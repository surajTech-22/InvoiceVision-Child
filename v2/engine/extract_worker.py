#!/usr/bin/env python3
"""InvoiceVisionChild v2 production OCR & GST verification worker.

Runs isolated locally via:
1) Multi-pass NIC e-Invoice QR decoder (ignoring UPI QR codes)
2) P2 preprocessing (PP-LCNet_x1_0_doc_ori orientation + safe crop + UVDoc dewarp + LAB)
3) Primary LightOnOCR-2-1B (Q8_0 GGUF via llama-server.exe)
4) Deterministic GST HTML/Markdown/OTSL parser + Mod-36 GSTIN & arithmetic audit
5) Math-gated escalation to Qwen3-VL-4B + consensus merge when primary fails math/GSTIN checks
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gst_math import audit_invoice_math
from gst_parser import normalize_canonical_dict, parse_document_text_to_canonical
from hybrid_merger import (
    QWEN_INVOICE_JSON_PROMPT,
    QWEN_INVOICE_JSON_SCHEMA,
    LlamaServerSession,
    img_to_data_url,
    math_fitness,
    merge_consensus,
)
from preprocess import configure_isolated_paddlex, preprocess_pages_p2, render_input_to_images, resize_max_side
from qr_decode import decode_qr_from_image
from supplier_memory import apply_supplier_memory, build_few_shot_prompt_hint

LIGHTON_PROMPT = "Extract all text and tables from this invoice accurately."


def emit_progress(enabled: bool, pct: int, message: str) -> None:
    if enabled:
        print(f"PROGRESS|{pct}|{message}", flush=True)


def resolve_default_paths() -> Dict[str, Path]:
    app_root = SCRIPT_DIR.parent
    runtime_candidates = [
        app_root / "Runtime",
        Path(r"C:\AccountingAutomationHub\InvoiceVisionChild\Runtime"),
        Path(r"C:\Users\welcome\.gemini\antigravity\scratch\InvoiceOcrLab"),
    ]
    llama_server: Optional[Path] = None
    models_dir: Optional[Path] = None
    paddlex_dir: Optional[Path] = None

    for root in runtime_candidates:
        if not root.exists():
            continue
        ls1 = root / "llama_bin" / "llama-server.exe"
        if llama_server is None and ls1.is_file():
            llama_server = ls1
        m1 = root / "models"
        if models_dir is None and (m1 / "lightonocr-2-1b").is_dir():
            models_dir = m1
        p1 = root / "cache"
        p2 = root / "paddlex"
        if paddlex_dir is None and p2.is_dir():
            paddlex_dir = root
        elif paddlex_dir is None and p1.is_dir():
            paddlex_dir = p1

    return {
        "llama_server": llama_server or (app_root / "Runtime" / "llama_bin" / "llama-server.exe"),
        "lighton_model": (models_dir or app_root / "Runtime" / "models") / "lightonocr-2-1b" / "LightOnOCR-2-1B-Q8_0.gguf",
        "lighton_mmproj": (models_dir or app_root / "Runtime" / "models") / "lightonocr-2-1b" / "mmproj-LightOnOCR-2-1B-f16.gguf",
        "qwen_model": (models_dir or app_root / "Runtime" / "models") / "qwen3-vl-4b" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
        "qwen_mmproj": (models_dir or app_root / "Runtime" / "models") / "qwen3-vl-4b" / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf",
        "paddlex_cache": paddlex_dir or (app_root / "Runtime"),
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_extraction(args: argparse.Namespace) -> Dict[str, Any]:
    t_start = time.perf_counter()
    defaults = resolve_default_paths()

    llama_server = Path(args.llama_server or defaults["llama_server"])
    lighton_model = Path(args.lighton_model or defaults["lighton_model"])
    lighton_mmproj = Path(args.lighton_mmproj or defaults["lighton_mmproj"])
    qwen_model = Path(args.qwen_model or defaults["qwen_model"])
    qwen_mmproj = Path(args.qwen_mmproj or defaults["qwen_mmproj"])
    paddlex_root = Path(args.paddlex_cache or defaults["paddlex_cache"])

    if not llama_server.is_file():
        raise FileNotFoundError(f"llama-server.exe missing: {llama_server}")
    if not lighton_model.is_file() or not lighton_mmproj.is_file():
        raise FileNotFoundError(f"LightOnOCR-2-1B model missing: {lighton_model}")

    input_paths = [Path(p).resolve() for p in args.input]
    for p in input_paths:
        if not p.is_file():
            raise FileNotFoundError(f"Source file not found: {p}")

    work_dir = Path(args.work_dir).resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="iv_work_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    log_dir = work_dir / "logs"

    if getattr(args, "cached_ocr_json", None):
        cached_path = Path(args.cached_ocr_json)
        if cached_path.is_file():
            try:
                cached_pages = json.loads(cached_path.read_text(encoding="utf-8-sig"))
                if isinstance(cached_pages, list) and len(cached_pages) == len(input_paths) and all(isinstance(x, str) and x.strip() for x in cached_pages):
                    emit_progress(args.progress, 60, f"Stitching {len(cached_pages)} cached OCR page(s)...")
                    qr_fast = decode_qr_from_image(str(input_paths[0]), [str(p) for p in input_paths[1:]])
                    combined_cached = "\n\n<!-- PAGE BREAK -->\n\n".join(x.strip() for x in cached_pages)
                    fast_canon = parse_document_text_to_canonical(
                        combined_cached,
                        qr_einvoice=qr_fast.get("einvoice"),
                        known_client_gstin=args.client_gstin,
                        direction_hint=args.direction,
                        qr_upi_meta=qr_fast.get("upi_meta"),
                    )
                    fast_mem = apply_supplier_memory(fast_canon, getattr(args, "memory_db", "") or "")
                    fast_audit = fast_canon.get("_audit") or audit_invoice_math(fast_canon)
                    if fast_audit.get("fully_balanced"):
                        emit_progress(args.progress, 96, "Cached multi-page stitch balanced cleanly.")
                        fast_canon.pop("_audit", None)
                        return {
                            "schema": "AAH-INVOICEVISION-WORKER-V1",
                            "engineUsed": "LightOnOCR-2-1B-P2 (Instant Multi-Page Stitch)",
                            "elapsedSec": round(time.perf_counter() - t_start, 2),
                            "preprocessing": [],
                            "preprocessedImages": [str(p) for p in input_paths],
                            "renderedPageImages": [str(p) for p in input_paths],
                            "qrInfo": qr_fast,
                            "sourceFiles": [{"path": str(p), "sha256": sha256_file(p), "fileBytes": p.stat().st_size} for p in input_paths],
                            "canonical": fast_canon,
                            "audit": fast_audit,
                            "supplierMemory": fast_mem,
                            "rawOcrText": combined_cached,
                            "rawTablesHtml": list(fast_canon.pop("rawTablesHtml", []) or []),
                        }
            except Exception:
                pass

    # Isolate PaddleX home BEFORE importing paddlex inside preprocess.py
    configure_isolated_paddlex(paddlex_root if (paddlex_root / "paddlex").is_dir() else paddlex_root.parent)
    if (paddlex_root / "official_models").is_dir():
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_root)
    elif (paddlex_root / "paddlex").is_dir():
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_root / "paddlex")

    emit_progress(args.progress, 5, "Checking QR code & rendering input pages...")
    raw_pages = render_input_to_images(input_paths, work_dir / "pages")
    if not raw_pages:
        raise RuntimeError("No image or PDF pages rendered.")

    qr_info = decode_qr_from_image(str(raw_pages[0]), [str(p) for p in raw_pages[1:]])
    qr_einv = qr_info.get("einvoice")
    qr_upi_meta = qr_info.get("upi_meta")

    emit_progress(args.progress, 15, f"Preprocessing {len(raw_pages)} page(s) (orientation + dewarp)...")
    prep_records = preprocess_pages_p2(
        raw_pages,
        work_dir,
        paddlex_cache_dir=Path(os.environ["PADDLE_PDX_CACHE_HOME"]),
        max_side=1536,
        progress_cb=lambda msg: emit_progress(args.progress, 22, msg),
    )
    p2_paths = [Path(str(r["p2_path"])) for r in prep_records]

    mode = (args.mode or "auto").strip().lower()
    raw_texts_lighton: List[str] = []
    canon_lighton: Optional[Dict[str, Any]] = None
    canon_qwen: Optional[Dict[str, Any]] = None
    engine_used = "LightOnOCR-2-1B-P2"

    memory_db = getattr(args, "memory_db", "") or ""
    memory_meta: Dict[str, Any] = {
        "profileFound": False,
        "gstin": "",
        "canonicalName": "",
        "confirmedCount": 0,
        "preferredDirection": "",
        "preferredRecognitionMode": "",
        "appliedRules": [],
    }
    if mode != "qwen":
        emit_progress(args.progress, 32, f"Running LightOnOCR-2-1B on {len(p2_paths)} preprocessed page(s)...")
        with LlamaServerSession(str(llama_server), str(lighton_model), str(lighton_mmproj), log_dir, threads=args.threads, repeat_penalty=1.12) as srv:
            for idx, p2_img in enumerate(p2_paths, 1):
                emit_progress(args.progress, 35 + int(25 * idx / len(p2_paths)), f"LightOnOCR-2-1B reading page {idx}/{len(p2_paths)}...")
                txt = srv.chat_image(img_to_data_url(str(p2_img)), LIGHTON_PROMPT, max_tokens=4096, timeout_s=360)
                raw_texts_lighton.append(txt)

        combined_lighton = "\n\n<!-- PAGE BREAK -->\n\n".join(raw_texts_lighton)
        canon_lighton = parse_document_text_to_canonical(
            combined_lighton,
            qr_einvoice=qr_einv,
            known_client_gstin=args.client_gstin,
            direction_hint=args.direction,
            qr_upi_meta=qr_upi_meta,
        )
        memory_meta = apply_supplier_memory(canon_lighton, memory_db)
        final_canon = canon_lighton
        final_raw = combined_lighton
    else:
        combined_lighton = ""
        final_canon = {}
        final_raw = ""

    need_escalation = False
    is_partial_continuation = (
        len(p2_paths) == 1
        and canon_lighton is not None
        and len(canon_lighton.get("rows") or []) > 0
        and float(canon_lighton.get("invoiceTotal") or 0.0) <= 0.0
        and bool(canon_lighton.get("invoiceNumber"))
        and bool((canon_lighton.get("_audit") or {}).get("seller_gstin_valid"))
        and bool(re.search(r"\b(?:cont\.?\s*page\s*\d+|page\s*1\s*(?:of|/)\s*[2-9]|carry\s*forward|carried\s*forward|to\s+be\s+continued)\b", combined_lighton, re.IGNORECASE))
    )
    if is_partial_continuation:
        engine_used = "LightOnOCR-2-1B-P2 (Partial Page)"
    elif mode == "qwen":
        need_escalation = True
    elif mode in ("auto", "hybrid") and canon_lighton is not None:
        audit = canon_lighton.get("_audit") or {}
        if (
            not audit.get("fully_balanced")
            or audit.get("row_count", 0) == 0
            or not audit.get("seller_gstin_valid")
            or not audit.get("buyer_gstin_valid")
        ):
            need_escalation = True

    if need_escalation and qwen_model.is_file() and qwen_mmproj.is_file():
        emit_progress(args.progress, 65, "Escalating math/GSTIN verification to Qwen3-VL-4B...")
        try:
            import cv2

            seller_obj = (canon_lighton or {}).get("seller") or {}
            few_shot_hint = build_few_shot_prompt_hint(
                memory_db,
                str(seller_obj.get("gstin") or ""),
                str(seller_obj.get("name") or ""),
            )
            qwen_prompt = QWEN_INVOICE_JSON_PROMPT + few_shot_hint

            qwen_dir = work_dir / "qwen_scaled"
            qwen_dir.mkdir(parents=True, exist_ok=True)
            qwen_replies: List[str] = []
            with LlamaServerSession(str(llama_server), str(qwen_model), str(qwen_mmproj), log_dir, threads=args.threads) as srv:
                for idx, p2_img in enumerate(p2_paths, 1):
                    emit_progress(args.progress, 70 + int(22 * idx / len(p2_paths)), f"Qwen3-VL-4B verifying page {idx}/{len(p2_paths)}...")
                    # Cap escalated Qwen input at 1280px max side so CPU inference finishes fast (~2 min)
                    bgr = cv2.imread(str(p2_img))
                    q_img = p2_img
                    if bgr is not None and max(bgr.shape[:2]) > 1280:
                        q_img = qwen_dir / p2_img.name
                        cv2.imwrite(str(q_img), resize_max_side(bgr, 1280))
                    reply = srv.chat_image(
                        img_to_data_url(str(q_img)),
                        qwen_prompt,
                        max_tokens=2400,
                        timeout_s=420,
                        json_schema=QWEN_INVOICE_JSON_SCHEMA,
                    )
                    qwen_replies.append(reply)

            page_canons = [
                parse_document_text_to_canonical(r, qr_einvoice=qr_einv, known_client_gstin=args.client_gstin, direction_hint=args.direction, qr_upi_meta=qr_upi_meta)
                for r in qwen_replies
            ]
            if len(page_canons) == 1:
                canon_qwen = page_canons[0]
            else:
                merged_obj = dict(page_canons[0])
                all_rows = []
                for pc in page_canons:
                    all_rows.extend(pc.get("rows") or [])
                merged_obj["rows"] = all_rows
                merged_obj["taxableTotal"] = 0.0
                merged_obj["discountTotal"] = 0.0
                merged_obj["cgstTotal"] = 0.0
                merged_obj["sgstTotal"] = 0.0
                merged_obj["igstTotal"] = 0.0
                merged_obj["cessTotal"] = 0.0
                for pc in reversed(page_canons):
                    if float(pc.get("invoiceTotal") or 0.0) > 0:
                        merged_obj["invoiceTotal"] = pc["invoiceTotal"]
                        merged_obj["roundOff"] = pc.get("roundOff", 0.0)
                        merged_obj["creditNoteTotal"] = pc.get("creditNoteTotal", 0.0)
                        break
                canon_qwen = normalize_canonical_dict(merged_obj, "\n\n".join(qwen_replies), qr_einv, qr_upi_meta=qr_upi_meta)

            if canon_lighton is not None:
                final_canon = merge_consensus([canon_lighton, canon_qwen], qr_einv=qr_einv, qr_upi_meta=qr_upi_meta)
                engine_used = "Hybrid(LightOnOCR-2-1B+Qwen3-VL-4B)"
                final_raw = combined_lighton + "\n\n===== QWEN3-VL-4B VERIFICATION =====\n" + "\n\n".join(qwen_replies)
            else:
                final_canon = canon_qwen
                engine_used = "Qwen3-VL-4B-P2"
                final_raw = "\n\n".join(qwen_replies)
            memory_meta = apply_supplier_memory(final_canon, memory_db)
        except Exception as esc_ex:
            if canon_lighton is None:
                raise
            emit_progress(args.progress, 94, f"Qwen3-VL-4B fallback skipped ({type(esc_ex).__name__}); keeping LightOnOCR-2-1B output.")
            final_raw = combined_lighton + f"\n\n[Escalation note: {esc_ex}]"

    emit_progress(args.progress, 95, "Finalizing GST math audit & canonical JSON...")
    elapsed = round(time.perf_counter() - t_start, 2)
    audit = final_canon.pop("_audit", None) or audit_invoice_math(final_canon)

    payload = {
        "schema": "AAH-INVOICEVISION-WORKER-V1",
        "engineUsed": engine_used,
        "elapsedSec": elapsed,
        "preprocessing": prep_records,
        "preprocessedImages": [str(p) for p in p2_paths],
        "renderedPageImages": [str(p) for p in raw_pages],
        "qrInfo": qr_info,
        "sourceFiles": [{"path": str(p), "sha256": sha256_file(p), "fileBytes": p.stat().st_size} for p in input_paths],
        "canonical": final_canon,
        "audit": audit,
        "supplierMemory": memory_meta,
        "rawOcrText": final_raw,
        "rawTablesHtml": list(final_canon.pop("rawTablesHtml", []) or []),
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="InvoiceVisionChild v2 OCR worker")
    parser.add_argument("--input", action="append", required=True, help="Source image or PDF (repeatable)")
    parser.add_argument("--output", required=True, help="Output worker JSON path")
    parser.add_argument("--work-dir", help="Scratch directory for intermediate rendered/preprocessed pages")
    parser.add_argument("--mode", default="auto", choices=["auto", "fast", "hybrid", "qwen"])
    parser.add_argument("--client-gstin", default="")
    parser.add_argument("--direction", default="Auto")
    parser.add_argument("--llama-server")
    parser.add_argument("--lighton-model")
    parser.add_argument("--lighton-mmproj")
    parser.add_argument("--qwen-model")
    parser.add_argument("--qwen-mmproj")
    parser.add_argument("--paddlex-cache")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--memory-db", default="", help="Optional path to SQLite supplier_memory.db")
    parser.add_argument("--cached-ocr-json", help="Optional JSON array of per-page cached LightOnOCR strings for instant multi-page stitching")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".json.tmp")
    result = run_extraction(args)
    tmp_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, out_path)
    emit_progress(args.progress, 100, f"Done in {result['elapsedSec']}s ({result['engineUsed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
