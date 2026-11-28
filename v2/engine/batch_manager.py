#!/usr/bin/env python3
"""Continuous pipelined batch multi-agent orchestrator for InvoiceVisionChild v2.

Stages run continuously across the batch without stalling upstream stages:
  1. ManagerAgent            -> Receives job(s), hands to Stage 1, tracks stages/agents, receives from FinalHandoffAgent, cleanly exits at 0 remaining.
  2. Continuous Prep+QR      -> Renders PDFs/images, runs P2 orientation/crop/dewarp/LAB, multi-pass QR decode; checks SHA-256 OCR cache.
  3. Continuous Visual OCR   -> Single warm LightOnOCR-2-1B (-np 1 -c 16384, unlimited EOS + loop guard) runs ONCE per uncached photo; never blocks on downstream agents.
  4. Dynamic Category Pool   -> `discover_bill_categories()` spawns needed category sub-agents on a reusable ThreadPoolExecutor(6); sub-agents communicate via `PeerBus`.
  5. Continuous AuditorAgent -> Audits 7 invariants; sends direct `CorrectionDirective` over `PeerBus` for Pass 2 targeted repair; continuously moves to next invoice.
  6. Continuous FinalHandoff -> Saves per-agent + supplier memory on verified bills, stamps `AAH-INVOICEVISION-WORKER-V1`, atomically writes output JSON, notifies ManagerAgent.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_bus import InvoiceStageTracker, PeerBus
from category_agents import (
    REGISTRY,
    InvoiceWorkContext,
    discover_bill_categories,
    initialize_base_parse,
    persist_learned_agent_memories,
)
from gst_math import audit_invoice_math, run_parallel_category_audits
from gst_parser import clean_num, normalize_canonical_dict, parse_document_text_to_canonical
from hybrid_merger import LlamaServerSession, apply_qwen_escalation_to_worker_payload, img_to_data_url
from preprocess import configure_isolated_paddlex, crop_footer_strip, preprocess_pages_p2, render_input_to_images
from qr_decode import decode_qr_from_image
from supplier_memory import apply_supplier_memory

LIGHTON_PROMPT = "Extract all text and tables from this invoice accurately."


@dataclass
class BatchJob:
    invoice_id: str
    input_paths: List[Path]
    output_path: Path
    work_dir: Path
    mode: str = "auto"
    client_gstin: str = ""
    direction: str = "Auto"
    memory_db: Optional[Path] = None
    cached_ocr_json: Optional[Path] = None
    source_sha256: List[Dict[str, Any]] = field(default_factory=list)
    done_event: threading.Event = field(default_factory=threading.Event)
    result_payload: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ManagerAgent:
    """Keeps live stage/agent status across a batch, feeds Stage 1, receives from FinalHandoffAgent, and shuts down cleanly."""

    def __init__(
        self,
        llama_server: Path,
        lighton_model: Path,
        lighton_mmproj: Path,
        paddlex_cache: Path,
        cache_dir: Path,
        threads: int = 10,
        subagent_workers: int = 6,
        progress_cb: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
        daemon_log_dir: Optional[Path] = None,
    ) -> None:
        self.llama_server = Path(llama_server)
        self.lighton_model = Path(lighton_model)
        self.lighton_mmproj = Path(lighton_mmproj)
        self.paddlex_cache = Path(paddlex_cache)
        self.cache_dir = Path(cache_dir)
        self.daemon_log_dir = Path(daemon_log_dir) if daemon_log_dir else None
        self.ocr_cache_dir = self.cache_dir / "ocr_cache"
        self.ocr_cache_dir.mkdir(parents=True, exist_ok=True)
        self.threads = max(2, int(threads))
        self.llama_parallel = 2 if self.threads >= 8 else 1

        self.bus = PeerBus()
        self.tracker = InvoiceStageTracker(progress_cb=progress_cb)
        self._prep_job_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="PrepJob")
        self._prep_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="PrepQRChild")
        self._ocr_job_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="OCRJob")
        self._ocr_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="VisualOCRChild")
        self.pool = ThreadPoolExecutor(max_workers=max(2, subagent_workers), thread_name_prefix="SubAgent")
        self._audit_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="AuditChild")
        self._ocr_slot_sem = threading.Semaphore(self.llama_parallel)
        self._infer_lock = threading.Lock()
        self._infer_cond = threading.Condition(self._infer_lock)
        self._active_ocr_slots = 0
        self._qwen_active = False

        self._q_prep: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self._q_ocr: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self._q_dispatch: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self._q_audit: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()
        self._q_handoff: queue.Queue[Optional[Dict[str, Any]]] = queue.Queue()

        self._server_lock = threading.Lock()
        self._ocr_session: Optional[LlamaServerSession] = None
        self.llama_boot_count = 0

        self._active_lock = threading.Lock()
        self._pending_count = 0
        self._all_done_cond = threading.Condition(self._active_lock)
        self._stopped = False

        self._threads = [
            threading.Thread(target=self._run_prep_stage, name="PrepQRStage", daemon=True),
            threading.Thread(target=self._run_visual_ocr_stage, name="VisualOCRStage", daemon=True),
            threading.Thread(target=self._run_dispatch_stage, name="CategoryDispatchStage", daemon=True),
            threading.Thread(target=self._run_audit_stage, name="AuditorAgent", daemon=True),
            threading.Thread(target=self._run_handoff_stage, name="FinalHandoffAgent", daemon=True),
        ]
        for t in self._threads:
            t.start()

    def submit(self, job: BatchJob) -> BatchJob:
        with self._active_lock:
            if self._stopped:
                raise RuntimeError("ManagerAgent is stopped")
            self._pending_count += 1
        self.tracker.register(job.invoice_id, job.input_paths[0].name if job.input_paths else job.invoice_id, [str(p) for p in job.input_paths])
        self._q_prep.put({"job": job, "started": time.perf_counter()})
        return job

    def wait_all(self) -> None:
        with self._active_lock:
            while self._pending_count > 0:
                self._all_done_cond.wait(timeout=0.5)

    def shutdown(self) -> None:
        with self._active_lock:
            self._stopped = True
        for q in (self._q_prep, self._q_ocr, self._q_dispatch, self._q_audit, self._q_handoff):
            q.put(None)
        for t in self._threads:
            t.join(timeout=15)
        for p in (self._prep_job_pool, self._prep_pool, self._ocr_job_pool, self._ocr_pool, self.pool, self._audit_pool):
            p.shutdown(wait=True)
        self._close_ocr_session()

    def _ensure_ocr_session(self, log_dir: Path) -> LlamaServerSession:
        with self._server_lock:
            if self._ocr_session is None:
                eff_log_dir = self.daemon_log_dir or log_dir
                eff_log_dir.mkdir(parents=True, exist_ok=True)
                sess = LlamaServerSession(
                    str(self.llama_server),
                    str(self.lighton_model),
                    str(self.lighton_mmproj),
                    eff_log_dir,
                    threads=self.threads,
                    ctx=16384 * self.llama_parallel,
                    repeat_penalty=1.12,
                    parallel=self.llama_parallel,
                )
                sess.__enter__()
                self._ocr_session = sess
                self.llama_boot_count += 1
            return self._ocr_session

    def _close_ocr_session(self) -> None:
        with self._server_lock:
            if self._ocr_session is not None:
                try:
                    self._ocr_session.__exit__(None, None, None)
                finally:
                    self._ocr_session = None

    def _ocr_cache_path(self, img_sha: str) -> Path:
        return self.ocr_cache_dir / f"{img_sha}.json"

    def _read_ocr_cache(self, img_sha: str) -> Optional[Dict[str, Any]]:
        cp = self._ocr_cache_path(img_sha)
        if cp.is_file():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                if data.get("model") == self.lighton_model.name and isinstance(data.get("text"), str) and not data.get("truncated"):
                    return data
            except Exception:
                pass
        return None

    def _write_ocr_cache(self, img_sha: str, text: str, finish_reason: str, truncated: bool) -> None:
        cp = self._ocr_cache_path(img_sha)
        tmp = cp.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "sha256": img_sha,
                    "model": self.lighton_model.name,
                    "text": text,
                    "finish_reason": finish_reason,
                    "truncated": truncated,
                    "ts": round(time.time(), 3),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, cp)

    def _mark_job_failed(self, pkt: Dict[str, Any], err: str) -> None:
        job: BatchJob = pkt["job"]
        job.error = err
        self.tracker.transition(job.invoice_id, "FAILED", {"error": err})
        job.done_event.set()
        with self._active_lock:
            self._pending_count = max(0, self._pending_count - 1)
            self._all_done_cond.notify_all()

    @contextmanager
    def _lighton_inference_slot(self):
        with self._ocr_slot_sem:
            with self._infer_cond:
                while self._qwen_active:
                    self._infer_cond.wait(timeout=0.5)
                self._active_ocr_slots += 1
            try:
                yield
            finally:
                with self._infer_cond:
                    self._active_ocr_slots = max(0, self._active_ocr_slots - 1)
                    self._infer_cond.notify_all()

    @contextmanager
    def exclusive_qwen_gate(self):
        with self._infer_cond:
            while self._qwen_active or self._active_ocr_slots > 0:
                self._infer_cond.wait(timeout=0.5)
            self._qwen_active = True
        try:
            yield
        finally:
            with self._infer_cond:
                self._qwen_active = False
                self._infer_cond.notify_all()

    # ---------------- Stage 1: Prep + QR (Parallel Child Agents) ----------------
    def _prep_one_job(self, pkt: Dict[str, Any]) -> None:
        job: BatchJob = pkt["job"]
        try:
            self.tracker.transition(job.invoice_id, "PREP_QR")
            work_dir = Path(job.work_dir)
            pages_dir = work_dir / "pages"
            work_dir.mkdir(parents=True, exist_ok=True)

            t_render = time.perf_counter()
            raw_pages = render_input_to_images(job.input_paths, pages_dir, pdf_dpi=200)
            if not raw_pages:
                raise RuntimeError("No readable pages rendered from input")
            self.tracker.record_child_agent(job.invoice_id, "PREP_QR", "render_pages_child", (time.perf_counter() - t_render) * 1000.0, detail={"pageCount": len(raw_pages)})

            def _cache_probe_child() -> tuple:
                t0 = time.perf_counter()
                src_meta = [
                    {"path": str(p), "sha256": sha256_file(p), "fileBytes": p.stat().st_size}
                    for p in job.input_paths
                ]
                page_shas = [sha256_file(p) for p in raw_pages]
                all_cached = all(self._read_ocr_cache(ps) is not None for ps in page_shas)
                self.tracker.record_child_agent(job.invoice_id, "PREP_QR", "cache_probe_child", (time.perf_counter() - t0) * 1000.0, detail={"cacheReady": all_cached})
                return src_meta, page_shas, all_cached

            def _qr_child() -> Dict[str, Any]:
                t0 = time.perf_counter()
                res = decode_qr_from_image(str(raw_pages[0]), extra_paths=[str(p) for p in raw_pages[1:]])
                self.tracker.record_child_agent(job.invoice_id, "PREP_QR", "qr_decode_child", (time.perf_counter() - t0) * 1000.0, detail={"einvoiceFound": bool(res.get("einvoice_found"))})
                return res

            fut_probe = self._prep_pool.submit(_cache_probe_child)
            fut_qr = self._prep_pool.submit(_qr_child)

            src_meta, page_shas, all_cached = fut_probe.result()
            has_cached_override = bool(job.cached_ocr_json and Path(job.cached_ocr_json).is_file())
            if all_cached or has_cached_override:
                # Cache hits or explicit cached OCR don't need UVDoc dewarping; keep rendered pages cleanly
                prep_records = [{"raw_page": str(p), "p2_path": str(p), "skipped_cached": True} for p in raw_pages]
                p2_paths = list(raw_pages)
                self.tracker.record_child_agent(job.invoice_id, "PREP_QR", "p2_prep_child", 0.0, status="skipped_cache_hit")
            else:
                def _p2_child() -> List[Dict[str, object]]:
                    t0 = time.perf_counter()
                    recs = preprocess_pages_p2(raw_pages, work_dir, paddlex_cache_dir=self.paddlex_cache, max_side=1536)
                    self.tracker.record_child_agent(job.invoice_id, "PREP_QR", "p2_prep_child", (time.perf_counter() - t0) * 1000.0, detail={"pages": len(recs)})
                    return recs

                fut_p2 = self._prep_pool.submit(_p2_child)
                prep_records = fut_p2.result()
                p2_paths = [Path(str(r["p2_path"])) for r in prep_records]

            qr_info = fut_qr.result()
            job.source_sha256 = src_meta
            pkt.update(
                {
                    "raw_pages": raw_pages,
                    "prep_records": prep_records,
                    "p2_paths": p2_paths,
                    "page_shas": page_shas,
                    "qr_info": qr_info,
                }
            )
            self._q_ocr.put(pkt)
        except Exception as ex:
            self._mark_job_failed(pkt, f"Stage1 Prep+QR error: {ex}")

    def _run_prep_stage(self) -> None:
        configure_isolated_paddlex(self.paddlex_cache)
        while True:
            pkt = self._q_prep.get()
            if pkt is None:
                break
            self._prep_job_pool.submit(self._prep_one_job, pkt)

    # ---------------- Stage 2: Parallel Child Visual OCR (Single Warm Server + Strip Repair) ----------------
    def _ocr_single_page_child(self, idx: int, p2_img: Path, p_sha: str, log_dir: Path, invoice_id: str, cached_text: Optional[str]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if cached_text is not None:
            self.tracker.record_child_agent(invoice_id, "VISUAL_OCR", f"visual_ocr_cache_p{idx}", (time.perf_counter() - t0) * 1000.0)
            return {"idx": idx, "text": cached_text, "finish_reason": "cache_override", "truncated": False, "cached": True}

        cached = self._read_ocr_cache(p_sha)
        if cached is not None:
            self.tracker.record_child_agent(invoice_id, "VISUAL_OCR", f"visual_ocr_cache_p{idx}", (time.perf_counter() - t0) * 1000.0)
            return {"idx": idx, "text": cached["text"], "finish_reason": f"cache:{cached.get('finish_reason', 'stop')}", "truncated": False, "cached": True}

        with self._lighton_inference_slot():
            srv = self._ensure_ocr_session(log_dir)
            res = srv.chat_image_stream(img_to_data_url(str(p2_img)), LIGHTON_PROMPT, max_tokens=None, timeout_s=600)
        txt = str(res.get("text") or "")
        fr = str(res.get("finish_reason") or "")
        tr = bool(res.get("truncated")) or bool(res.get("truncated_by_loop"))
        if not tr:
            self._write_ocr_cache(p_sha, txt, fr, False)
        self.tracker.record_child_agent(
            invoice_id,
            "VISUAL_OCR",
            f"visual_ocr_page_child_{idx}",
            (time.perf_counter() - t0) * 1000.0,
            detail={"finishReason": fr, "truncated": tr, "chars": len(txt)},
        )
        return {"idx": idx, "text": txt, "finish_reason": fr, "truncated": tr, "cached": False}

    def repair_footer_strip(
        self,
        invoice_id: str,
        p2_img_path: Path,
        work_dir: Path,
        top_ratio: float = 0.48,
        max_tokens: int = 1200,
        prompt: Optional[str] = None,
        child_name: str = "visual_ocr_footer_strip_child",
    ) -> str:
        """Spawn a fast targeted Stage-2 child OCR call on a bottom footer strip."""
        t0 = time.perf_counter()
        tag = f"{int(round(top_ratio * 100))}"
        strip_path = work_dir / "preprocessed" / f"{p2_img_path.stem}_footer_strip_{tag}.png"
        cropped = crop_footer_strip(p2_img_path, strip_path, top_ratio=top_ratio)
        eff_prompt = prompt or "Extract the tax breakdown table, CGST, SGST, IGST, round off, grand total, and amount in words from this invoice bottom section."
        with self._lighton_inference_slot():
            srv = self._ensure_ocr_session(work_dir / "logs")
            res = srv.chat_image_stream(
                img_to_data_url(str(cropped)),
                eff_prompt,
                max_tokens=max_tokens,
                timeout_s=180,
            )
        txt = str(res.get("text") or "")
        self.tracker.record_child_agent(
            invoice_id,
            "VISUAL_OCR",
            child_name,
            (time.perf_counter() - t0) * 1000.0,
            detail={"chars": len(txt), "finishReason": res.get("finish_reason", ""), "topRatio": top_ratio},
        )
        return txt

    def _ocr_one_job(self, pkt: Dict[str, Any]) -> None:
        job: BatchJob = pkt["job"]
        try:
            self.tracker.transition(job.invoice_id, "VISUAL_OCR")
            p2_paths: List[Path] = pkt["p2_paths"]
            page_shas: List[str] = pkt["page_shas"]

            cached_override: Optional[List[str]] = None
            if job.cached_ocr_json and Path(job.cached_ocr_json).is_file():
                raw_c = json.loads(Path(job.cached_ocr_json).read_text(encoding="utf-8"))
                if isinstance(raw_c, list) and len(raw_c) == len(p2_paths):
                    cached_override = [str(x) for x in raw_c]

            log_dir = Path(job.work_dir) / "logs"
            if len(p2_paths) <= 1:
                page_results = [
                    self._ocr_single_page_child(
                        1,
                        p2_paths[0],
                        page_shas[0],
                        log_dir,
                        job.invoice_id,
                        cached_override[0] if cached_override is not None else None,
                    )
                ]
            else:
                futs = [
                    self._ocr_pool.submit(
                        self._ocr_single_page_child,
                        idx,
                        p2_img,
                        p_sha,
                        log_dir,
                        job.invoice_id,
                        cached_override[idx - 1] if cached_override is not None else None,
                    )
                    for idx, (p2_img, p_sha) in enumerate(zip(p2_paths, page_shas), 1)
                ]
                page_results = [f.result() for f in futs]

            page_texts = [r["text"] for r in page_results]
            finish_reasons = [r["finish_reason"] for r in page_results]
            ocr_truncated = any(r["truncated"] for r in page_results)
            cache_hits = sum(1 for r in page_results if r["cached"])
            combined_ocr = "\n\n<!-- PAGE BREAK -->\n\n".join(page_texts)
            all_cached = cache_hits == len(p2_paths)
            pkt.update(
                {
                    "page_texts": page_texts,
                    "combined_ocr": combined_ocr,
                    "ocr_truncated": ocr_truncated,
                    "finish_reasons": finish_reasons,
                    "cache_hit": all_cached,
                }
            )
            self.tracker.transition(job.invoice_id, "VISUAL_OCR", {"cacheHit": all_cached})
            self._q_dispatch.put(pkt)
        except Exception as ex:
            self._mark_job_failed(pkt, f"Stage2 VisualOCR error: {ex}")

    def _run_visual_ocr_stage(self) -> None:
        while True:
            pkt = self._q_ocr.get()
            if pkt is None:
                break
            self._ocr_job_pool.submit(self._ocr_one_job, pkt)

    # ---------------- Stage 3: Dynamic Category Dispatcher + Reusable Sub-Agent Pool ----------------
    def _run_category_wave(self, ctx: InvoiceWorkContext, categories: List[str], directives: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        # Ordered dependency waves so upstream peer providers publish before consumers read from PeerBus,
        # while independent sub-agents inside each wave run concurrently in the reusable pool.
        waves = [
            [c for c in ("qr_authority", "multipage_continuity") if c in categories],
            [c for c in ("supplier_identity", "buyer_direction", "invoice_header", "discount_charges") if c in categories],
            [c for c in ("line_items",) if c in categories],
            [c for c in ("hsn_classification",) if c in categories],
            [c for c in ("tax_summary_slab",) if c in categories],
            [c for c in ("totals_words",) if c in categories],
        ]
        # Catch any dynamically registered extra category names in a final concurrent wave
        covered = {c for w in waves for c in w}
        extra = [c for c in categories if c not in covered]
        if extra:
            waves.append(extra)

        for wave in waves:
            if not wave:
                continue
            futures: Dict[str, Future] = {}
            for cat in wave:
                handler = REGISTRY.handler_for(cat)
                if handler is None:
                    continue
                self.tracker.agent_started(ctx.invoice_id, cat)
                d_payload = (directives or {}).get(cat)
                futures[cat] = self.pool.submit(handler, ctx, self.bus, d_payload)
            for cat, fut in futures.items():
                try:
                    ctx.agent_notes[cat] = fut.result()
                except Exception as ex:
                    ctx.agent_notes[cat] = {"error": str(ex)}
                finally:
                    self.tracker.agent_finished(ctx.invoice_id, cat)

    def _run_dispatch_stage(self) -> None:
        while True:
            pkt = self._q_dispatch.get()
            if pkt is None:
                break
            job: BatchJob = pkt["job"]
            try:
                ctx = InvoiceWorkContext(
                    invoice_id=job.invoice_id,
                    raw_ocr_text=pkt["combined_ocr"],
                    page_texts=pkt["page_texts"],
                    qr_info=pkt["qr_info"],
                    client_gstin=job.client_gstin,
                    direction=job.direction,
                    memory_db=job.memory_db,
                )
                initialize_base_parse(ctx)
                categories = discover_bill_categories(ctx)
                self.tracker.transition(job.invoice_id, "CATEGORY_DISPATCH", {"dispatchedCategories": categories})
                self.tracker.transition(job.invoice_id, "PEER_SUBAGENTS")
                self._run_category_wave(ctx, categories)
                ctx.canonical = normalize_canonical_dict(
                    ctx.canonical,
                    ctx.raw_ocr_text,
                    (ctx.qr_info or {}).get("einvoice"),
                    qr_upi_meta=(ctx.qr_info or {}).get("upi_meta"),
                )
                pkt["ctx"] = ctx
                pkt["categories"] = categories
                self._q_audit.put(pkt)
            except Exception as ex:
                self._mark_job_failed(pkt, f"Stage3 SubAgents error: {ex}")

    # ---------------- Stage 4: Continuous Parallel N->N AuditorAgent ----------------
    def _run_audit_stage(self) -> None:
        while True:
            pkt = self._q_audit.get()
            if pkt is None:
                break
            job: BatchJob = pkt["job"]
            ctx: InvoiceWorkContext = pkt["ctx"]
            categories: List[str] = list(pkt.get("categories") or [])
            try:
                self.tracker.transition(job.invoice_id, "AUDIT", {"categoryAgentCount": len(categories)})
                qr_einv = (ctx.qr_info or {}).get("einvoice")
                qr_upi = (ctx.qr_info or {}).get("upi_meta")
                is_trunc = bool(pkt.get("ocr_truncated"))

                audit, audit_children = run_parallel_category_audits(
                    ctx.canonical,
                    categories,
                    pool=self._audit_pool,
                    bus=self.bus,
                    invoice_id=job.invoice_id,
                    pass_no=ctx.pass_no,
                    qr_einvoice=qr_einv,
                    truncated=is_trunc,
                )

                # Fast Stage-2 footer-strip child recovery before considering heavier escalation
                issues_low = " ".join(audit.get("blocking_issues") or []).lower()
                raw_low = (ctx.raw_ocr_text or "").lower()
                if (
                    not audit.get("fully_balanced")
                    and (
                        is_trunc
                        or audit.get("truncated")
                        or "printed grand total" in issues_low
                        or "truncated mid-table" in issues_low
                        or ("tax sum" in issues_low and "incl" in raw_low)
                    )
                    and pkt.get("p2_paths")
                    and not pkt.get("cache_hit")
                ):
                    footer_txt = self.repair_footer_strip(job.invoice_id, Path(pkt["p2_paths"][-1]), Path(job.work_dir))
                    if footer_txt.strip():
                        # Close unclosed partial table if needed and append recovered footer block
                        base_txt = ctx.raw_ocr_text or ""
                        if base_txt.lower().count("<table") > base_txt.lower().count("</table>"):
                            base_txt += "</table>\n\n"
                        ctx.raw_ocr_text = base_txt + "\n\n" + footer_txt.strip()
                        if ctx.page_texts:
                            ctx.page_texts[-1] = (ctx.page_texts[-1] or "") + "\n\n" + footer_txt.strip()
                        pkt["ocr_truncated"] = False
                        is_trunc = False
                        initialize_base_parse(ctx)
                        self._run_category_wave(ctx, categories)
                        ctx.canonical = normalize_canonical_dict(ctx.canonical, ctx.raw_ocr_text, qr_einv, qr_upi_meta=qr_upi)
                        audit, audit_children = run_parallel_category_audits(
                            ctx.canonical,
                            categories,
                            pool=self._audit_pool,
                            bus=self.bus,
                            invoice_id=job.invoice_id,
                            pass_no=ctx.pass_no,
                            qr_einvoice=qr_einv,
                            truncated=False,
                        )
                        issues_low = " ".join(audit.get("blocking_issues") or []).lower()
                        raw_low = (ctx.raw_ocr_text or "").lower()

                # Verify whole-rupee Net Payable box via bottom 28% strip if Amount-in-Words is exact whole rupees
                # while extracted invoiceTotal kept paise and no explicit Round Off line was detected.
                amt_w = float(audit.get("amount_in_words") or 0.0)
                inv_t = float(ctx.canonical.get("invoiceTotal") or 0.0)
                ro_v = float(ctx.canonical.get("roundOff") or 0.0)
                if (
                    amt_w > 0.0
                    and abs(amt_w - round(amt_w)) < 0.001
                    and 0.04 <= abs(inv_t - amt_w) <= 0.99
                    and "round off" not in raw_low
                    and "round-off" not in raw_low
                    and "rounding" not in raw_low
                    and pkt.get("p2_paths")
                ):
                    np_txt = self.repair_footer_strip(
                        job.invoice_id,
                        Path(pkt["p2_paths"][-1]),
                        Path(job.work_dir),
                        top_ratio=0.72,
                        max_tokens=500,
                        prompt="Extract only the Tax Summary bottom Total row (especially Net Payable Amt), Round Off, Grand Total, and Amount in words accurately.",
                        child_name="visual_ocr_net_payable_child",
                    )
                    if np_txt.strip():
                        np_canon = parse_document_text_to_canonical(
                            np_txt,
                            qr_einvoice=qr_einv,
                            known_client_gstin=job.client_gstin,
                            direction_hint=job.direction,
                            qr_upi_meta=qr_upi,
                        )
                        strip_tot = float(np_canon.get("invoiceTotal") or 0.0)
                        target_whole = int(round(amt_w))
                        # Also match printed whole-rupee Net Payable cell (e.g. 23,851.00 or 23851.00) if partial strip header lacked column label
                        if abs(strip_tot - amt_w) > 0.01:
                            for m_num in re.finditer(r"(?<![\d.])([0-9][0-9,]*)\.00\b", np_txt):
                                if int(m_num.group(1).replace(",", "")) == target_whole:
                                    strip_tot = float(target_whole)
                                    break
                        if strip_tot > 0 and abs(strip_tot - amt_w) <= 0.01:
                            tx_v = float(ctx.canonical.get("taxableTotal") or 0.0)
                            cg_v = float(ctx.canonical.get("cgstTotal") or 0.0)
                            sg_v = float(ctx.canonical.get("sgstTotal") or 0.0)
                            ig_v = float(ctx.canonical.get("igstTotal") or 0.0)
                            cs_v = float(ctx.canonical.get("cessTotal") or 0.0)
                            cn_v = float(ctx.canonical.get("creditNoteTotal") or 0.0)
                            ctx.canonical["invoiceTotal"] = round(strip_tot, 2)
                            ctx.canonical["roundOff"] = round(strip_tot - (tx_v + cg_v + sg_v + ig_v + cs_v - cn_v), 2)
                            ctx.raw_ocr_text = (ctx.raw_ocr_text or "") + "\n\n<!-- NET PAYABLE VERIFY -->\n" + np_txt.strip()
                            ctx.canonical = normalize_canonical_dict(ctx.canonical, ctx.raw_ocr_text, qr_einv, qr_upi_meta=qr_upi)
                            audit, audit_children = run_parallel_category_audits(
                                ctx.canonical,
                                categories,
                                pool=self._audit_pool,
                                bus=self.bus,
                                invoice_id=job.invoice_id,
                                pass_no=ctx.pass_no,
                                qr_einvoice=qr_einv,
                                truncated=is_trunc,
                            )

                # Pass 2 targeted self-correction via direct PeerBus CorrectionDirectives + selective re-audit
                if not audit.get("fully_balanced"):
                    directives: Dict[str, Dict[str, Any]] = {}
                    issues_blob = " ".join(audit.get("blocking_issues") or []).lower()
                    if "gstin" in issues_blob or not audit.get("seller_gstin_valid"):
                        directives["supplier_identity"] = {"reason": "gstin_check"}
                    if not audit.get("buyer_gstin_valid"):
                        directives["buyer_direction"] = {"reason": "buyer_gstin_check"}
                    if audit.get("bad_rows") or not audit.get("slab_match") or not audit.get("tax_match"):
                        for dc in ("line_items", "hsn_classification", "tax_summary_slab"):
                            if dc in categories:
                                directives[dc] = {"reason": "row_or_slab_mismatch"}
                    if not audit.get("grand_balanced") or not audit.get("words_match"):
                        if "totals_words" in categories:
                            directives["totals_words"] = {"reason": "grand_total_or_words_mismatch"}

                    if directives:
                        ctx.pass_no = 2
                        self.tracker.transition(job.invoice_id, "SELF_CORRECT", {"passCount": 2})
                        for target_agent, d_payload in directives.items():
                            self.bus.publish("auditor_agent", target_agent, "correction_directive", ctx.invoice_id, d_payload, pass_no=2)
                        self._run_category_wave(ctx, list(directives.keys()), directives=directives)
                        ctx.canonical = normalize_canonical_dict(ctx.canonical, ctx.raw_ocr_text, qr_einv, qr_upi_meta=qr_upi)
                        # Re-audit only the affected categories in parallel and merge into the 1:1 audit children list
                        re_cats = [c for c in categories if c in directives] or list(directives.keys())
                        new_audit, updated_children = run_parallel_category_audits(
                            ctx.canonical,
                            re_cats,
                            pool=self._audit_pool,
                            bus=self.bus,
                            invoice_id=job.invoice_id,
                            pass_no=2,
                            qr_einvoice=qr_einv,
                            truncated=is_trunc,
                        )
                        by_cat = {c["category"]: c for c in updated_children}
                        merged_children = [by_cat.get(c["category"], c) for c in audit_children]
                        for c_rec in updated_children:
                            if all(m["category"] != c_rec["category"] for m in merged_children):
                                merged_children.append(c_rec)
                        audit = new_audit
                        audit["auditAgentCount"] = len(merged_children)
                        audit["categoryAgentCount"] = len(categories)
                        audit["perAgentAudit"] = merged_children
                        audit_children = merged_children

                self.tracker.record_audit_children(job.invoice_id, audit_children)
                ctx.audit = audit
                pkt["audit_children"] = audit_children
                self.bus.publish(
                    "auditor_agent",
                    "final_handoff",
                    "audit_verdict",
                    ctx.invoice_id,
                    {
                        "fullyBalanced": bool(audit.get("fully_balanced")),
                        "blockingCount": len(audit.get("blocking_issues") or []),
                        "auditAgentCount": len(audit_children),
                    },
                    pass_no=ctx.pass_no,
                )
                self._q_handoff.put(pkt)
            except Exception as ex:
                self._mark_job_failed(pkt, f"Stage4 Auditor error: {ex}")

    # ---------------- Stage 5: Dedicated Continuous FinalHandoffAgent ----------------
    def _run_handoff_stage(self) -> None:
        while True:
            pkt = self._q_handoff.get()
            if pkt is None:
                break
            job: BatchJob = pkt["job"]
            ctx: InvoiceWorkContext = pkt["ctx"]
            try:
                self.tracker.transition(job.invoice_id, "FINAL_HANDOFF")
                canon = dict(ctx.canonical)
                audit = dict(ctx.audit)
                canon.pop("_audit", None)
                raw_tables = list(canon.pop("rawTablesHtml", []) or [])

                memory_meta: Dict[str, Any] = {
                    "profileFound": False,
                    "gstin": "",
                    "canonicalName": "",
                    "confirmedCount": 0,
                    "preferredDirection": "",
                    "preferredRecognitionMode": "",
                    "appliedRules": [],
                }
                saved_agents: List[str] = []
                if job.memory_db:
                    if audit.get("fully_balanced"):
                        memory_meta = apply_supplier_memory(canon, str(job.memory_db), client_gstin=job.client_gstin)
                        saved_agents = persist_learned_agent_memories(ctx)
                    else:
                        memory_meta["skippedReason"] = "audit_not_balanced"

                elapsed = round(time.perf_counter() - float(pkt["started"]), 2)
                engine_tag = "LightOnOCR-2-1B-P2-Cached" if pkt.get("cache_hit") else "LightOnOCR-2-1B-P2"
                snap = self.tracker.snapshot(job.invoice_id)
                audit_children = pkt.get("audit_children") or []
                trace = {
                    "invoiceId": job.invoice_id,
                    "dispatchedCategories": pkt.get("categories", []),
                    "categoryAgentCount": len(pkt.get("categories", [])),
                    "auditAgentCount": len(audit_children),
                    "auditChildAgents": audit_children,
                    "stageChildAgents": snap.get("stageChildAgents", {}),
                    "llamaParallelSlots": self.llama_parallel,
                    "passCount": ctx.pass_no,
                    "cacheHit": bool(pkt.get("cache_hit")),
                    "finishReasons": pkt.get("finish_reasons", []),
                    "savedAgentMemories": saved_agents,
                    "agentNotes": ctx.agent_notes,
                    "peerMessages": self.bus.trace_for_invoice(job.invoice_id),
                    "stageHistory": snap.get("stageHistory", []),
                }

                payload = {
                    "schema": "AAH-INVOICEVISION-WORKER-V1",
                    "engineUsed": engine_tag,
                    "elapsedSec": elapsed,
                    "preprocessing": pkt["prep_records"],
                    "preprocessedImages": [str(p) for p in pkt["p2_paths"]],
                    "renderedPageImages": [str(p) for p in pkt["raw_pages"]],
                    "qrInfo": pkt["qr_info"],
                    "sourceFiles": job.source_sha256,
                    "canonical": canon,
                    "audit": audit,
                    "supplierMemory": memory_meta,
                    "rawOcrText": ctx.raw_ocr_text,
                    "rawTablesHtml": raw_tables,
                    "agentPipelineTrace": trace,
                }

                out_path = Path(job.output_path).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = out_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, out_path)

                job.result_payload = payload
                self.tracker.transition(job.invoice_id, "DONE")
                self.bus.clear_invoice(job.invoice_id)
                job.done_event.set()
                with self._active_lock:
                    self._pending_count = max(0, self._pending_count - 1)
                    self._all_done_cond.notify_all()
            except Exception as ex:
                self._mark_job_failed(pkt, f"Stage5 FinalHandoff error: {ex}")


def run_batch_jobs(
    jobs: List[BatchJob],
    llama_server: Path,
    lighton_model: Path,
    lighton_mmproj: Path,
    paddlex_cache: Path,
    cache_dir: Path,
    threads: int = 10,
    progress_cb: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Run 1..N invoices through the continuous ManagerAgent pipeline and exit cleanly when 0 remain."""
    mgr = ManagerAgent(
        llama_server=llama_server,
        lighton_model=lighton_model,
        lighton_mmproj=lighton_mmproj,
        paddlex_cache=paddlex_cache,
        cache_dir=cache_dir,
        threads=threads,
        progress_cb=progress_cb,
    )
    t0 = time.perf_counter()
    try:
        for job in jobs:
            mgr.submit(job)
        mgr.wait_all()
    finally:
        mgr.shutdown()
    return {
        "totalElapsedSec": round(time.perf_counter() - t0, 2),
        "llamaBootCount": mgr.llama_boot_count,
        "states": mgr.tracker.all_snapshots(),
    }


def serve_warm_daemon(
    manager: ManagerAgent,
    daemon_info_file: Path,
    idle_timeout_s: float = 45.0,
) -> int:
    """Keep ManagerAgent + warm LightOnOCR-2-1B alive across C# ExtractionQueue calls and auto-exit when idle."""
    if manager.daemon_log_dir is None:
        manager.daemon_log_dir = manager.cache_dir / "logs"
    activity_lock = threading.Lock()
    last_activity = [time.monotonic()]
    active_escalations = [0]
    stop_event = threading.Event()

    def touch() -> None:
        with activity_lock:
            last_activity[0] = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/health":
                touch()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ready"}')
                return
            if self.path.startswith("/progress"):
                touch()
                inv_id = ""
                if "invoiceId=" in self.path:
                    inv_id = self.path.split("invoiceId=", 1)[1].split("&", 1)[0]
                snap = manager.tracker.snapshot(inv_id) if inv_id else {}
                body = json.dumps(
                    {
                        "stage": snap.get("stage", ""),
                        "activeAgents": snap.get("activeAgents", []),
                        "completedAgents": snap.get("completedAgents", []),
                        "dispatchedCategories": snap.get("dispatchedCategories", []),
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            touch()
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            if self.path == "/shutdown":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"stopping":true}')
                stop_event.set()
                return
            if self.path == "/escalate-qwen":
                with activity_lock:
                    active_escalations[0] += 1
                    last_activity[0] = time.monotonic()
                t_esc0 = time.perf_counter()
                try:
                    req = json.loads(raw.decode("utf-8"))
                    out_p = Path(req["workerOutput"])
                    wo = json.loads(out_p.read_text(encoding="utf-8"))
                    with manager.exclusive_qwen_gate():
                        apply_qwen_escalation_to_worker_payload(
                            wo,
                            llama_server=manager.llama_server,
                            qwen_model=Path(req["qwenModel"]),
                            qwen_mmproj=Path(req["qwenMmproj"]),
                            work_dir=Path(req["workDir"]),
                            client_gstin=str(req.get("clientGstin") or ""),
                            direction=str(req.get("direction") or "Auto"),
                            memory_db=str(req.get("memoryDb") or ""),
                            threads=manager.threads,
                        )
                    wo["elapsedSec"] = round(
                        float(wo.get("elapsedSec") or 0.0)
                        + (time.perf_counter() - t_esc0)
                        + float(req.get("waitOffsetSec") or 0.0),
                        2,
                    )
                    tmp_out = out_p.with_suffix(".json.tmp")
                    tmp_out.write_text(json.dumps(wo, indent=2, ensure_ascii=False), encoding="utf-8")
                    os.replace(tmp_out, out_p)
                    body = json.dumps({"ok": True, "engineUsed": wo["engineUsed"], "balanced": bool((wo["audit"] or {}).get("fully_balanced"))}).encode("utf-8")
                    self.send_response(200)
                except Exception as ex:
                    body = json.dumps({"ok": False, "error": str(ex)}).encode("utf-8")
                    self.send_response(500)
                finally:
                    with activity_lock:
                        active_escalations[0] = max(0, active_escalations[0] - 1)
                        last_activity[0] = time.monotonic()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path != "/extract":
                self.send_response(404)
                self.end_headers()
                return
            try:
                req = json.loads(raw.decode("utf-8"))
                job = BatchJob(
                    invoice_id=str(req.get("invoiceId") or f"JOB-{int(time.time()*1000)}"),
                    input_paths=[Path(p) for p in req["inputs"]],
                    output_path=Path(req["output"]),
                    work_dir=Path(req["workDir"]),
                    mode=str(req.get("mode") or "auto"),
                    client_gstin=str(req.get("clientGstin") or ""),
                    direction=str(req.get("direction") or "Auto"),
                    memory_db=Path(req["memoryDb"]) if req.get("memoryDb") else None,
                    cached_ocr_json=Path(req["cachedOcrJson"]) if req.get("cachedOcrJson") else None,
                )
                manager.submit(job)
                job.done_event.wait(timeout=1800)
                touch()
                if job.error or not job.result_payload:
                    body = json.dumps({"ok": False, "error": job.error or "timeout"}).encode("utf-8")
                    self.send_response(500)
                else:
                    body = json.dumps(
                        {"ok": True, "elapsedSec": job.result_payload.get("elapsedSec", 0.0), "engineUsed": job.result_payload.get("engineUsed", "")}
                    ).encode("utf-8")
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as ex:
                body = json.dumps({"ok": False, "error": str(ex)}).encode("utf-8")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    daemon_info_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_info = daemon_info_file.with_suffix(".tmp")
    tmp_info.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    os.replace(tmp_info, daemon_info_file)

    srv.timeout = 1.0
    try:
        while not stop_event.is_set():
            srv.handle_request()
            with activity_lock:
                idle_for = time.monotonic() - last_activity[0]
                esc_active = active_escalations[0]
            if idle_for >= idle_timeout_s and manager._pending_count == 0 and esc_active == 0:
                break
    finally:
        try:
            daemon_info_file.unlink(missing_ok=True)
        except Exception:
            pass
        srv.server_close()
        manager.shutdown()
    return 0
