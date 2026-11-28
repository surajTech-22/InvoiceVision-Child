#!/usr/bin/env python3
"""Dynamic category sub-agents & extensible dispatcher for GST invoices.

No fixed 5-agent cap: `discover_bill_categories()` inspects the invoice's actual text,
HTML/markdown structure, QR payload, and page count, dispatching only the category
sub-agents needed for that invoice (and supporting dynamic plugin registration).
Each sub-agent runs inside a reusable thread pool, reads/writes peer signals over
`PeerBus`, consults per-agent self-learning SQLite memory, and handles targeted
Pass 2 `correction_directive` messages from `AuditorAgent`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent_bus import PeerBus
from gst_parser import (
    _clean_party_name,
    _subset_match_indices,
    build_gst_slabs,
    clean_num,
    extract_amount_in_words,
    find_gstins_in_text,
    normalize_canonical_dict,
    parse_document_text_to_canonical,
    repair_gstin,
    round2,
)
from supplier_memory import load_agent_memory, save_agent_memory


@dataclass
class InvoiceWorkContext:
    invoice_id: str
    raw_ocr_text: str
    page_texts: List[str]
    qr_info: Dict[str, Any]
    client_gstin: str = ""
    direction: str = "Auto"
    memory_db: Optional[Path] = None
    canonical: Dict[str, Any] = field(default_factory=dict)
    audit: Dict[str, Any] = field(default_factory=dict)
    agent_notes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    learned_rules: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pass_no: int = 1


CategoryHandler = Callable[[InvoiceWorkContext, PeerBus, Optional[Dict[str, Any]]], Dict[str, Any]]


class CategoryRegistry:
    """Extensible registry mapping category name -> agent handler + trigger rule."""

    def __init__(self) -> None:
        self._handlers: Dict[str, CategoryHandler] = {}

    def register(self, category_name: str, handler: CategoryHandler) -> None:
        self._handlers[category_name] = handler

    def handler_for(self, category_name: str) -> Optional[CategoryHandler]:
        return self._handlers.get(category_name)

    def registered_categories(self) -> List[str]:
        return list(self._handlers.keys())


REGISTRY = CategoryRegistry()


def discover_bill_categories(ctx: InvoiceWorkContext) -> List[str]:
    """Dynamically determine which category sub-agents this specific bill requires."""
    raw = ctx.raw_ocr_text or ""
    low = raw.lower()
    cats: List[str] = ["supplier_identity", "buyer_direction", "invoice_header"]

    if (ctx.qr_info or {}).get("einvoice") or (ctx.qr_info or {}).get("upi_meta") or "irn" in low:
        cats.append("qr_authority")

    if len(ctx.page_texts) > 1 or re.search(r"page\s+\d+\s+of\s+[2-9]", low):
        cats.append("multipage_continuity")

    if "<table" in low or "|" in raw or re.search(r"\b(?:qty|quantity|pcs|box|qtls|rate|mrp|amount|item)\b", low):
        cats.append("line_items")

    if "hsn" in low or "sac" in low or re.search(r"\b\d{6,8}\b", raw):
        cats.append("hsn_classification")

    if re.search(r"\b(?:disc|discount|sch|scheme|free|round\s*[-]?\s*off|credit\s*note|less\s*:)\b", low):
        cats.append("discount_charges")

    if re.search(r"\b(?:cgst|sgst|utgst|igst|cess|tax\s*summary|taxable\s*value)\b", low):
        cats.append("tax_summary_slab")

    cats.append("totals_words")
    return cats


def initialize_base_parse(ctx: InvoiceWorkContext) -> None:
    """Build baseline canonical extraction once per invoice after Stage 2 OCR finishes."""
    qr_einv = (ctx.qr_info or {}).get("einvoice")
    qr_upi = (ctx.qr_info or {}).get("upi_meta")
    learned_rules: Optional[Dict[str, Any]] = None
    if ctx.memory_db:
        try:
            from ai_self_learning import lookup_layout_rules

            prelim_gstins = find_gstins_in_text(ctx.raw_ocr_text or "")
            cand_sup = next((g for g in prelim_gstins if g and g != (ctx.client_gstin or "").strip().upper()), "")
            lctx = lookup_layout_rules(
                str(ctx.memory_db),
                ctx.raw_ocr_text or "",
                supplier_gstin=cand_sup,
                client_gstin=ctx.client_gstin,
            )
            if lctx.get("rules"):
                learned_rules = lctx["rules"]
                ctx.agent_notes["_layoutMemory"] = {
                    "matched": True,
                    "matchType": lctx.get("matchType", ""),
                    "layoutHash": lctx.get("layoutHash", ""),
                }
        except Exception:
            learned_rules = None

    ctx.canonical = parse_document_text_to_canonical(
        ctx.raw_ocr_text,
        qr_einvoice=qr_einv,
        known_client_gstin=ctx.client_gstin,
        direction_hint=ctx.direction,
        qr_upi_meta=qr_upi,
        learned_rules=learned_rules,
    )


def _agent_mem_load(ctx: InvoiceWorkContext, agent_name: str, gstin: str) -> Dict[str, Any]:
    if not ctx.memory_db or not gstin:
        return {}
    return load_agent_memory(ctx.memory_db, agent_name, gstin)


def _handle_qr_authority(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    qr_einv = (ctx.qr_info or {}).get("einvoice") or {}
    qr_upi = (ctx.qr_info or {}).get("upi_meta") or {}
    note: Dict[str, Any] = {
        "hasEinvoiceQr": bool(qr_einv),
        "hasUpiQr": bool(qr_upi),
        "docNo": str(qr_einv.get("DocNo") or ""),
        "totInvVal": clean_num(qr_einv.get("TotInvVal")),
        "sellerGstin": str(qr_einv.get("SellerGstin") or ""),
        "buyerGstin": str(qr_einv.get("BuyerGstin") or ""),
    }
    if qr_einv:
        bus.publish("qr_authority", "supplier_identity", "qr_gstins", ctx.invoice_id, {"sellerGstin": note["sellerGstin"]}, ctx.pass_no)
        bus.publish("qr_authority", "buyer_direction", "qr_gstins", ctx.invoice_id, {"buyerGstin": note["buyerGstin"]}, ctx.pass_no)
        bus.publish("qr_authority", "invoice_header", "qr_header", ctx.invoice_id, {"docNo": note["docNo"], "docDt": qr_einv.get("DocDt")}, ctx.pass_no)
        bus.publish("qr_authority", "totals_words", "qr_total", ctx.invoice_id, {"totInvVal": note["totInvVal"]}, ctx.pass_no)
    return note


def _handle_supplier_identity(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    seller = ctx.canonical.setdefault("seller", {"name": "", "gstin": ""})
    qr_hint = bus.latest_payload("supplier_identity", ctx.invoice_id, "qr_gstins")
    if qr_hint.get("sellerGstin"):
        sg, ok, _ = repair_gstin(qr_hint["sellerGstin"])
        if ok:
            seller["gstin"] = sg

    gstin = str(seller.get("gstin") or "")
    mem = _agent_mem_load(ctx, "supplier_identity", gstin)
    if mem.get("sellerName") and (not seller.get("name") or directive):
        seller["name"] = str(mem["sellerName"])

    cleaned = _clean_party_name(str(seller.get("name") or ""))
    if cleaned:
        seller["name"] = cleaned

    if gstin:
        _, sg_ok, _ = repair_gstin(gstin)
        if not sg_ok or directive:
            for cand in find_gstins_in_text(ctx.raw_ocr_text):
                if cand != (ctx.canonical.get("buyer") or {}).get("gstin"):
                    cg, ok2, _ = repair_gstin(cand)
                    if ok2:
                        seller["gstin"] = cg
                        gstin = cg
                        break

    if seller.get("name") and seller.get("gstin"):
        ctx.learned_rules["supplier_identity"] = {"sellerName": seller["name"]}
    bus.publish("supplier_identity", "broadcast", "seller_resolved", ctx.invoice_id, dict(seller), ctx.pass_no)
    return {"sellerName": seller.get("name", ""), "sellerGstin": seller.get("gstin", ""), "usedMemory": bool(mem)}


def _handle_buyer_direction(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    buyer = ctx.canonical.setdefault("buyer", {"name": "", "gstin": ""})
    seller_info = bus.latest_payload("buyer_direction", ctx.invoice_id, "seller_resolved")
    qr_hint = bus.latest_payload("buyer_direction", ctx.invoice_id, "qr_gstins")
    if qr_hint.get("buyerGstin"):
        bg, ok, _ = repair_gstin(qr_hint["buyerGstin"])
        if ok and bg != seller_info.get("gstin"):
            buyer["gstin"] = bg
    cleaned = _clean_party_name(str(buyer.get("name") or ""))
    if cleaned:
        buyer["name"] = cleaned
    if directive and ctx.client_gstin:
        cg, ok, _ = repair_gstin(ctx.client_gstin)
        if ok and (ctx.direction or "").lower() == "purchase" and not buyer.get("gstin"):
            buyer["gstin"] = cg
    return {"buyerName": buyer.get("name", ""), "buyerGstin": buyer.get("gstin", "")}


def _handle_invoice_header(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    qr_hdr = bus.latest_payload("invoice_header", ctx.invoice_id, "qr_header")
    if qr_hdr.get("docNo") and not ctx.canonical.get("invoiceNumber"):
        ctx.canonical["invoiceNumber"] = str(qr_hdr["docNo"])
    return {
        "invoiceNumber": ctx.canonical.get("invoiceNumber", ""),
        "invoiceDate": ctx.canonical.get("invoiceDate", ""),
        "documentType": ctx.canonical.get("documentType", "Tax Invoice"),
    }


def _handle_multipage_continuity(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    page_count = max(1, len(ctx.page_texts))
    truncated_pages = [i + 1 for i, p in enumerate(ctx.page_texts) if p.count("<table") > p.count("</table>") or p.count("<tr>") > p.count("</tr>")]
    note = {"pageCount": page_count, "truncatedPages": truncated_pages}
    bus.publish("multipage_continuity", "line_items", "multipage_state", ctx.invoice_id, note, ctx.pass_no)
    return note


def _handle_discount_charges(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = ctx.canonical.get("rows") or []
    disc_tot = round2(sum(float(r.get("discount") or 0.0) for r in rows))
    ctx.canonical["discountTotal"] = disc_tot
    note = {
        "discountTotal": disc_tot,
        "roundOff": float(ctx.canonical.get("roundOff") or 0.0),
        "creditNoteTotal": float(ctx.canonical.get("creditNoteTotal") or 0.0),
    }
    bus.publish("discount_charges", "line_items", "discount_summary", ctx.invoice_id, note, ctx.pass_no)
    bus.publish("discount_charges", "totals_words", "adjustments", ctx.invoice_id, note, ctx.pass_no)
    return note


def _handle_line_items(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = ctx.canonical.get("rows") or []
    rows_clean = []
    for r in rows:
        desc = str(r.get("description") or "").strip().lower()
        if desc in ("c-gst", "s-gst", "i-gst", "cgst", "sgst", "igst", "round off", "less: round off"):
            continue
        rows_clean.append(r)
    if len(rows_clean) != len(rows):
        ctx.canonical["rows"] = rows_clean
        rows = rows_clean

    bus.publish(
        "line_items",
        "hsn_classification",
        "rows_snapshot",
        ctx.invoice_id,
        {"rowCount": len(rows), "zeroRateCount": sum(1 for r in rows if float(r.get("gstRate") or 0.0) == 0.0)},
        ctx.pass_no,
    )
    return {"rowCount": len(rows), "rowTaxableSum": round2(sum(float(r.get("taxable") or 0.0) for r in rows))}


def _handle_hsn_classification(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = ctx.canonical.get("rows") or []
    seller_gstin = str((ctx.canonical.get("seller") or {}).get("gstin") or "")
    mem = _agent_mem_load(ctx, "hsn_classification", seller_gstin)
    hsn_rates = dict(mem.get("hsnRates") or {})

    # Apply remembered HSN->rate only when unambiguous (not when 0% + non-zero slabs intentionally share an HSN)
    meta = ctx.canonical.get("_meta") or {}
    slabs_detail = meta.get("summary_slabs_detail") or []
    slab_rates = {float(s.get("rate", 0.0)) for s in slabs_detail}
    mixed_zero_hsn = 0.0 in slab_rates and len(slab_rates) > 1

    repaired = 0
    if not mixed_zero_hsn and hsn_rates:
        for r in rows:
            h = re.sub(r"[^0-9]", "", str(r.get("hsnSac") or ""))
            if float(r.get("gstRate") or 0.0) == 0.0 and h in hsn_rates:
                r["gstRate"] = float(hsn_rates[h])
                repaired += 1

    if rows and not mixed_zero_hsn:
        new_map = {}
        for r in rows:
            h = re.sub(r"[^0-9]", "", str(r.get("hsnSac") or ""))
            rt = float(r.get("gstRate") or 0.0)
            if 4 <= len(h) <= 8 and rt > 0:
                new_map[h] = rt
        if new_map:
            ctx.learned_rules["hsn_classification"] = {"hsnRates": new_map}

    bus.publish("hsn_classification", "tax_summary_slab", "hsn_rates_ready", ctx.invoice_id, {"repaired": repaired}, ctx.pass_no)
    return {"hsnCount": sum(1 for r in rows if r.get("hsnSac")), "repairedFromMemory": repaired}


def _handle_tax_summary_slab(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    rows = ctx.canonical.get("rows") or []
    # Reconcile any row that has gstRate == 0 but positive tax (from a CorrectionDirective or partial OCR)
    cg_tot = float(ctx.canonical.get("cgstTotal") or 0.0)
    sg_tot = float(ctx.canonical.get("sgstTotal") or 0.0)
    ig_tot = float(ctx.canonical.get("igstTotal") or 0.0)

    if directive:
        for r in rows:
            tx = float(r.get("taxable") or 0.0)
            rt = float(r.get("gstRate") or 0.0)
            rtax = round2(float(r.get("cgst") or 0.0) + float(r.get("sgst") or 0.0) + float(r.get("igst") or 0.0))
            if rt == 0.0 and tx > 0 and rtax > 0:
                est = (rtax / tx) * 100.0
                for std in (3.0, 5.0, 12.0, 18.0, 28.0):
                    if abs(est - std) <= 0.6:
                        r["gstRate"] = std
                        break
            elif rt > 0 and tx > 0 and rtax == 0.0:
                if ig_tot > 0 and cg_tot == 0 and sg_tot == 0:
                    r["igst"] = round2(tx * rt / 100.0)
                    r["lineTotal"] = round2(tx + r["igst"])
                else:
                    half = round2(tx * rt / 200.0)
                    r["cgst"] = half
                    r["sgst"] = half
                    r["lineTotal"] = round2(tx + 2.0 * half)

    slabs = build_gst_slabs(rows)
    ctx.canonical["slabs"] = slabs
    bus.publish(
        "tax_summary_slab",
        "totals_words",
        "slab_totals",
        ctx.invoice_id,
        {
            "taxableTotal": float(ctx.canonical.get("taxableTotal") or 0.0),
            "cgstTotal": cg_tot,
            "sgstTotal": sg_tot,
            "igstTotal": ig_tot,
            "slabCount": len(slabs),
        },
        ctx.pass_no,
    )
    return {"slabCount": len(slabs), "slabs": [(s["gstRate"], s["taxable"]) for s in slabs]}


def _handle_totals_words(ctx: InvoiceWorkContext, bus: PeerBus, directive: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    qr_tot_msg = bus.latest_payload("totals_words", ctx.invoice_id, "qr_total")
    adj_msg = bus.latest_payload("totals_words", ctx.invoice_id, "adjustments")
    slab_msg = bus.latest_payload("totals_words", ctx.invoice_id, "slab_totals")

    plain = re.sub(r"<[^>]+>", " ", ctx.raw_ocr_text or "")
    words_val = extract_amount_in_words(plain)
    inv_tot = float(ctx.canonical.get("invoiceTotal") or 0.0)

    if qr_tot_msg.get("totInvVal", 0.0) > 0 and inv_tot <= 0:
        inv_tot = float(qr_tot_msg["totInvVal"])
        ctx.canonical["invoiceTotal"] = round2(inv_tot)

    if directive and (ctx.canonical.get("taxableTotal") or 0.0) > 0:
        tx = float(ctx.canonical.get("taxableTotal") or 0.0)
        tax = round2(
            float(ctx.canonical.get("cgstTotal") or 0.0)
            + float(ctx.canonical.get("sgstTotal") or 0.0)
            + float(ctx.canonical.get("igstTotal") or 0.0)
            + float(ctx.canonical.get("cessTotal") or 0.0)
        )
        cn = float(adj_msg.get("creditNoteTotal", ctx.canonical.get("creditNoteTotal") or 0.0))
        ro = float(adj_msg.get("roundOff", ctx.canonical.get("roundOff") or 0.0))
        expected = round2(tx + tax - cn + ro)
        if words_val and abs(words_val - expected) <= 0.15 and abs(inv_tot - expected) > 0.25:
            ctx.canonical["invoiceTotal"] = words_val
            inv_tot = words_val

    return {
        "invoiceTotal": round2(inv_tot),
        "amountInWords": round2(words_val) if words_val else 0.0,
        "slabTaxable": slab_msg.get("taxableTotal", 0.0),
    }


for _name, _fn in (
    ("qr_authority", _handle_qr_authority),
    ("supplier_identity", _handle_supplier_identity),
    ("buyer_direction", _handle_buyer_direction),
    ("invoice_header", _handle_invoice_header),
    ("multipage_continuity", _handle_multipage_continuity),
    ("discount_charges", _handle_discount_charges),
    ("line_items", _handle_line_items),
    ("hsn_classification", _handle_hsn_classification),
    ("tax_summary_slab", _handle_tax_summary_slab),
    ("totals_words", _handle_totals_words),
):
    REGISTRY.register(_name, _fn)


def persist_learned_agent_memories(ctx: InvoiceWorkContext) -> List[str]:
    """Persist per-agent learned rules only after AuditorAgent confirms `fully_balanced`."""
    saved: List[str] = []
    if not ctx.memory_db:
        return saved
    gstin = str((ctx.canonical.get("seller") or {}).get("gstin") or "").strip().upper()
    if not gstin:
        return saved
    for agent_name, rules in ctx.learned_rules.items():
        if rules and save_agent_memory(ctx.memory_db, agent_name, gstin, rules):
            saved.append(agent_name)
    return saved
