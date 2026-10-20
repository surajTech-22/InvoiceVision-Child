#!/usr/bin/env python3
"""Real CPU OCR smoke/benchmark on *synthetic* documents; not field-accuracy certification."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def make_font(size):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def generate(out):
    out.mkdir(parents=True, exist_ok=True)
    tests = []
    variants = [
        [
            ("TAX INVOICE", 82, 35, 31),
            ("SUPPLIER: SUNRISE TRADERS", 55, 120, 22),
            ("BUYER: GENERAL STORES", 55, 170, 22),
            ("Invoice No: INV-0724", 690, 120, 22),
            ("Date: 20-10-2026", 690, 170, 22),
            ("ITEM", 75, 265, 21), ("QTY", 530, 265, 21),
            ("RATE", 720, 265, 21), ("AMOUNT", 925, 265, 21),
            ("Rice", 75, 325, 21), ("10", 530, 325, 21),
            ("50", 720, 325, 21), ("500", 925, 325, 21),
            ("TOTAL 500", 835, 445, 24),
        ],
        [
            ("CREDIT NOTE", 680, 44, 30),
            ("Billed to: GREEN ENTERPRISES", 60, 130, 23),
            ("Sold by: MARKET SUPPLIES", 60, 185, 23),
            ("Ref No: CN-104", 620, 238, 22),
            ("Dated 20/10/2026", 620, 277, 22),
            ("Description", 70, 340, 21), ("Units", 540, 340, 21),
            ("Price", 745, 340, 21), ("Value", 935, 340, 21),
            ("Packing", 70, 395, 22), ("5", 540, 395, 22),
            ("40", 745, 395, 22), ("200", 935, 395, 22),
        ],
        [
            ("INVOICE", 470, 44, 35),
            ("From: BLUE SERVICES", 60, 135, 22),
            ("Ship To: TRADING COMPANY", 60, 185, 22),
            ("Invoice # A00168", 665, 135, 22),
            ("Invoice Date 18 OCT 2026", 655, 185, 22),
            ("Particulars", 75, 295, 22), ("Quantity", 535, 295, 22),
            ("Unit Rate", 725, 295, 22), ("Line Total", 930, 295, 22),
            ("Service charge", 75, 365, 22), ("2", 535, 365, 22),
            ("300", 725, 365, 22), ("600", 930, 365, 22),
        ],
    ]
    for index, rows in enumerate(variants, 1):
        im = Image.new("RGB", (1260, 620), "white")
        draw = ImageDraw.Draw(im)
        draw.rectangle((26, 20, 1232, 595), outline=(0, 0, 0), width=2)
        for text, x, y, size in rows:
            draw.text((x, y), text, fill=(0, 0, 0), font=make_font(size))
        draw.line((55, 258 if index == 1 else 326, 1210,
                   258 if index == 1 else 326), fill=(25, 25, 25), width=2)
        path = out / f"synthetic_{index}.png"
        im.save(path)
        tests.append({"path": str(path), "name": path.name,
                      "expected": [r[0] for r in rows[:5]],
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return tests

def read_rapid(image_path):
    from rapidocr import RapidOCR
    if not hasattr(read_rapid, "_engine"):
        read_rapid._engine = RapidOCR()
    result = read_rapid._engine(str(image_path))
    texts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    if texts is None and isinstance(result, tuple) and result:
        blocks = result[0] or []
        texts = [b[1] for b in blocks if isinstance(b, (list, tuple)) and len(b) > 1]
        boxes = [b[0] for b in blocks if isinstance(b, (list, tuple)) and len(b) > 1]
    if texts is None:
        raise RuntimeError("RapidOCR returned no usable OCR result schema")
    return [str(x) for x in texts], (boxes.tolist() if hasattr(boxes, "tolist") else boxes)

def read_paddle(image_path):
    from paddleocr import PaddleOCR
    if not hasattr(read_paddle, "_engine"):
        read_paddle._engine = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
            device="cpu",
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            text_recognition_batch_size=1)
    data = read_paddle._engine.predict(input=str(image_path))
    if not data:
        raise RuntimeError("PaddleOCR predict returned empty")
    entry = data[0]
    payload = getattr(entry, "json", None)
    payload = payload() if callable(payload) else payload
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected PaddleOCR result format")
    res = payload.get("res", payload)
    texts = res.get("rec_texts", [])
    boxes = res.get("rec_polys", res.get("rec_boxes", []))
    if hasattr(boxes, "tolist"):
        boxes = boxes.tolist()
    if not texts:
        raise RuntimeError("PaddleOCR returned no detected text")
    return [str(x) for x in texts], boxes

def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()

def run():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["rapidocr", "paddleocr"], required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cases = generate(args.out / "synthetic_images")
    results = []
    for case in cases:
        t0 = time.monotonic()
        try:
            texts, boxes = (read_rapid(case["path"]) if args.engine == "rapidocr"
                            else read_paddle(case["path"]))
            elapsed = round(time.monotonic()-t0, 3)
            combined = normalize(" ".join(texts))
            # These are synthetic string-presence checks, NOT exact semantic accuracy.
            required = {label: normalize(label) in combined for label in case["expected"]}
            result = {"name": case["name"], "status": "PASS" if all(required.values()) else "PARTIAL",
                      "source_sha256": case["sha256"], "seconds": elapsed,
                      "recognized_text_lines": len(texts), "expected_cue_presence": required,
                      "texts": texts, "boxes": boxes}
        except Exception as exc:
            result = {"name": case["name"], "status": "ERROR", "error": str(exc),
                      "traceback": traceback.format_exc()}
        results.append(result)
        (args.out / f"{Path(case['name']).stem}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"{case['name']}: {result['status']}", flush=True)
    passed = len([r for r in results if r["status"] == "PASS"])
    report = {"engine": args.engine, "kind": "SYNTHETIC_LIVE_INFERENCE_ONLY",
              "passed": passed, "total": len(cases),
              "source_based_layout_accuracy_certified": False,
              "note": "Do not use this result alone to select production invoice models.",
              "results": [{k:v for k,v in r.items() if k not in {"texts","boxes","traceback"}} for r in results]}
    (args.out / "REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if passed != len(cases):
        raise SystemExit("Model inference or synthetic cue-presence benchmark did not pass")

if __name__ == "__main__":
    run()
