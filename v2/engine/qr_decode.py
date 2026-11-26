from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from PIL import Image, ImageOps
import zxingcpp


def decode_b64url(s: str) -> bytes:
    s = s.strip()
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def parse_einvoice_jwt(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    s = raw_text.strip()
    if s.lower().startswith("upi://"):
        return None
    if s.count(".") >= 2 and s.startswith("eyJ"):
        parts = s.split(".")
        try:
            payload = json.loads(decode_b64url(parts[1]).decode("utf-8", errors="replace"))
            data_field = payload.get("data")
            if isinstance(data_field, str):
                inner = json.loads(data_field)
            elif isinstance(data_field, dict):
                inner = data_field
            else:
                inner = payload
            if isinstance(inner, dict) and any(k in inner for k in ("SellerGstin", "BuyerGstin", "DocNo", "Irn")):
                return inner
        except Exception:
            return None
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            if isinstance(obj, dict) and any(k in obj for k in ("SellerGstin", "BuyerGstin", "DocNo", "Irn")):
                return obj
        except Exception:
            return None
    return None


def _scan_array(img_bgr: np.ndarray, qr_det: cv2.QRCodeDetector) -> List[str]:
    found: List[str] = []
    try:
        for res in zxingcpp.read_barcodes(img_bgr, try_rotate=True, try_downscale=True):
            if res.text:
                found.append(res.text)
    except Exception:
        pass
    try:
        ok, decoded_info, _, _ = qr_det.detectAndDecodeMulti(img_bgr)
        if ok and decoded_info is not None:
            for item in decoded_info:
                if item:
                    found.append(item)
    except Exception:
        pass
    if not found:
        try:
            val, _, _ = qr_det.detectAndDecode(img_bgr)
            if val:
                found.append(val)
        except Exception:
            pass
    return found


def _prep_variants(crop_bgr: np.ndarray) -> List[tuple]:
    out = [("orig", crop_bgr)]
    h, w = crop_bgr.shape[:2]
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
    sharp = cv2.addWeighted(gray, 1.8, blur, -0.8, 0)
    out.append(("sharp", cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)))
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    out.append(("otsu", cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)))
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    out.append(("clahe", cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)))
    if max(h, w) < 1800:
        up2 = cv2.resize(crop_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        out.append(("up2", up2))
        up2_gray = cv2.cvtColor(up2, cv2.COLOR_BGR2GRAY)
        up2_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(up2_gray)
        out.append(("up2_clahe", cv2.cvtColor(up2_clahe, cv2.COLOR_GRAY2BGR)))
        thr = cv2.adaptiveThreshold(up2_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10)
        out.append(("up2_adapt", cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR)))
    return out


def _decode_single(image_path: str) -> Dict[str, Any]:
    pil_img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    img_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    qr_det = cv2.QRCodeDetector()

    raw_codes: List[str] = []
    seen_texts = set()
    einvoice: Optional[Dict[str, Any]] = None
    upi_codes: List[str] = []
    decode_pass = None

    def try_region(region_name: str, region_bgr: np.ndarray) -> bool:
        nonlocal einvoice, decode_pass
        for vname, var in _prep_variants(region_bgr):
            texts = _scan_array(var, qr_det)
            for t in texts:
                if t not in seen_texts:
                    seen_texts.add(t)
                    raw_codes.append(t)
                    if t.strip().lower().startswith("upi://"):
                        upi_codes.append(t)
                parsed = parse_einvoice_jwt(t)
                if parsed and einvoice is None:
                    einvoice = parsed
                    decode_pass = f"{region_name}:{vname}"
                    return True
        return False

    for rot_name, k in [("rot0", 0), ("rot90", 1), ("rot270", 3), ("rot180", 2)]:
        rot_img = img_bgr if k == 0 else np.rot90(img_bgr, k).copy()
        h, w = rot_img.shape[:2]
        if rot_name == "rot0":
            if try_region("full_rot0", rot_img):
                break
        regions = [
            (f"{rot_name}_tr", rot_img[0:int(h * 0.50), int(w * 0.50):w]),
            (f"{rot_name}_br", rot_img[int(h * 0.50):h, int(w * 0.50):w]),
            (f"{rot_name}_tl", rot_img[0:int(h * 0.50), 0:int(w * 0.50)]),
            (f"{rot_name}_bl", rot_img[int(h * 0.50):h, 0:int(w * 0.50)]),
            (f"{rot_name}_mid_r", rot_img[int(h * 0.15):int(h * 0.65), int(w * 0.45):w]),
        ]
        found_einvoice = False
        for rname, reg in regions:
            if try_region(rname, reg):
                found_einvoice = True
                break
        if found_einvoice:
            break

    return {
        "raw_codes": raw_codes,
        "upi_codes": upi_codes,
        "einvoice": einvoice,
        "decode_pass": decode_pass,
    }


def decode_qr_from_image(image_path: str, extra_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    paths = [image_path] + [p for p in (extra_paths or []) if p and os.path.exists(p)]
    results = [_decode_single(p) for p in paths]
    all_raw: List[str] = []
    all_upi: List[str] = []
    einvoice: Optional[Dict[str, Any]] = None
    decode_pass = None
    for r in results:
        for code in r["raw_codes"]:
            if code not in all_raw:
                all_raw.append(code)
        for code in r["upi_codes"]:
            if code not in all_upi:
                all_upi.append(code)
        if r["einvoice"] and einvoice is None:
            einvoice = r["einvoice"]
            decode_pass = r["decode_pass"]
    return {
        "image": os.path.basename(image_path),
        "einvoice_found": einvoice is not None,
        "decode_pass": decode_pass,
        "einvoice": einvoice,
        "raw_codes": all_raw,
        "upi_ignored_count": len(all_upi),
        "other_qr_count": max(0, len(all_raw) - len(all_upi) - (1 if einvoice else 0)),
    }
