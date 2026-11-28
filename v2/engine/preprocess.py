from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageOps

_PDX_MODEL_LOCK = threading.Lock()
_PDX_PREDICT_LOCK = threading.Lock()
_PDX_MODELS: Dict[str, Tuple[object, object]] = {}


def configure_isolated_paddlex(cache_root: Path) -> None:
    cache_home = cache_root / "home"
    cache_paddlex = cache_root / "paddlex"
    cache_xdg = cache_root / "xdg"
    for d in (cache_home, cache_paddlex, cache_xdg):
        d.mkdir(parents=True, exist_ok=True)
    os.environ["USERPROFILE"] = str(cache_home)
    os.environ["HOME"] = str(cache_home)
    os.environ["XDG_CACHE_HOME"] = str(cache_xdg)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_paddlex)
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


def load_exif_bgr(path: str) -> np.ndarray:
    pil = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def render_input_to_images(input_paths: List[Path], pages_dir: Path, pdf_dpi: int = 200) -> List[Path]:
    """Normalize input images or render PDF pages cleanly into PNGs without altering originals."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    out: List[Path] = []
    idx = 0
    for src in input_paths:
        ext = src.suffix.lower()
        if ext == ".pdf":
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(str(src))
            try:
                for pno in range(len(doc)):
                    idx += 1
                    page = doc[pno]
                    try:
                        dst = pages_dir / f"page_{idx:03d}.png"
                        page.render(scale=pdf_dpi / 72.0).to_pil().save(str(dst))
                        out.append(dst)
                    finally:
                        page.close()
            finally:
                doc.close()
        else:
            idx += 1
            dst = pages_dir / f"page_{idx:03d}.png"
            pil = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            pil.save(str(dst), "PNG")
            out.append(dst)
    return out


def safe_sheet_crop(img_bgr: np.ndarray) -> Tuple[np.ndarray, str]:
    """Safely trim large dark desk/keyboard borders while never clipping bright white paper edges."""
    h, w = img_bgr.shape[:2]
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    bright_mask = ((hsv[:, :, 2] >= 115) & (hsv[:, :, 1] <= 95)).astype(np.uint8) * 255

    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, w // 45), max(15, h // 45)))
    closed = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, k_close)
    k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 90), max(9, h // 90)))
    cleaned = cv2.morphologyEx(closed, cv2.MORPH_OPEN, k_open)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img_bgr, "no_contour"

    largest = max(contours, key=cv2.contourArea)
    area_ratio = cv2.contourArea(largest) / float(w * h)
    if area_ratio < 0.18 or area_ratio > 0.94:
        return img_bgr, f"skip_area_{area_ratio:.2f}"

    x, y, bw, bh = cv2.boundingRect(largest)
    pad_x = int(bw * 0.025)
    pad_y = int(bh * 0.025)
    x0 = max(0, x - pad_x)
    y0 = max(0, y - pad_y)
    x1 = min(w, x + bw + pad_x)
    y1 = min(h, y + bh + pad_y)

    rect = cv2.minAreaRect(largest)
    angle = rect[-1]
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90

    cropped = img_bgr[y0:y1, x0:x1]
    if 0.6 <= abs(angle) <= 10.0:
        ch, cw = cropped.shape[:2]
        M = cv2.getRotationMatrix2D((cw / 2.0, ch / 2.0), angle, 1.0)
        cos = abs(M[0, 0])
        sin = abs(M[0, 1])
        nw = int((ch * sin) + (cw * cos))
        nh = int((ch * cos) + (cw * sin))
        M[0, 2] += (nw / 2.0) - cw / 2.0
        M[1, 2] += (nh / 2.0) - ch / 2.0
        cropped = cv2.warpAffine(
            cropped, M, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(245, 245, 245)
        )
        return cropped, f"crop_deskew({area_ratio:.2f},ang={angle:.1f})"

    return cropped, f"crop_only({area_ratio:.2f})"


def normalize_lighting_gentle(img_bgr: np.ndarray) -> np.ndarray:
    """Gentle LAB luminance shadow leveling without destroying faint decimal dots or stamps."""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    k = max(51, (min(img_bgr.shape[:2]) // 18) | 1)
    bg = cv2.GaussianBlur(l, (k, k), 0)
    l_f = l.astype(np.float32)
    bg_f = np.maximum(bg.astype(np.float32), 20.0)
    l_norm = np.clip((l_f / bg_f) * 215.0, 0, 255)
    l_blend = np.clip(0.65 * l_norm + 0.35 * l_f, 0, 255).astype(np.uint8)

    clahe = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(8, 8))
    l_final = clahe.apply(l_blend)

    merged = cv2.merge([l_final, a, b])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def resize_max_side(img_bgr: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img_bgr
    scale = max_side / float(m)
    return cv2.resize(img_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)


def _get_paddlex_models(paddlex_cache_dir: Optional[Path]) -> Tuple[object, object]:
    """Load PP-LCNet_x1_0_doc_ori and UVDoc once per process so warm daemon skips reload overhead."""
    cache_key = str(paddlex_cache_dir or os.environ.get("PADDLE_PDX_CACHE_HOME") or "default")
    with _PDX_MODEL_LOCK:
        if cache_key in _PDX_MODELS:
            return _PDX_MODELS[cache_key]
        if paddlex_cache_dir is not None:
            paddlex_cache_dir.mkdir(parents=True, exist_ok=True)
            os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_cache_dir)
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddlex import create_model

        ori_model = create_model("PP-LCNet_x1_0_doc_ori")
        unwarp_model = create_model("UVDoc")
        _PDX_MODELS[cache_key] = (ori_model, unwarp_model)
        return ori_model, unwarp_model


def crop_footer_strip(p2_img_path: Path, dst_path: Path, top_ratio: float = 0.50) -> Path:
    """Create a zoomed footer crop for fast Stage-2 targeted footer/total recovery."""
    img = cv2.imread(str(p2_img_path))
    if img is None:
        return p2_img_path
    h, w = img.shape[:2]
    y0 = max(0, min(h - 120, int(h * top_ratio)))
    crop = img[y0:h, 0:w]
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst_path), crop)
    return dst_path


def _preprocess_single_page(
    idx: int,
    total: int,
    page_path: Path,
    p2_dir: Path,
    max_side: int,
    ori_model: object,
    unwarp_model: object,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    rot_map = {
        "0": None,
        "90": cv2.ROTATE_90_COUNTERCLOCKWISE,
        "180": cv2.ROTATE_180,
        "270": cv2.ROTATE_90_CLOCKWISE,
    }
    if progress_cb:
        progress_cb(f"Preprocessing page {idx}/{total} (orientation, crop, UVDoc dewarp)...")
    img_p0 = load_exif_bgr(str(page_path))

    with _PDX_PREDICT_LOCK:
        ori_res = list(ori_model.predict(str(page_path)))
    ori_label = "0"
    ori_score = 0.0
    if ori_res:
        r0 = ori_res[0]
        labels = r0.get("label_names") or []
        scores = r0.get("scores") or []
        if labels:
            ori_label = str(labels[0])
            ori_score = float(scores[0]) if scores else 0.0

    img_rot = img_p0
    if ori_label in rot_map and rot_map[ori_label] is not None:
        img_rot = cv2.rotate(img_p0, rot_map[ori_label])

    img_p1, crop_info = safe_sheet_crop(img_rot)
    img_p1_capped = resize_max_side(img_p1, 2048)
    p1_path = p2_dir / f"{page_path.stem}_p1.png"
    cv2.imwrite(str(p1_path), img_p1_capped)

    with _PDX_PREDICT_LOCK:
        unwarp_res = list(unwarp_model.predict(str(p1_path)))
    if unwarp_res and "doctr_img" in unwarp_res[0] and isinstance(unwarp_res[0]["doctr_img"], np.ndarray):
        img_uv_bgr = cv2.cvtColor(unwarp_res[0]["doctr_img"], cv2.COLOR_RGB2BGR)
    else:
        img_uv_bgr = img_p1_capped

    img_clean = normalize_lighting_gentle(img_uv_bgr)
    img_p2 = resize_max_side(img_clean, max_side)
    p2_path = p2_dir / f"{page_path.stem}_p2.png"
    cv2.imwrite(str(p2_path), img_p2)

    return {
        "raw_page": str(page_path),
        "p2_path": str(p2_path),
        "ori_label": ori_label,
        "ori_score": round(ori_score, 4),
        "crop_info": crop_info,
        "p2_shape": list(img_p2.shape[:2]),
    }


def preprocess_pages_p2(
    raw_pages: List[Path],
    work_dir: Path,
    paddlex_cache_dir: Optional[Path] = None,
    max_side: int = 1536,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, object]]:
    """Run P2 preprocessing (singleton PP-LCNet_x1_0_doc_ori + safe crop + UVDoc dewarp + gentle LAB) per page."""
    if progress_cb:
        progress_cb("Loading document orientation & UVDoc dewarping models...")
    ori_model, unwarp_model = _get_paddlex_models(paddlex_cache_dir)

    p2_dir = work_dir / "preprocessed"
    p2_dir.mkdir(parents=True, exist_ok=True)
    total = len(raw_pages)
    if total <= 1:
        return [
            _preprocess_single_page(idx, total, pp, p2_dir, max_side, ori_model, unwarp_model, progress_cb)
            for idx, pp in enumerate(raw_pages, 1)
        ]

    with ThreadPoolExecutor(max_workers=min(4, total), thread_name_prefix="PagePrepChild") as pool:
        futs = [
            pool.submit(_preprocess_single_page, idx, total, pp, p2_dir, max_side, ori_model, unwarp_model, progress_cb)
            for idx, pp in enumerate(raw_pages, 1)
        ]
        return [f.result() for f in futs]
