#!/usr/bin/env python3
"""Offline AI Diagnostic & GST Verification Analyst for InvoiceVisionChild v2.

Phase 1 (<50ms deterministic): audits GSTIN checksums, state codes vs intra/interstate
tax split, row-to-slab & slab-to-header arithmetic, Accounting-vs-Item posting preview,
Indian GST OCR layout traps, and SQLite supplier self-learning memory status.

Phase 2 (optional local CPU Qwen3-VL-4B text-only): launches llama-server without
mmproj to produce a concise 3-5 bullet plain-English CA diagnostic summary.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gst_math import VALID_STATE_CODES, is_valid_gstin  # noqa: E402
from hybrid_merger import LlamaServerSession  # noqa: E402
from supplier_memory import lookup_supplier_profile, normalize_gstin  # noqa: E402

ANALYST_SYSTEM_PROMPT = (
    "You are an offline Chartered Accountant & GST Invoice Audit assistant inside Accounting Automation Hub. "
    "Explain in 3-5 short plain-English bullet points: (1) invoice math & GST health, "
    "(2) why Accounting Invoice vs Item Invoice mode behaves cleanly on import, and "
    "(3) any specific discrepancy or supplier rule the reviewer should check. "
    "Use ONLY numbers provided in the audit summary and OCR excerpt. Never invent figures or use markdown tables."
)


def _f(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def run_deterministic_audit(req: Dict[str, Any], memory_db: str = "") -> Dict[str, Any]:
    findings: List[str] = []
    recommendations: List[str] = []

    inv_no = str(req.get("invoiceNumber") or "").strip()
    inv_date = str(req.get("invoiceDate") or "").strip()
    direction = str(req.get("direction") or "Auto").strip()
    rec_mode = str(req.get("recognitionMode") or "Accounting Invoice").strip() or "Accounting Invoice"
    client_gstin = normalize_gstin(str(req.get("clientGstin") or ""))
    seller_name = str(req.get("sellerName") or "").strip()
    seller_gstin = normalize_gstin(str(req.get("sellerGstin") or ""))
    buyer_name = str(req.get("buyerName") or "").strip()
    buyer_gstin = normalize_gstin(str(req.get("buyerGstin") or ""))
    raw_ocr = str(req.get("rawOcrText") or "")
    blocking_flags = [str(x).strip() for x in (req.get("blockingFlags") or []) if str(x).strip()]

    tx_total = _f(req.get("taxableTotal"))
    cgst_total = _f(req.get("cgstTotal"))
    sgst_total = _f(req.get("sgstTotal"))
    igst_total = _f(req.get("igstTotal"))
    cess_total = _f(req.get("cessTotal"))
    round_off = _f(req.get("roundOff"))
    inv_total = _f(req.get("invoiceTotal"))

    rows = req.get("rows") or []
    slabs = req.get("gstSlabs") or []

    severity = 0  # 0=Verified, 1=Attention Needed, 2=Action Required

    if not inv_no:
        severity = max(severity, 2)
        findings.append("Invoice Number is blank.")
    if not inv_date:
        severity = max(severity, 2)
        findings.append("Invoice Date is blank.")

    if seller_gstin:
        if is_valid_gstin(seller_gstin):
            st = f"State {seller_gstin[:2]}"
            findings.append(f"Seller GSTIN {seller_gstin} passes Mod-36 checksum ({st}).")
        else:
            severity = max(severity, 2)
            findings.append(f"Seller GSTIN '{seller_gstin}' failed Mod-36 checksum.")
            recommendations.append("Verify the 15-character Seller GSTIN against the original invoice image.")
    else:
        severity = max(severity, 1)
        findings.append("Seller GSTIN is missing.")

    if buyer_gstin:
        if is_valid_gstin(buyer_gstin):
            st = f"State {buyer_gstin[:2]}"
            findings.append(f"Buyer GSTIN {buyer_gstin} passes Mod-36 checksum ({st}).")
        else:
            severity = max(severity, 2)
            findings.append(f"Buyer GSTIN '{buyer_gstin}' failed Mod-36 checksum.")

    if is_valid_gstin(client_gstin) and is_valid_gstin(seller_gstin) and is_valid_gstin(buyer_gstin):
        expected_dir = "Sales" if client_gstin == seller_gstin else "Purchase" if client_gstin == buyer_gstin else ""
        if expected_dir and direction and expected_dir.lower() != direction.lower():
            severity = max(severity, 2)
            findings.append(f"Direction '{direction}' disagrees with Client GSTIN ({client_gstin} matches {expected_dir}).")
        elif expected_dir:
            findings.append(f"Direction '{expected_dir}' verified against Client GSTIN {client_gstin}.")

    if len(seller_gstin) >= 2 and len(buyer_gstin) >= 2:
        same_state = seller_gstin[:2] == buyer_gstin[:2]
        if same_state and igst_total > 0.05 and cgst_total == 0.0:
            severity = max(severity, 1)
            findings.append(f"Both parties are in state code {seller_gstin[:2]}, yet IGST ({igst_total:.2f}) is populated instead of CGST+SGST.")
        elif not same_state and (cgst_total > 0.05 or sgst_total > 0.05) and igst_total == 0.0:
            findings.append(f"Cross-state states ({seller_gstin[:2]} -> {buyer_gstin[:2]}) use CGST+SGST (intra-state Place of Supply).")

    # Row-to-header & Grand total check
    row_tx_sum = round(sum(_f(r.get("taxable")) for r in rows), 2)
    row_tax_diff = abs(row_tx_sum - tx_total)
    if rows and tx_total > 0.0:
        if row_tax_diff <= 0.25:
            findings.append(f"All {len(rows)} extracted row(s) reconcile with Taxable Total ({row_tx_sum:.2f} vs {tx_total:.2f}).")
        else:
            severity = max(severity, 2)
            findings.append(f"Row Taxable sum {row_tx_sum:.2f} differs from Header Taxable {tx_total:.2f} by Rs {row_tax_diff:.2f}.")
            recommendations.append("Check for a missing row, multi-page carry-forward page, or scheme discount column.")
    elif not rows and inv_total > 0.0:
        severity = max(severity, 1)
        findings.append("Zero item rows extracted; summary totals only.")

    computed_grand = round(tx_total + cgst_total + sgst_total + igst_total + cess_total + round_off, 2)
    grand_diff = abs(inv_total - computed_grand)
    if inv_total > 0.0 and grand_diff <= 0.25:
        findings.append(
            f"Grand total reconciles: {tx_total:.2f} + CGST {cgst_total:.2f} + SGST {sgst_total:.2f} + IGST {igst_total:.2f}"
            + (f" + RoundOff {round_off:+.2f}" if abs(round_off) > 0.001 else "")
            + f" = {inv_total:.2f}."
        )
    elif inv_total > 0.0:
        severity = max(severity, 2)
        findings.append(f"Invoice Total {inv_total:.2f} disagrees with Taxable+GST+RoundOff ({computed_grand:.2f}, diff {grand_diff:.2f}).")
        recommendations.append("Check Credit Note deduction, Freight/TCS charges, or Round Off sign on the original bill.")

    if abs(cgst_total - sgst_total) > 0.15 and igst_total <= 0.05:
        severity = max(severity, 2)
        findings.append(f"CGST ({cgst_total:.2f}) and SGST ({sgst_total:.2f}) are unequal.")

    # Posting Preview (Accounting Invoice vs Item Invoice clarity)
    unique_rates = sorted({round(_f(s.get("gstRate")), 2) for s in slabs if _f(s.get("taxable")) > 0} | {round(_f(r.get("gstRate")), 2) for r in rows if _f(r.get("taxable")) > 0})
    is_inventory_mode = rec_mode.lower() in ("item invoice", "inventory invoice")
    if is_inventory_mode:
        missing_qty = sum(1 for r in rows if _f(r.get("quantity")) <= 0 or not str(r.get("unit") or "").strip())
        posting_preview = f"Item Invoice mode: will import {len(rows)} inventory item line(s) with Qty/Unit/Rate into Purchase/Sales & Tally Item Invoice."
        if missing_qty > 0:
            severity = max(severity, 1)
            recommendations.append(f"{missing_qty} row(s) are missing Qty or Unit for Item Invoice mode; fill them or switch Mode to 'Accounting Invoice' if you want ledger-only slab posting.")
    else:
        slab_count = max(1, len(unique_rates) if rows else (1 if tx_total > 0 else 0))
        rate_desc = ", ".join(f"{r:g}%" for r in unique_rates) if unique_rates else "summary"
        posting_preview = (
            f"Accounting Invoice mode: will collapse {len(rows)} extracted line(s) into {slab_count} pure GST-slab accounting row(s) "
            f"({rate_desc}) with ZERO inventory items / quantities / <ALLINVENTORYENTRIES.LIST>."
        )

    # Known Indian GST layout traps scan
    if re.search(r"cont\.?\s*page\s*\d+|carried\s*forward|c/f|b/f", raw_ocr, re.IGNORECASE):
        findings.append("OCR text contains multi-page continuation markers (Cont. Page / C/F / B/F).")
    if re.search(r"incl\.?\s*of\s*tax|mrp\s*incl", raw_ocr, re.IGNORECASE):
        findings.append("Bill shows tax-inclusive rate/MRP columns; taxable value should remain post-discount pre-tax.")
    if re.search(r"sch\.?\s*disc|scheme\s*disc", raw_ocr, re.IGNORECASE):
        findings.append("Scheme discount column detected on source bill.")
    if blocking_flags:
        severity = max(severity, 1)
        findings.append("Verification notes flagged: " + "; ".join(blocking_flags[:4]))

    # Supplier Self-Learning Memory Lookup
    opposite_gstin = seller_gstin if direction.lower() != "sales" else buyer_gstin
    opposite_name = seller_name if direction.lower() != "sales" else buyer_name
    profile = lookup_supplier_profile(memory_db, opposite_gstin or seller_gstin, opposite_name or seller_name)
    if profile is not None:
        hsn_count = len(profile.get("hsnRates") or {})
        pref_mode = profile.get("preferredRecognitionMode") or "Accounting Invoice"
        mem_status = f"Learned profile active for {profile['canonicalName'] or profile['gstin']} ({profile['confirmedCount']} confirmed bill(s), {hsn_count} HSN rate(s), preferred mode: {pref_mode})."
        findings.append(mem_status)
    else:
        mem_status = f"New supplier ({opposite_gstin or 'no GSTIN yet'}): confirming this invoice will teach Offline AI Memory in 1 shot."
        recommendations.append("Once fields look right, click 'Teach AI' or 'Confirm Mapping & Next' so future bills from this party auto-apply your corrections.")

    verdict = "Verified" if severity == 0 else ("Attention Needed" if severity == 1 else "Action Required")
    if not recommendations:
        recommendations.append("All GST math & mode checks look clean — ready to confirm.")

    return {
        "verdict": verdict,
        "summary": f"{verdict} · Invoice {inv_no or '?'} · {posting_preview}",
        "postingPreview": posting_preview,
        "supplierMemoryStatus": mem_status,
        "findings": findings,
        "recommendations": recommendations,
    }


def run_llm_explanation(
    audit: Dict[str, Any],
    req: Dict[str, Any],
    llama_server: Path,
    qwen_model: Path,
    work_dir: Path,
    threads: int = 10,
) -> tuple[str, str]:
    excerpt = str(req.get("rawOcrText") or "").strip()
    if len(excerpt) > 2000:
        excerpt = excerpt[:1200] + "\n...\n" + excerpt[-750:]

    user_prompt = (
        f"Invoice No: {req.get('invoiceNumber', '')} | Date: {req.get('invoiceDate', '')} | Direction: {req.get('direction', '')} | Mode: {req.get('recognitionMode', 'Accounting Invoice')}\n"
        f"Seller: {req.get('sellerName', '')} ({req.get('sellerGstin', '')})\n"
        f"Buyer: {req.get('buyerName', '')} ({req.get('buyerGstin', '')})\n"
        f"Totals: Taxable={_f(req.get('taxableTotal')):.2f}, CGST={_f(req.get('cgstTotal')):.2f}, SGST={_f(req.get('sgstTotal')):.2f}, IGST={_f(req.get('igstTotal')):.2f}, RoundOff={_f(req.get('roundOff')):.2f}, Grand={_f(req.get('invoiceTotal')):.2f}\n"
        f"Posting Preview: {audit['postingPreview']}\n"
        f"Memory Status: {audit['supplierMemoryStatus']}\n"
        f"Deterministic Findings:\n- " + "\n- ".join(audit["findings"][:8]) + "\n\n"
        f"OCR Excerpt:\n{excerpt}"
    )

    with LlamaServerSession(str(llama_server), str(qwen_model), None, work_dir / "logs", threads=threads, ctx=3072) as srv:
        reply = srv.chat_text(ANALYST_SYSTEM_PROMPT, user_prompt, max_tokens=360, timeout_s=75)
    return reply.strip(), "Qwen3-VL-4B (Offline CPU Text Analyst)"


def resolve_default_qwen_paths() -> tuple[Path, Path]:
    app_root = SCRIPT_DIR.parent
    for root in (app_root / "Runtime", Path(r"C:\AccountingAutomationHub\InvoiceVisionChild\Runtime")):
        ls = root / "llama_bin" / "llama-server.exe"
        qm = root / "models" / "qwen3-vl-4b" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
        if ls.is_file() and qm.is_file():
            return ls, qm
    return (
        app_root / "Runtime" / "llama_bin" / "llama-server.exe",
        app_root / "Runtime" / "models" / "qwen3-vl-4b" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="InvoiceVisionChild v2 Offline AI Analyst")
    parser.add_argument("--input", required=True, help="Input analysis request JSON path")
    parser.add_argument("--output", required=True, help="Output analysis result JSON path")
    parser.add_argument("--memory-db", default="", help="Optional path to supplier_memory.db")
    parser.add_argument("--llama-server", default="")
    parser.add_argument("--qwen-model", default="")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--no-llm", action="store_true", help="Run fast deterministic GST/memory diagnostics only")
    args = parser.parse_args()

    t0 = time.perf_counter()
    req_path = Path(args.input).resolve()
    req = json.loads(req_path.read_text(encoding="utf-8-sig"))
    mem_db = args.memory_db or str(req.get("memoryDbPath") or "")

    audit = run_deterministic_audit(req, memory_db=mem_db)

    def_ls, def_qm = resolve_default_qwen_paths()
    llama_server = Path(args.llama_server or def_ls)
    qwen_model = Path(args.qwen_model or def_qm)
    use_llm = (not args.no_llm) and bool(req.get("useLlm", True)) and llama_server.is_file() and qwen_model.is_file()

    llm_explanation = ""
    llm_engine = "Deterministic GST & Memory Auditor"
    if use_llm:
        try:
            llm_explanation, llm_engine = run_llm_explanation(
                audit, req, llama_server, qwen_model, req_path.parent / "analyst_work", threads=args.threads
            )
        except Exception as ex:
            llm_explanation = f"Deterministic audit completed (local LLM note: {type(ex).__name__}: {ex})."

    elapsed = round(time.perf_counter() - t0, 2)
    payload = {
        "schema": "AAH-INVOICEVISION-ANALYSIS-V1",
        "verdict": audit["verdict"],
        "summary": audit["summary"],
        "postingPreview": audit["postingPreview"],
        "supplierMemoryStatus": audit["supplierMemoryStatus"],
        "findings": audit["findings"],
        "recommendations": audit["recommendations"],
        "llmExplanation": llm_explanation,
        "llmEngineUsed": llm_engine,
        "elapsedSec": elapsed,
    }

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, out_path)
    print(f"ANALYSIS_OK|{payload['verdict']}|{elapsed}s|{llm_engine}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
