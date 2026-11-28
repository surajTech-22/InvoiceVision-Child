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
    apply_qwen_escalation_to_worker_payload,
    escalate_with_qwen,
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
        "qwen_text_model": (models_dir or app_root / "Runtime" / "models") / "qwen3-1.7b" / "Qwen3-1.7B-Q4_K_M.gguf",
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
    qwen_text_model = Path(getattr(args, "qwen_text_model", "") or defaults["qwen_text_model"])
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
                    if fast_canon and (fast_canon.get("rows") or fast_canon.get("invoiceNumber") or fast_canon.get("invoiceTotal")):
                        emit_progress(args.progress, 96, "Cached multi-page stitch complete (no re-OCR).")
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
                txt = srv.chat_image(img_to_data_url(str(p2_img)), LIGHTON_PROMPT, max_tokens=4096, timeout_s=600)
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

    def _is_partial_continuation_scan(raw_txt: str, canon_obj: Optional[Dict[str, Any]], aud_obj: Dict[str, Any], pg_cnt: int) -> bool:
        if pg_cnt > 1 or not canon_obj or aud_obj.get("row_count", 0) <= 0:
            return False
        inv_tot_v = float(canon_obj.get("invoiceTotal") or 0.0)
        tx_tax_v = float(canon_obj.get("taxableTotal") or 0.0) + float(canon_obj.get("cgstTotal") or 0.0) + float(canon_obj.get("sgstTotal") or 0.0) + float(canon_obj.get("igstTotal") or 0.0)
        blk_s = " ".join(str(b).lower() for b in (aud_obj.get("blocking_issues") or []))
        if inv_tot_v <= 0.0 and re.search(r"\b(?:cont\.?\s*page\s*\d+|page\s*1\s*(?:of|/)\s*[2-9]|carry\s*forward|carried\s*forward|to\s+be\s+continued)\b", raw_txt, re.IGNORECASE):
            return True
        if "printed grand total was not found" in blk_s and re.search(r"\b(?:cont\.?\s*page\s*\d+|page\s*1\s*(?:of|/)\s*[2-9]|carry\s*forward|carried\s*forward|to\s+be\s+continued)\b", raw_txt, re.IGNORECASE):
            return True
        if inv_tot_v > tx_tax_v + 1.0:
            if re.search(r"\bpage\s*[2-9]\s*(?:of|/)\s*[2-9]\b", raw_txt, re.IGNORECASE):
                return True
            # Detect continuation Page 2+ whose item table starts at Sl.No >= 2 (e.g. row 9 of INV 11874)
            m_first_row = re.search(r"<tbody>\s*<tr>\s*<td[^>]*>\s*(\d{1,3})\s*\.?\s*</td>", raw_txt, re.IGNORECASE)
            if m_first_row and int(m_first_row.group(1)) >= 2 and inv_tot_v > max(100.0, tx_tax_v * 1.5):
                return True
        return False

    need_escalation = False
    is_partial_continuation = (
        canon_lighton is not None
        and bool(canon_lighton.get("invoiceNumber"))
        and bool((canon_lighton.get("_audit") or {}).get("seller_gstin_valid"))
        and _is_partial_continuation_scan(combined_lighton, canon_lighton, canon_lighton.get("_audit") or {}, len(p2_paths))
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

    if need_escalation and canon_lighton is not None and combined_lighton.strip():
        text_ai_model = qwen_text_model if qwen_text_model.is_file() else qwen_model
        if text_ai_model.is_file():
            emit_progress(args.progress, 62, "Stage 2.5 Text AI analyzing HTML structure & layout memory...")
            try:
                from hybrid_merger import analyze_html_with_text_ai

                txt_res = analyze_html_with_text_ai(
                    llama_server=llama_server,
                    text_model=text_ai_model,
                    raw_html=combined_lighton,
                    base_canon=canon_lighton,
                    audit=canon_lighton.get("_audit") or {},
                    work_dir=work_dir,
                    qr_info=qr_info,
                    client_gstin=args.client_gstin,
                    direction=args.direction,
                    memory_db=memory_db,
                    threads=args.threads,
                )
                if txt_res.get("fullyBalanced") or txt_res.get("improved"):
                    canon_lighton = txt_res["canonical"]
                    canon_lighton["_audit"] = txt_res["audit"]
                    final_canon = canon_lighton
                    engine_used = txt_res["engineUsed"]
                    memory_meta = txt_res["supplierMemory"]
                    if txt_res.get("fullyBalanced"):
                        need_escalation = False
            except Exception as txt_ex:
                emit_progress(args.progress, 64, f"Text AI note ({type(txt_ex).__name__}); continuing...")

    if need_escalation and qwen_model.is_file() and qwen_mmproj.is_file():
        emit_progress(args.progress, 65, "Escalating math/GSTIN verification to Qwen3-VL-4B...")
        try:
            esc = escalate_with_qwen(
                llama_server=llama_server,
                qwen_model=qwen_model,
                qwen_mmproj=qwen_mmproj,
                p2_paths=p2_paths,
                work_dir=work_dir,
                qr_info=qr_info,
                canon_lighton=canon_lighton,
                combined_lighton=combined_lighton,
                client_gstin=args.client_gstin,
                direction=args.direction,
                memory_db=memory_db,
                threads=args.threads,
                progress_cb=(lambda pct, msg: emit_progress(args.progress, pct, msg)),
            )
            final_canon = esc["canonical"]
            engine_used = esc["engineUsed"]
            final_raw = esc["rawOcrText"]
            memory_meta = esc["supplierMemory"]
        except Exception as esc_ex:
            if canon_lighton is None:
                raise
            emit_progress(args.progress, 94, f"Qwen3-VL-4B fallback skipped ({type(esc_ex).__name__}); keeping LightOnOCR-2-1B output.")
            final_raw = combined_lighton + f"\n\n[Escalation note: {esc_ex}]"

    emit_progress(args.progress, 95, "Finalizing GST math audit & canonical JSON...")
    elapsed = round(time.perf_counter() - t_start, 2)
    audit = final_canon.pop("_audit", None) or audit_invoice_math(final_canon, raw_text=final_raw, qr_einvoice=qr_einv)

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
        "agentPipelineTrace": {},
    }

    if not is_partial_continuation and (mode in ("hybrid", "qwen") or bool(audit.get("needs_ai_crosscheck"))):
        two_stg = (audit.get("two_stage_verification") or {}) if isinstance(audit, dict) else {}
        if not two_stg.get("stage2AiCrossChecked"):
            x_model = qwen_text_model if qwen_text_model.is_file() else qwen_model
            if x_model.is_file() and str(final_raw or "").strip():
                try:
                    from hybrid_merger import apply_two_stage_cross_verify_to_worker_payload

                    emit_progress(args.progress, 97, "Stage 2 AI Cross-Check verifying Seller/Buyer/Invoice header...")
                    apply_two_stage_cross_verify_to_worker_payload(
                        payload,
                        llama_server=llama_server,
                        text_model=x_model,
                        work_dir=work_dir,
                        client_gstin=args.client_gstin,
                        direction=args.direction,
                        memory_db=memory_db,
                        threads=args.threads,
                    )
                except Exception:
                    pass
    payload["elapsedSec"] = round(time.perf_counter() - t_start, 2)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="InvoiceVisionChild v2 OCR worker")
    parser.add_argument("--input", action="append", help="Source image or PDF (repeatable)")
    parser.add_argument("--output", help="Output worker JSON path")
    parser.add_argument("--batch-json", help="Optional JSON file listing batch invoice jobs to pipeline continuously")
    parser.add_argument("--work-dir", help="Scratch directory for intermediate rendered/preprocessed pages")
    parser.add_argument("--cache-dir", help="Optional shared directory for SHA-256 OCR cache and warm daemon socket")
    parser.add_argument("--mode", default="auto", choices=["auto", "fast", "hybrid", "qwen"])
    parser.add_argument("--client-gstin", default="")
    parser.add_argument("--direction", default="Auto")
    parser.add_argument("--llama-server")
    parser.add_argument("--lighton-model")
    parser.add_argument("--lighton-mmproj")
    parser.add_argument("--qwen-text-model")
    parser.add_argument("--qwen-model")
    parser.add_argument("--qwen-mmproj")
    parser.add_argument("--paddlex-cache")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--memory-db", default="", help="Optional path to SQLite supplier_memory.db")
    parser.add_argument("--cached-ocr-json", help="Optional JSON array of per-page cached LightOnOCR strings for instant multi-page stitching")
    parser.add_argument("--no-daemon", action="store_true", help="Run in-process and exit immediately after batch/job completes")
    parser.add_argument("--daemon", action="store_true", help="Serve warm ManagerAgent HTTP endpoint until idle timeout")
    parser.add_argument("--idle-timeout", type=float, default=45.0, help="Daemon idle auto-exit timeout in seconds")
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()

    defaults = resolve_default_paths()
    cache_dir = Path(args.cache_dir) if args.cache_dir else (Path(tempfile.gettempdir()) / "aah_ivc_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    llama_srv = Path(args.llama_server or defaults["llama_server"])
    lo_model = Path(args.lighton_model or defaults["lighton_model"])
    lo_mmproj = Path(args.lighton_mmproj or defaults["lighton_mmproj"])
    pdx_cache = Path(args.paddlex_cache or defaults["paddlex_cache"])

    from batch_manager import BatchJob, ManagerAgent, run_batch_jobs, serve_warm_daemon

    if args.daemon:
        mgr = ManagerAgent(
            llama_server=llama_srv,
            lighton_model=lo_model,
            lighton_mmproj=lo_mmproj,
            paddlex_cache=pdx_cache,
            cache_dir=cache_dir,
            threads=args.threads,
            daemon_log_dir=cache_dir / "logs",
        )
        return serve_warm_daemon(mgr, cache_dir / "warm_daemon.json", idle_timeout_s=args.idle_timeout)

    if args.batch_json:
        raw_jobs = json.loads(Path(args.batch_json).read_text(encoding="utf-8"))
        jobs: List[BatchJob] = []
        for idx, item in enumerate(raw_jobs, 1):
            jobs.append(
                BatchJob(
                    invoice_id=str(item.get("invoiceId") or f"INV-{idx}"),
                    input_paths=[Path(p) for p in item["inputs"]],
                    output_path=Path(item["output"]),
                    work_dir=Path(item.get("workDir") or (cache_dir / f"work_{idx}")),
                    mode=str(item.get("mode") or args.mode or "auto"),
                    client_gstin=str(item.get("clientGstin") or args.client_gstin or ""),
                    direction=str(item.get("direction") or args.direction or "Auto"),
                    memory_db=Path(item["memoryDb"]) if item.get("memoryDb") else (Path(args.memory_db) if args.memory_db else None),
                    cached_ocr_json=Path(item["cachedOcrJson"]) if item.get("cachedOcrJson") else None,
                )
            )
        summary = run_batch_jobs(
            jobs,
            llama_server=llama_srv,
            lighton_model=lo_model,
            lighton_mmproj=lo_mmproj,
            paddlex_cache=pdx_cache,
            cache_dir=cache_dir,
            threads=args.threads,
            progress_cb=(
                (lambda iid, st, snap: emit_progress(True, 50, f"[{iid}] {st} active={snap.get('activeAgents')}"))
                if args.progress
                else None
            ),
        )
        if args.output:
            out_p = Path(args.output).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            tmp_p = out_p.with_suffix(".json.tmp")
            tmp_p.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_p, out_p)
        emit_progress(args.progress, 100, f"Batch complete ({len(jobs)} bills) in {summary['totalElapsedSec']}s (llamaBoots={summary['llamaBootCount']})")
        return 0 if all(j.error is None for j in jobs) else 2

    if not args.input or not args.output:
        parser.error("--input and --output are required unless --batch-json or --daemon is specified")

    mode = (args.mode or "auto").strip().lower()
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.cache_dir is None:
        local_app = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
        cache_dir = Path(local_app) / "InvoiceVisionChild" / "Cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _try_stage25_text_ai(payload_dict: Dict[str, Any]) -> bool:
        if mode not in ("auto", "hybrid"):
            return False
        audit_pl = payload_dict.get("audit") or {}
        if audit_pl.get("fully_balanced"):
            return False
        raw_pl = str(payload_dict.get("rawOcrText") or "").strip()
        if not raw_pl:
            return False
        q_txt = Path(getattr(args, "qwen_text_model", "") or defaults["qwen_text_model"])
        text_model = q_txt if q_txt.is_file() else Path(args.qwen_model or defaults["qwen_model"])
        if not text_model.is_file():
            return False
        try:
            from hybrid_merger import analyze_html_with_text_ai

            emit_progress(args.progress, 68, "Stage 2.5 Text AI analyzing HTML structure & layout memory...")
            t_tx0 = time.perf_counter()
            res = analyze_html_with_text_ai(
                llama_server=llama_srv,
                text_model=text_model,
                raw_html=raw_pl,
                base_canon=payload_dict.get("canonical"),
                audit=audit_pl,
                work_dir=Path(args.work_dir).resolve() if args.work_dir else out_path.parent,
                qr_info=payload_dict.get("qrInfo") or {},
                client_gstin=args.client_gstin,
                direction=args.direction,
                memory_db=args.memory_db,
                threads=args.threads,
            )
            if res.get("fullyBalanced") or res.get("improved"):
                payload_dict["canonical"] = res["canonical"]
                payload_dict["audit"] = res["audit"]
                payload_dict["engineUsed"] = res["engineUsed"]
                payload_dict["supplierMemory"] = res["supplierMemory"]
                payload_dict["elapsedSec"] = round(float(payload_dict.get("elapsedSec") or 0.0) + (time.perf_counter() - t_tx0), 2)
                if isinstance(payload_dict.get("agentPipelineTrace"), dict):
                    payload_dict["agentPipelineTrace"]["textAiAnalyzed"] = True
                    payload_dict["agentPipelineTrace"]["selfLearnedRuleSaved"] = bool((res.get("ruleSaved") or {}).get("saved"))
                tmp_path = out_path.with_suffix(".json.tmp")
                tmp_path.write_text(json.dumps(payload_dict, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp_path, out_path)
            return bool(res.get("fullyBalanced"))
        except Exception:
            return False

    def _escalate_payload_locally(payload_dict: Dict[str, Any]) -> Dict[str, Any]:
        if _try_stage25_text_ai(payload_dict):
            return payload_dict
        qwen_m = Path(args.qwen_model or defaults["qwen_model"])
        qwen_mm = Path(args.qwen_mmproj or defaults["qwen_mmproj"])
        t_esc0 = time.perf_counter()
        apply_qwen_escalation_to_worker_payload(
            payload_dict,
            llama_server=llama_srv,
            qwen_model=qwen_m,
            qwen_mmproj=qwen_mm,
            work_dir=Path(args.work_dir).resolve() if args.work_dir else out_path.parent,
            client_gstin=args.client_gstin,
            direction=args.direction,
            memory_db=args.memory_db,
            threads=args.threads,
            progress_cb=(lambda pct, msg: emit_progress(args.progress, pct, msg)),
        )
        payload_dict["elapsedSec"] = round(float(payload_dict.get("elapsedSec") or 0.0) + (time.perf_counter() - t_esc0), 2)
        tmp_path = out_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, out_path)
        return payload_dict

    def _is_partial_continuation_payload(payload_dict: Dict[str, Any]) -> bool:
        audit_pl = payload_dict.get("audit") or {}
        raw_pl = payload_dict.get("rawOcrText") or ""
        canon_pl = payload_dict.get("canonical") or {}
        pages_cnt = len(payload_dict.get("renderedPageImages") or [])
        inv_tot_pl = float(canon_pl.get("invoiceTotal") or 0.0)
        tx_tax_pl = (
            float(canon_pl.get("taxableTotal") or 0.0)
            + float(canon_pl.get("cgstTotal") or 0.0)
            + float(canon_pl.get("sgstTotal") or 0.0)
            + float(canon_pl.get("igstTotal") or 0.0)
        )
        blk_pl = " ".join(str(b).lower() for b in (audit_pl.get("blocking_issues") or []))
        m_first_row = re.search(r"<tbody>\s*<tr>\s*<td[^>]*>\s*(\d{1,3})\s*\.?\s*</td>", raw_pl, re.IGNORECASE)
        is_cont_by_rowno = bool(m_first_row and int(m_first_row.group(1)) >= 2 and inv_tot_pl > max(100.0, tx_tax_pl * 1.5))
        return (
            pages_cnt <= 1
            and audit_pl.get("row_count", 0) > 0
            and (
                (inv_tot_pl <= 0.0 and bool(re.search(r"\b(?:cont\.?\s*page\s*\d+|page\s*1\s*(?:of|/)\s*[2-9]|carry\s*forward|to\s+be\s+continued)\b", raw_pl, re.IGNORECASE)))
                or ("printed grand total was not found" in blk_pl and bool(re.search(r"\b(?:cont\.?\s*page\s*\d+|page\s*1\s*(?:of|/)\s*[2-9]|carry\s*forward|to\s+be\s+continued)\b", raw_pl, re.IGNORECASE)))
                or (inv_tot_pl > tx_tax_pl + 1.0 and (bool(re.search(r"\bpage\s*[2-9]\s*(?:of|/)\s*[2-9]\b", raw_pl, re.IGNORECASE)) or is_cont_by_rowno))
            )
        )

    def _try_two_stage_ai_crosscheck(payload_dict: Dict[str, Any], daemon_port: int = 0) -> bool:
        if _is_partial_continuation_payload(payload_dict):
            return False
        audit_pl = payload_dict.get("audit") or {}
        if mode not in ("hybrid", "qwen") and not audit_pl.get("needs_ai_crosscheck"):
            return False
        two_stg = audit_pl.get("two_stage_verification") or {}
        if two_stg.get("stage2AiCrossChecked"):
            return True
        raw_pl = str(payload_dict.get("rawOcrText") or "").strip()
        if not raw_pl:
            return False
        q_txt = Path(getattr(args, "qwen_text_model", "") or defaults["qwen_text_model"])
        text_model = q_txt if q_txt.is_file() else Path(args.qwen_model or defaults["qwen_model"])
        if not text_model.is_file():
            return False
        work_p = Path(args.work_dir).resolve() if args.work_dir else out_path.parent
        emit_progress(args.progress, 88, "Stage 2 AI Cross-Check verifying Seller/Buyer/Invoice header...")
        if daemon_port > 0:
            try:
                import urllib.request

                xv_req = json.dumps(
                    {
                        "workerOutput": str(out_path),
                        "textModel": str(text_model),
                        "workDir": str(work_p),
                        "clientGstin": args.client_gstin,
                        "direction": args.direction,
                        "memoryDb": args.memory_db,
                    }
                ).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{daemon_port}/cross-verify",
                    data=xv_req,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=180) as resp:
                    if resp.status == 200 and out_path.is_file():
                        updated = json.loads(out_path.read_text(encoding="utf-8"))
                        payload_dict.update(updated)
                        return True
            except Exception:
                pass
        try:
            from hybrid_merger import apply_two_stage_cross_verify_to_worker_payload

            t_xv0 = time.perf_counter()
            apply_two_stage_cross_verify_to_worker_payload(
                payload_dict,
                llama_server=llama_srv,
                text_model=text_model,
                work_dir=work_p,
                client_gstin=args.client_gstin,
                direction=args.direction,
                memory_db=args.memory_db,
                threads=args.threads,
            )
            payload_dict["elapsedSec"] = round(float(payload_dict.get("elapsedSec") or 0.0) + (time.perf_counter() - t_xv0), 2)
            tmp_path = out_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload_dict, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, out_path)
            return True
        except Exception:
            return False

    def _needs_qwen_escalation(payload_dict: Dict[str, Any]) -> bool:
        if mode != "hybrid":
            return False
        audit_pl = payload_dict.get("audit") or {}
        if audit_pl.get("fully_balanced"):
            return False
        if _is_partial_continuation_payload(payload_dict):
            return False
        qwen_txt_m = Path(getattr(args, "qwen_text_model", "") or defaults["qwen_text_model"])
        qwen_m = Path(args.qwen_model or defaults["qwen_model"])
        qwen_mm = Path(args.qwen_mmproj or defaults["qwen_mmproj"])
        return qwen_txt_m.is_file() or qwen_m.is_file() or (qwen_m.is_file() and qwen_mm.is_file())

    # Reuse warm local daemon (or spawn one safely under lock so parallel bursts share 1 LightOnOCR-2-1B instance)
    daemon_info_file = cache_dir / "warm_daemon.json"
    use_pipeline = mode in ("auto", "fast", "hybrid") and not args.cached_ocr_json

    if use_pipeline and not args.no_daemon and os.environ.get("AAH_IVC_NO_DAEMON") != "1":
        import subprocess
        import threading
        import urllib.request

        job_id_unique = f"{out_path.parent.name}_{out_path.stem}"

        def _try_submit_daemon(port_num: int) -> bool:
            req_body = json.dumps(
                {
                    "invoiceId": job_id_unique,
                    "inputs": [str(Path(p).resolve()) for p in args.input],
                    "output": str(out_path),
                    "workDir": str(Path(args.work_dir).resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="aah_ivc2_"))),
                    "mode": mode,
                    "clientGstin": args.client_gstin,
                    "direction": args.direction,
                    "memoryDb": args.memory_db,
                    "cachedOcrJson": args.cached_ocr_json,
                }
            ).encode("utf-8")

            done_flag = threading.Event()

            def _heartbeat_poll() -> None:
                last_stage = ""
                stage_pct = {"QUEUED": 10, "PREP_QR": 20, "VISUAL_OCR": 45, "CATEGORY_DISPATCH": 70, "PEER_SUBAGENTS": 78, "AUDIT": 85, "SELF_CORRECT": 90, "FINAL_HANDOFF": 96}
                while not done_flag.wait(12.0):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port_num}/progress?invoiceId={job_id_unique}", timeout=2) as pr:
                            if pr.status == 200:
                                st = json.loads(pr.read().decode("utf-8"))
                                sg = str(st.get("stage") or "PROCESSING")
                                if sg != last_stage or True:
                                    last_stage = sg
                                    emit_progress(args.progress, stage_pct.get(sg, 50), f"Warm daemon stage: {sg}")
                    except Exception:
                        emit_progress(args.progress, 50, "Warm daemon processing queued invoice...")

            hb_thread = threading.Thread(target=_heartbeat_poll, daemon=True) if args.progress else None
            if hb_thread is not None:
                hb_thread.start()
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{port_num}/extract", data=req_body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=1800) as resp:
                    if resp.status == 200:
                        dres = json.loads(resp.read().decode("utf-8"))
                        emit_progress(args.progress, 100, f"Done via warm daemon in {dres.get('elapsedSec', 0)}s ({dres.get('engineUsed', '')})")
                        return True
            finally:
                done_flag.set()
            return False

        def _read_live_port() -> int:
            if not daemon_info_file.is_file():
                return 0
            try:
                info = json.loads(daemon_info_file.read_text(encoding="utf-8"))
                p = int(info.get("port") or 0)
                if p > 0:
                    with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=2) as h:
                        if h.status == 200:
                            return p
            except Exception:
                return 0
            return 0

        port = _read_live_port()
        if port <= 0:
            lock_path = cache_dir / "daemon_spawn.lock"
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    port = _read_live_port()
                    if port <= 0:
                        daemon_py = sys.executable
                        if os.name == "nt":
                            pw = Path(sys.executable).with_name("pythonw.exe")
                            if pw.is_file():
                                daemon_py = str(pw)
                        dcmd = [
                            daemon_py, str(Path(__file__).resolve()),
                            "--daemon", "--idle-timeout", str(args.idle_timeout),
                            "--cache-dir", str(cache_dir),
                            "--threads", str(args.threads),
                            "--llama-server", str(llama_srv),
                            "--lighton-model", str(lo_model),
                            "--lighton-mmproj", str(lo_mmproj),
                            "--paddlex-cache", str(pdx_cache),
                        ]
                        # pythonw.exe (SUBSYSTEM:WINDOWS) + CREATE_NO_WINDOW + SW_HIDE guarantees
                        # Windows never allocates or flashes a cmd/WindowsTerminal console window.
                        cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        si = None
                        if os.name == "nt":
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            si.wShowWindow = 0  # SW_HIDE
                        subprocess.Popen(
                            dcmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL,
                            creationflags=cflags,
                            startupinfo=si,
                            close_fds=True,
                        )
                        for _ in range(30):
                            time.sleep(0.25)
                            port = _read_live_port()
                            if port > 0:
                                break
                finally:
                    if os.name == "nt":
                        import msvcrt
                        try:
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
                    os.close(fd)
            except Exception:
                port = _read_live_port()

        if port > 0:
            try:
                if _try_submit_daemon(port):
                    if out_path.is_file():
                        d_out = json.loads(out_path.read_text(encoding="utf-8"))
                        if _needs_qwen_escalation(d_out):
                            if _try_stage25_text_ai(d_out):
                                _try_two_stage_ai_crosscheck(d_out, daemon_port=port)
                                emit_progress(args.progress, 100, f"Done in {d_out.get('elapsedSec', 0)}s ({d_out.get('engineUsed', 'TextAI')})")
                                return 0
                            qwen_m = Path(args.qwen_model or defaults["qwen_model"])
                            qwen_mm = Path(args.qwen_mmproj or defaults["qwen_mmproj"])
                            emit_progress(args.progress, 75, "Hybrid Auditor fallback -> escalating unresolved bill to Qwen3-VL-4B (reusing LightOnOCR)...")
                            t_q0 = time.perf_counter()
                            esc_req = json.dumps(
                                {
                                    "workerOutput": str(out_path),
                                    "qwenModel": str(qwen_m),
                                    "qwenMmproj": str(qwen_mm),
                                    "workDir": str(Path(args.work_dir).resolve() if args.work_dir else out_path.parent),
                                    "clientGstin": args.client_gstin,
                                    "direction": args.direction,
                                    "memoryDb": args.memory_db,
                                    "waitOffsetSec": 0.0,
                                }
                            ).encode("utf-8")
                            try:
                                qreq = urllib.request.Request(f"http://127.0.0.1:{port}/escalate-qwen", data=esc_req, headers={"Content-Type": "application/json"}, method="POST")
                                with urllib.request.urlopen(qreq, timeout=900) as qresp:
                                    if qresp.status == 200:
                                        qres = json.loads(qresp.read().decode("utf-8"))
                                        if out_path.is_file():
                                            d_out = json.loads(out_path.read_text(encoding="utf-8"))
                                            _try_two_stage_ai_crosscheck(d_out, daemon_port=port)
                                        emit_progress(args.progress, 100, f"Done in {round(time.perf_counter()-t_q0,1)}s ({d_out.get('engineUsed', qres.get('engineUsed', 'Hybrid'))})")
                                        return 0
                            except Exception:
                                _escalate_payload_locally(d_out)
                                _try_two_stage_ai_crosscheck(d_out, daemon_port=port)
                                emit_progress(args.progress, 100, f"Done in {d_out.get('elapsedSec', 0)}s ({d_out.get('engineUsed', 'Hybrid')})")
                                return 0
                        if _try_two_stage_ai_crosscheck(d_out, daemon_port=port):
                            emit_progress(args.progress, 100, f"Done in {d_out.get('elapsedSec', 0)}s ({d_out.get('engineUsed', '2Stage-Verified')})")
                            return 0
                    return 0
            except Exception:
                pass

    if mode in ("auto", "fast", "hybrid"):
        job = BatchJob(
            invoice_id=f"{out_path.parent.name}_{out_path.stem}",
            input_paths=[Path(p).resolve() for p in args.input],
            output_path=out_path,
            work_dir=Path(args.work_dir).resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix="aah_ivc2_")),
            mode=mode,
            client_gstin=args.client_gstin,
            direction=args.direction,
            memory_db=Path(args.memory_db) if args.memory_db else None,
            cached_ocr_json=Path(args.cached_ocr_json) if args.cached_ocr_json else None,
        )
        run_batch_jobs(
            [job],
            llama_server=llama_srv,
            lighton_model=lo_model,
            lighton_mmproj=lo_mmproj,
            paddlex_cache=pdx_cache,
            cache_dir=cache_dir,
            threads=args.threads,
            progress_cb=((lambda iid, st, snap: emit_progress(True, 60, f"[{iid}] {st}")) if args.progress else None),
        )
        if job.error:
            raise RuntimeError(job.error)
        res_pl = job.result_payload or {}
        if _needs_qwen_escalation(res_pl):
            emit_progress(args.progress, 75, "Hybrid Auditor fallback -> escalating unresolved bill to Qwen3-VL-4B (reusing LightOnOCR)...")
            _escalate_payload_locally(res_pl)
        _try_two_stage_ai_crosscheck(res_pl, daemon_port=0)
        emit_progress(args.progress, 100, f"Done in {res_pl.get('elapsedSec', 0)}s ({res_pl.get('engineUsed', '')})")
        return 0

    tmp_path = out_path.with_suffix(".json.tmp")
    result = run_extraction(args)
    tmp_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, out_path)
    emit_progress(args.progress, 100, f"Done in {result['elapsedSec']}s ({result['engineUsed']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
