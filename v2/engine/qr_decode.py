from __future__ import annotations

import base64
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from PIL import Image, ImageOps
import zxingcpp


def decode_b64url(s: str) -> bytes:
    s = s.strip()
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def parse_upi_invoice_meta(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None
    s = raw_text.strip()
    if not s.lower().startswith("upi://"):
        return None
    try:
        parsed = urlparse(s)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        lowered = {k.lower(): (v[0].strip() if v else "") for k, v in qs.items()}
        gstin = re.sub(r"[^A-Za-z0-9]", "", lowered.get("gstin") or "").upper()
        if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin):
            gstin = ""
        inv_no = (lowered.get("invoiceno") or lowered.get("tr") or "").strip()
        payee = (lowered.get("pn") or "").strip()
        amt = (lowered.get("am") or "").strip()
        if not gstin and not inv_no:
            return None
        return {
            "sellerGstin": gstin,
            "payeeName": payee,
            "invoiceNo": inv_no,
            "amount": amt,
        }
    except Exception:
        return None


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


def _prep_variants(crop_bgr: np.ndarray, heavy: bool = False) -> List[tuple]:
    out = [("orig", crop_bgr)]
    h, w = crop_bgr.shape[:2]
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
    out.append(("clahe", cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR)))
    if heavy:
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        out.append(("otsu", cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR)))
        if max(h, w) < 1800:
            up2 = cv2.resize(crop_bgr, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            out.append(("up2", up2))
            up2_gray = cv2.cvtColor(up2, cv2.COLOR_BGR2GRAY)
            up2_clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(up2_gray)
            out.append(("up2_clahe", cv2.cvtColor(up2_clahe, cv2.COLOR_GRAY2BGR)))
    return out


def _decode_single(image_path: str) -> Dict[str, Any]:
    pil_img = ImageOps.exif_transpose(Image.open(image_path)).convert("RGB")
    img_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    state_lock = threading.Lock()
    stop_event = threading.Event()
    raw_codes: List[str] = []
    seen_texts = set()
    einvoice: Optional[Dict[str, Any]] = None
    upi_codes: List[str] = []
    upi_meta: Optional[Dict[str, Any]] = None
    decode_pass = None

    def try_region(region_name: str, region_bgr: np.ndarray, heavy: bool = False) -> bool:
        nonlocal einvoice, upi_meta, decode_pass
        if stop_event.is_set():
            return False
        qr_det = cv2.QRCodeDetector()
        for vname, var in _prep_variants(region_bgr, heavy=heavy):
            if stop_event.is_set():
                return False
            texts = _scan_array(var, qr_det)
            for t in texts:
                parsed = parse_einvoice_jwt(t)
                with state_lock:
                    if t not in seen_texts:
                        seen_texts.add(t)
                        raw_codes.append(t)
                        if t.strip().lower().startswith("upi://"):
                            upi_codes.append(t)
                            if upi_meta is None:
                                upi_meta = parse_upi_invoice_meta(t)
                    if parsed and einvoice is None:
                        einvoice = parsed
                        decode_pass = f"{region_name}:{vname}"
                        stop_event.set()
                        return True
        return False

    # Fast path: zxingcpp.read_barcodes(try_rotate=True) natively checks 0/90/180/270 in C++
    if not try_region("full_rot0", img_bgr, heavy=False):
        h, w = img_bgr.shape[:2]
        # Wave 1: lightweight quadrant scan across natural orientation (all 4 angles handled by try_rotate=True)
        quads = [
            ("quad_tr", img_bgr[0:int(h * 0.50), int(w * 0.50):w]),
            ("quad_br", img_bgr[int(h * 0.50):h, int(w * 0.50):w]),
            ("quad_tl", img_bgr[0:int(h * 0.50), 0:int(w * 0.50)]),
            ("quad_bl", img_bgr[int(h * 0.50):h, 0:int(w * 0.50)]),
            ("quad_mid_r", img_bgr[int(h * 0.15):int(h * 0.65), int(w * 0.45):w]),
        ]
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="QRChild") as pool:
            for f in [pool.submit(try_region, rn, reg, False) for rn, reg in quads]:
                f.result()
            if not stop_event.is_set():
                # Wave 2: upscaled/otsu pass on natural orientation quadrants
                for f in [pool.submit(try_region, rn, reg, True) for rn, reg in quads[:4]]:
                    f.result()
            if not stop_event.is_set():
                # Wave 3: 90/270/180 rotated quadrants with heavy upscaling ONLY if e-Invoice QR wasn't found upright
                rot_tasks: List[tuple] = []
                for rot_name, k in [("rot90", 1), ("rot270", 3), ("rot180", 2)]:
                    rot_img = np.rot90(img_bgr, k).copy()
                    rh, rw = rot_img.shape[:2]
                    rot_tasks.extend([
                        (f"{rot_name}_tr", rot_img[0:int(rh * 0.50), int(rw * 0.50):rw]),
                        (f"{rot_name}_br", rot_img[int(rh * 0.50):rh, int(rw * 0.50):rw]),
                        (f"{rot_name}_tl", rot_img[0:int(rh * 0.50), 0:int(rw * 0.50)]),
                        (f"{rot_name}_bl", rot_img[int(rh * 0.50):rh, 0:int(rw * 0.50)]),
                    ])
                for b0 in range(0, len(rot_tasks), 4):
                    if stop_event.is_set():
                        break
                    for f in [pool.submit(try_region, rn, reg, True) for rn, reg in rot_tasks[b0:b0 + 4]]:
                        f.result()

    return {
        "raw_codes": raw_codes,
        "upi_codes": upi_codes,
        "upi_meta": upi_meta,
        "einvoice": einvoice,
        "decode_pass": decode_pass,
    }


def decode_qr_from_image(image_path: str, extra_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    paths = [image_path] + [p for p in (extra_paths or []) if p and os.path.exists(p)]
    if len(paths) <= 1:
        results = [_decode_single(p) for p in paths]
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(paths)), thread_name_prefix="QRPageChild") as pool:
            results = list(pool.map(_decode_single, paths))
    all_raw: List[str] = []
    all_upi: List[str] = []
    einvoice: Optional[Dict[str, Any]] = None
    upi_meta: Optional[Dict[str, Any]] = None
    decode_pass = None
    for r in results:
        for code in r["raw_codes"]:
            if code not in all_raw:
                all_raw.append(code)
        for code in r["upi_codes"]:
            if code not in all_upi:
                all_upi.append(code)
        if r.get("upi_meta") and upi_meta is None:
            upi_meta = r["upi_meta"]
        if r["einvoice"] and einvoice is None:
            einvoice = r["einvoice"]
            decode_pass = r["decode_pass"]
    return {
        "image": os.path.basename(image_path),
        "einvoice_found": einvoice is not None,
        "decode_pass": decode_pass,
        "einvoice": einvoice,
        "upi_meta": upi_meta,
        "raw_codes": all_raw,
        "upi_ignored_count": len(all_upi),
        "other_qr_count": max(0, len(all_raw) - len(all_upi) - (1 if einvoice else 0)),
    }
