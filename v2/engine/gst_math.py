from __future__ import annotations

import re
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

VALID_STATE_CODES = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "26", "27", "28", "29", "30", "31",
    "32", "33", "34", "35", "36", "37", "38", "97", "99",
}

SUPPORTED_GST_RATES = (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0, 40.0)

L2D = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}
D2L = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G", "4": "A"}
DIGIT_CONFUSIONS = {
    "3": ["8", "5", "2"], "8": ["3", "6", "0", "B"], "5": ["6", "3", "S"], "6": ["5", "8", "0"],
    "0": ["8", "6", "9"], "1": ["7", "4"], "7": ["1", "2"], "2": ["7", "3"], "4": ["9", "1"], "9": ["4", "0"],
}
LETTER_CONFUSIONS = {
    "I": ["L", "T", "1"], "L": ["I", "E"], "O": ["Q", "D", "0"], "B": ["R", "P", "E"],
    "E": ["F", "B", "L"], "F": ["E", "P"], "G": ["C", "6"], "C": ["G", "O"],
    "S": ["5", "8"], "Z": ["2", "7"], "V": ["U", "Y"], "U": ["V"], "K": ["X", "R"],
}


def compute_gstin_check_char(first14: str) -> str:
    total = 0
    for idx, ch in enumerate(first14):
        code = GSTIN_ALPHABET.index(ch)
        prod = code * (1 if idx % 2 == 0 else 2)
        total += (prod // 36) + (prod % 36)
    return GSTIN_ALPHABET[(36 - (total % 36)) % 36]


def is_valid_gstin(gstin: str | None) -> bool:
    if not gstin:
        return False
    s = re.sub(r"[^A-Za-z0-9]", "", gstin).upper()
    if len(s) != 15 or s[:2] not in VALID_STATE_CODES:
        return False
    if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", s):
        return False
    return compute_gstin_check_char(s[:14]) == s[14]


def repair_gstin(raw: str | None, pan_hints: List[str] | None = None) -> Tuple[str, bool, str]:
    """Repair common OCR confusions in a 15-char Indian GSTIN while verifying Mod-36 checksum."""
    if not raw:
        return "", False, "empty"
    s = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    if len(s) == 16:
        for del_i in range(15, -1, -1):
            sub15 = s[:del_i] + s[del_i + 1:]
            if is_valid_gstin(sub15):
                return sub15, True, f"len16_drop_{del_i}"
        for del_i in (15, 14, 13, 12, 11):
            sub15 = s[:del_i] + s[del_i + 1:]
            if not sub15.isdigit() and sum(1 for ch in sub15[2:7] if ch.isalpha()) >= 2:
                fixed15, ok15, why15 = repair_gstin(sub15, pan_hints=pan_hints)
                if ok15:
                    return fixed15, True, f"len16_drop_{del_i}_{why15}"
    if len(s) != 15:
        return s, False, f"bad_len_{len(s)}"
    if is_valid_gstin(s):
        return s, True, "exact"
    # Reject purely numeric 15-digit IDs (e.g. e-Invoice Ack No / phone / barcode) so D2L never fabricates fake GSTINs
    if s.isdigit() or sum(1 for ch in s[2:7] if ch.isalpha()) < 2:
        return s, False, "not_gstin_pattern"

    chars = list(s)
    for i in (0, 1, 7, 8, 9, 10):
        if chars[i] in L2D:
            chars[i] = L2D[chars[i]]
    for i in (2, 3, 4, 5, 6, 11):
        if chars[i] in D2L:
            chars[i] = D2L[chars[i]]
    if chars[13] in ("2", "7", "S"):
        chars[13] = "Z"

    struct_fixed = "".join(chars)
    if is_valid_gstin(struct_fixed):
        return struct_fixed, True, "structural_fix"

    # Try printed PAN hints (characters 2..12 of GSTIN == 10-char PAN)
    for pan in (pan_hints or []):
        p = re.sub(r"[^A-Za-z0-9]", "", pan or "").upper()
        if len(p) == 10 and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", p):
            # Only apply if PAN shares >= 7 characters with the OCR'd GSTIN PAN slice
            matches = sum(1 for a, b in zip(struct_fixed[2:12], p) if a == b)
            if matches >= 7:
                cand_with_pan = struct_fixed[:2] + p + struct_fixed[12:]
                if is_valid_gstin(cand_with_pan):
                    return cand_with_pan, True, "pan_hint_fix"
                # Also try check digit at pos 14 computed directly if first 14 chars are clean
                if re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z$", cand_with_pan[:14]):
                    cand_chk = cand_with_pan[:14] + compute_gstin_check_char(cand_with_pan[:14])
                    if is_valid_gstin(cand_chk):
                        return cand_chk, True, "pan_hint_check"

    for idx in range(15):
        alts: List[str] = []
        ch = struct_fixed[idx]
        if ch in L2D:
            alts.append(L2D[ch])
        if ch in D2L:
            alts.append(D2L[ch])
        if ch in DIGIT_CONFUSIONS:
            alts.extend(DIGIT_CONFUSIONS[ch])
        if ch in LETTER_CONFUSIONS:
            alts.extend(LETTER_CONFUSIONS[ch])
        for alt in alts:
            cand = list(struct_fixed)
            cand[idx] = alt
            cs = "".join(cand)
            if is_valid_gstin(cs):
                return cs, True, f"single_char_pos_{idx}"

    return struct_fixed, False, "invalid_checksum"


def round2(x: float) -> float:
    return round(float(x) + 1e-9, 2) if x >= 0 else round(float(x) - 1e-9, 2)


def is_supported_gst_rate(rate: float) -> bool:
    return any(abs(rate - r) <= 0.05 for r in SUPPORTED_GST_RATES)


def audit_invoice_math(
    inv: Dict[str, Any],
    raw_text: str = "",
    truncated: bool = False,
    amount_in_words: Optional[float] = None,
    qr_einvoice: Optional[Dict[str, Any]] = None,
    printed_total_found: Optional[bool] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = inv.get("rows") or []
    meta = inv.get("_meta") if isinstance(inv.get("_meta"), dict) else {}
    if not raw_text and isinstance(meta.get("raw_text"), str):
        raw_text = meta["raw_text"]
    if not truncated and meta.get("truncated"):
        truncated = True
    if amount_in_words is None and meta.get("amount_in_words"):
        amount_in_words = float(meta["amount_in_words"])
    if printed_total_found is None and "printed_total_found" in meta:
        printed_total_found = bool(meta["printed_total_found"])

    taxable_total = float(inv.get("taxableTotal") or 0.0)
    cgst_total = float(inv.get("cgstTotal") or 0.0)
    sgst_total = float(inv.get("sgstTotal") or 0.0)
    igst_total = float(inv.get("igstTotal") or 0.0)
    cess_total = float(inv.get("cessTotal") or 0.0)
    round_off = float(inv.get("roundOff") or 0.0)
    credit_note = float(inv.get("creditNoteTotal") or 0.0)
    invoice_total = float(inv.get("invoiceTotal") or 0.0)

    row_taxable_sum = sum(float(r.get("taxable") or 0.0) for r in rows)
    row_cgst_sum = sum(float(r.get("cgst") or 0.0) for r in rows)
    row_sgst_sum = sum(float(r.get("sgst") or 0.0) for r in rows)
    row_igst_sum = sum(float(r.get("igst") or 0.0) for r in rows)
    row_cess_sum = sum(float(r.get("cess") or 0.0) for r in rows)
    row_total_sum = sum(float(r.get("lineTotal") or 0.0) for r in rows)

    bad_rows = []
    row_warnings = []
    for idx, r in enumerate(rows):
        tx = float(r.get("taxable") or 0.0)
        cg = float(r.get("cgst") or 0.0)
        sg = float(r.get("sgst") or 0.0)
        ig = float(r.get("igst") or 0.0)
        cs = float(r.get("cess") or 0.0)
        lt = float(r.get("lineTotal") or 0.0)
        rate = float(r.get("gstRate") or 0.0)
        issues = []
        row_warns = []
        line_sum_ok = lt <= 0 or abs((tx + cg + sg + ig + cs) - lt) <= 0.25
        if not line_sum_ok:
            issues.append(f"sum_mismatch({tx}+{cg}+{sg}+{ig}+{cs}!={lt})")
        rate_math_ok = True
        if rate == 0 and (cg + sg + ig) > 0.05:
            issues.append(f"tax_on_zero_rate(tax={cg+sg+ig:.2f})")
            rate_math_ok = False
        if rate > 0 and tx > 0:
            if not is_supported_gst_rate(rate):
                issues.append(f"non_standard_gst_rate({rate})")
                rate_math_ok = False
            exp_tax = tx * (rate / 100.0)
            got_tax = cg + sg + ig
            if abs(exp_tax - got_tax) > max(0.35, tx * 0.005):
                issues.append(f"gst_rate_mismatch(exp={exp_tax:.2f},got={got_tax:.2f})")
                rate_math_ok = False
        if ig == 0 and (cg > 0 or sg > 0):
            if abs(cg - sg) > 0.005:
                issues.append(f"cgst_sgst_split_mismatch({cg}!={sg})")
                rate_math_ok = False
            if rate == 0:
                issues.append("missing_gst_rate")
                rate_math_ok = False
        if tx <= 0 and lt > 0:
            issues.append("missing_row_taxable")
            rate_math_ok = False
        qty = float(r.get("quantity") or 0.0)
        unit_rate = float(r.get("rate") or 0.0)
        disc = float(r.get("discount") or 0.0)
        if qty > 0 and unit_rate > 0 and tx > 0:
            exp_tx = round2((qty * unit_rate) - disc)
            is_inclusive_unit = (lt > 0 and rate > 0 and abs(exp_tx - lt) <= max(1.50, lt * 0.01))
            if abs(exp_tx - tx) > max(1.50, tx * 0.01) and not is_inclusive_unit:
                msg = f"qty_rate_disc_mismatch(exp={exp_tx:.2f},got={tx:.2f})"
                # If taxable+tax == lineTotal AND GST rate math holds, treat unit-rate difference as non-blocking warning
                if lt > 0 and line_sum_ok and rate_math_ok:
                    row_warns.append(msg)
                else:
                    issues.append(msg)
        if issues:
            bad_rows.append({"row": idx + 1, "issues": issues})
        if row_warns:
            row_warnings.append({"row": idx + 1, "warnings": row_warns})

    eff_tx = taxable_total if taxable_total > 0 else row_taxable_sum
    tax_sum = cgst_total + sgst_total + igst_total
    row_tax_sum = row_cgst_sum + row_sgst_sum + row_igst_sum
    eff_tax = tax_sum if tax_sum > 0 else row_tax_sum
    eff_cess = cess_total if cess_total > 0 else row_cess_sum

    taxable_match = len(rows) > 0 and eff_tx > 0 and abs(row_taxable_sum - eff_tx) <= max(0.50, 0.001 * eff_tx)
    cgst_match = len(rows) > 0 and abs(row_cgst_sum - cgst_total) <= max(0.50, 0.002 * max(cgst_total, 1.0)) if cgst_total > 0 or row_cgst_sum > 0 else True
    sgst_match = len(rows) > 0 and abs(row_sgst_sum - sgst_total) <= max(0.50, 0.002 * max(sgst_total, 1.0)) if sgst_total > 0 or row_sgst_sum > 0 else True
    igst_match = len(rows) > 0 and abs(row_igst_sum - igst_total) <= max(0.50, 0.002 * max(igst_total, 1.0)) if igst_total > 0 or row_igst_sum > 0 else True
    tax_match = len(rows) > 0 and abs(row_tax_sum - eff_tax) <= max(0.50, 0.002 * max(eff_tax, 1.0)) and cgst_match and sgst_match and igst_match

    slabs = inv.get("gstSlabs") or []
    slab_match = True
    if slabs and taxable_total > 0:
        slab_tx_sum = sum(float(s.get("taxable") or 0.0) for s in slabs)
        slab_tax_sum = sum(float(s.get("cgst") or 0.0) + float(s.get("sgst") or 0.0) + float(s.get("igst") or 0.0) for s in slabs)
        if abs(slab_tx_sum - taxable_total) > max(0.50, 0.001 * taxable_total):
            slab_match = False
        if abs(slab_tax_sum - tax_sum) > max(0.50, 0.002 * max(tax_sum, 1.0)):
            slab_match = False

    header_taxable_ok = (invoice_total <= 0) or (taxable_total > 0)
    header_cgst_sgst_ok = (igst_total > 0) or (abs(cgst_total - sgst_total) <= 0.005)

    expected_grand = eff_tx + eff_tax + eff_cess - credit_note + round_off
    grand_diff = abs(expected_grand - invoice_total) if invoice_total > 0 else 9999.0
    grand_balanced = invoice_total > 0 and (
        grand_diff <= 1.05 or abs((eff_tx + eff_tax + eff_cess - credit_note) - invoice_total) <= 1.05
    )

    blocking_issues: List[str] = []
    if truncated or (raw_text and (raw_text.lower().count("<table") > raw_text.lower().count("</table>") or raw_text.rstrip().endswith("<"))):
        blocking_issues.append("OCR output was truncated mid-table before end of invoice.")
    if not taxable_match and rows:
        blocking_issues.append(f"Row taxable sum ({row_taxable_sum:.2f}) mismatches header taxable total ({eff_tx:.2f}).")
    if not tax_match and rows:
        blocking_issues.append(f"Row tax sum ({row_tax_sum:.2f}) mismatches header tax total ({eff_tax:.2f}).")
    if not slab_match:
        blocking_issues.append("GST slab totals do not reconcile to invoice header taxable/tax totals.")
    if not grand_balanced:
        blocking_issues.append(f"Taxable + Tax - CreditNote + RoundOff ({expected_grand:.2f}) != Invoice Total ({invoice_total:.2f}).")
    if amount_in_words and amount_in_words > 0 and invoice_total > 0 and abs(amount_in_words - invoice_total) > 1.05:
        blocking_issues.append(f"Printed Amount-in-Words ({amount_in_words:.2f}) mismatches extracted Invoice Total ({invoice_total:.2f}).")
    if printed_total_found is False and invoice_total > 0 and not amount_in_words and not (qr_einvoice and qr_einvoice.get("TotInvVal")):
        blocking_issues.append("Printed grand total was not found directly; total was inferred only.")
    if qr_einvoice:
        qtot = float(qr_einvoice.get("TotInvVal") or 0.0)
        if qtot > 0 and invoice_total > 0 and abs(qtot - invoice_total) > 1.05:
            blocking_issues.append(f"e-Invoice QR total ({qtot:.2f}) mismatches Invoice Total ({invoice_total:.2f}).")

    seller_gstin = (inv.get("seller") or {}).get("gstin")
    buyer_gstin = (inv.get("buyer") or {}).get("gstin")
    seller_ok = is_valid_gstin(seller_gstin)
    buyer_ok = is_valid_gstin(buyer_gstin)
    if not seller_ok:
        blocking_issues.append("Seller GSTIN checksum invalid or missing.")

    html_complete = not (truncated or (raw_text and (raw_text.lower().count("<table") > raw_text.lower().count("</table>") or raw_text.rstrip().endswith("<"))))
    words_match = True if not (amount_in_words and amount_in_words > 0 and invoice_total > 0) else abs(amount_in_words - invoice_total) <= 1.05

    return {
        "row_count": len(rows),
        "bad_rows": bad_rows,
        "row_warnings": row_warnings,
        "row_taxable_sum": round2(row_taxable_sum),
        "row_cgst_sum": round2(row_cgst_sum),
        "row_sgst_sum": round2(row_sgst_sum),
        "row_igst_sum": round2(row_igst_sum),
        "row_tax_sum": round2(row_tax_sum),
        "row_total_sum": round2(row_total_sum),
        "taxable_match": taxable_match,
        "tax_match": tax_match,
        "slab_match": slab_match,
        "grand_balanced": grand_balanced,
        "grand_diff": round2(grand_diff),
        "words_match": words_match,
        "amount_in_words": round2(amount_in_words) if amount_in_words else 0.0,
        "html_complete": html_complete,
        "truncated": not html_complete,
        "blocking_issues": blocking_issues,
        "seller_gstin_valid": seller_ok,
        "buyer_gstin_valid": buyer_ok,
        "fully_balanced": (
            len(rows) > 0
            and len(bad_rows) == 0
            and taxable_match
            and tax_match
            and slab_match
            and grand_balanced
            and words_match
            and html_complete
            and len(blocking_issues) == 0
            and header_taxable_ok
            and header_cgst_sgst_ok
            and seller_ok
        ),
    }


# ---------------- Stage 4 Parallel 1-to-1 Category Audit Child Registry ----------------
AuditChildHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
AUDIT_REGISTRY: Dict[str, AuditChildHandler] = {}


def _audit_child_supplier_identity(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    s_gstin = (inv.get("seller") or {}).get("gstin")
    ok = is_valid_gstin(s_gstin)
    return {
        "passed": ok,
        "blocking": ([] if ok else ["Seller GSTIN checksum invalid or missing."]),
        "warnings": [],
        "metrics": {"sellerGstin": s_gstin or "", "valid": ok},
    }


def _audit_child_buyer_direction(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    b_gstin = (inv.get("buyer") or {}).get("gstin")
    ok = is_valid_gstin(b_gstin)
    return {
        "passed": True,  # Buyer GSTIN may be unregistered B2C, tracked as advisory metric unless invalid format
        "blocking": [],
        "warnings": ([] if ok or not b_gstin else [f"Buyer GSTIN checksum invalid ({b_gstin})."]),
        "metrics": {"buyerGstin": b_gstin or "", "valid": ok},
    }


def _audit_child_invoice_header(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    inv_no = str(inv.get("invoiceNumber") or "").strip()
    inv_dt = str(inv.get("invoiceDate") or "").strip()
    return {
        "passed": bool(inv_no),
        "blocking": [],
        "warnings": ([] if inv_no else ["Invoice number missing."]),
        "metrics": {"invoiceNumber": inv_no, "invoiceDate": inv_dt},
    }


def _audit_child_qr_authority(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    qr_e = meta_ctx.get("qr_einvoice") or {}
    inv_tot = float(inv.get("invoiceTotal") or 0.0)
    blocking: List[str] = []
    if qr_e:
        qtot = float(qr_e.get("TotInvVal") or 0.0)
        if qtot > 0 and inv_tot > 0 and abs(qtot - inv_tot) > 1.05:
            blocking.append(f"e-Invoice QR total ({qtot:.2f}) mismatches Invoice Total ({inv_tot:.2f}).")
    return {
        "passed": len(blocking) == 0,
        "blocking": blocking,
        "warnings": [],
        "metrics": {"hasQr": bool(qr_e)},
    }


def _audit_child_multipage_continuity(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    raw_text = str(meta_ctx.get("raw_text") or "")
    trunc = bool(meta_ctx.get("truncated")) or bool(
        raw_text and (raw_text.lower().count("<table") > raw_text.lower().count("</table>") or raw_text.rstrip().endswith("<"))
    )
    return {
        "passed": not trunc,
        "blocking": (["OCR output was truncated mid-table before end of invoice."] if trunc else []),
        "warnings": [],
        "metrics": {"htmlComplete": not trunc},
    }


def _audit_child_line_items(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    base = meta_ctx.get("base_audit") or {}
    blocking: List[str] = []
    if base.get("row_count", 0) > 0 and not base.get("taxable_match"):
        tx_sum = float(base.get("row_taxable_sum") or 0.0)
        eff_tx = float(inv.get("taxableTotal") or tx_sum)
        blocking.append(f"Row taxable sum ({tx_sum:.2f}) mismatches header taxable total ({eff_tx:.2f}).")
    return {
        "passed": len(blocking) == 0 and len(base.get("bad_rows") or []) == 0 and base.get("row_count", 0) > 0,
        "blocking": blocking,
        "warnings": [w for w in (base.get("row_warnings") or [])],
        "metrics": {"rowCount": base.get("row_count", 0), "badRowCount": len(base.get("bad_rows") or [])},
    }


def _audit_child_hsn_classification(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    rows = inv.get("rows") or []
    rate_issues = [
        idx + 1
        for idx, r in enumerate(rows)
        if float(r.get("gstRate") or 0.0) > 0 and not is_supported_gst_rate(float(r.get("gstRate") or 0.0))
    ]
    return {
        "passed": len(rate_issues) == 0,
        "blocking": [],
        "warnings": ([f"Rows with non-standard GST rate: {rate_issues}"] if rate_issues else []),
        "metrics": {"nonStandardRows": len(rate_issues)},
    }


def _audit_child_discount_charges(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    ro = float(inv.get("roundOff") or 0.0)
    cn = float(inv.get("creditNoteTotal") or 0.0)
    return {
        "passed": abs(ro) <= 5.0,
        "blocking": [],
        "warnings": ([] if abs(ro) <= 5.0 else [f"Large round-off ({ro:.2f})."]),
        "metrics": {"roundOff": ro, "creditNoteTotal": cn},
    }


def _audit_child_tax_summary_slab(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    base = meta_ctx.get("base_audit") or {}
    blocking: List[str] = []
    if base.get("row_count", 0) > 0 and not base.get("tax_match"):
        rt = float(base.get("row_tax_sum") or 0.0)
        ht = float(inv.get("cgstTotal") or 0.0) + float(inv.get("sgstTotal") or 0.0) + float(inv.get("igstTotal") or 0.0)
        blocking.append(f"Row tax sum ({rt:.2f}) mismatches header tax total ({(ht if ht > 0 else rt):.2f}).")
    if not base.get("slab_match", True):
        blocking.append("GST slab totals do not reconcile to invoice header taxable/tax totals.")
    return {
        "passed": len(blocking) == 0,
        "blocking": blocking,
        "warnings": [],
        "metrics": {"taxMatch": bool(base.get("tax_match")), "slabMatch": bool(base.get("slab_match"))},
    }


def _audit_child_totals_words(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    base = meta_ctx.get("base_audit") or {}
    inv_tot = float(inv.get("invoiceTotal") or 0.0)
    tx = float(inv.get("taxableTotal") or base.get("row_taxable_sum") or 0.0)
    ht = float(inv.get("cgstTotal") or 0.0) + float(inv.get("sgstTotal") or 0.0) + float(inv.get("igstTotal") or 0.0)
    eff_tax = ht if ht > 0 else float(base.get("row_tax_sum") or 0.0)
    cess = float(inv.get("cessTotal") or 0.0)
    ro = float(inv.get("roundOff") or 0.0)
    cn = float(inv.get("creditNoteTotal") or 0.0)
    expected_grand = tx + eff_tax + cess - cn + ro
    blocking: List[str] = []
    if not base.get("grand_balanced"):
        blocking.append(f"Taxable + Tax - CreditNote + RoundOff ({expected_grand:.2f}) != Invoice Total ({inv_tot:.2f}).")
    words_val = float(base.get("amount_in_words") or 0.0)
    if words_val > 0 and inv_tot > 0 and abs(words_val - inv_tot) > 1.05:
        blocking.append(f"Printed Amount-in-Words ({words_val:.2f}) mismatches extracted Invoice Total ({inv_tot:.2f}).")
    printed_found = meta_ctx.get("printed_total_found")
    qr_e = meta_ctx.get("qr_einvoice") or {}
    if printed_found is False and inv_tot > 0 and not words_val and not qr_e.get("TotInvVal"):
        blocking.append("Printed grand total was not found directly; total was inferred only.")
    return {
        "passed": len(blocking) == 0,
        "blocking": blocking,
        "warnings": [],
        "metrics": {"invoiceTotal": inv_tot, "amountInWords": words_val, "grandBalanced": bool(base.get("grand_balanced"))},
    }


def _audit_child_generic(cat_name: str, inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"passed": True, "blocking": [], "warnings": [], "metrics": {"category": cat_name, "mode": "generic"}}


for _acat, _afn in (
    ("supplier_identity", _audit_child_supplier_identity),
    ("buyer_direction", _audit_child_buyer_direction),
    ("invoice_header", _audit_child_invoice_header),
    ("qr_authority", _audit_child_qr_authority),
    ("multipage_continuity", _audit_child_multipage_continuity),
    ("line_items", _audit_child_line_items),
    ("hsn_classification", _audit_child_hsn_classification),
    ("discount_charges", _audit_child_discount_charges),
    ("tax_summary_slab", _audit_child_tax_summary_slab),
    ("totals_words", _audit_child_totals_words),
):
    AUDIT_REGISTRY[_acat] = _afn


def run_parallel_category_audits(
    inv: Dict[str, Any],
    categories: List[str],
    pool: ThreadPoolExecutor,
    bus: Any = None,
    invoice_id: str = "",
    pass_no: int = 1,
    qr_einvoice: Optional[Dict[str, Any]] = None,
    truncated: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Spawn N parallel Stage-4 Audit Child Agents matching 1:1 with the N Stage-3 category sub-agents."""
    meta_map = inv.get("_meta") if isinstance(inv.get("_meta"), dict) else {}
    raw_text = str(meta_map.get("raw_text") or "")
    base_audit = audit_invoice_math(inv, raw_text=raw_text, truncated=truncated, qr_einvoice=qr_einvoice)
    meta_ctx = {
        "raw_text": raw_text,
        "truncated": bool(truncated or base_audit.get("truncated")),
        "qr_einvoice": qr_einvoice or {},
        "printed_total_found": meta_map.get("printed_total_found"),
        "base_audit": base_audit,
    }

    target_cats = list(categories) if categories else ["supplier_identity", "line_items", "totals_words"]

    def _exec_child(cat_name: str) -> Dict[str, Any]:
        t0 = time.perf_counter()
        fn = AUDIT_REGISTRY.get(cat_name)
        res = fn(inv, meta_ctx) if fn is not None else _audit_child_generic(cat_name, inv, meta_ctx)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        child_rec = {
            "agentName": f"audit_{cat_name}",
            "category": cat_name,
            "passed": bool(res.get("passed", True)),
            "blocking": list(res.get("blocking") or []),
            "warnings": list(res.get("warnings") or []),
            "metrics": dict(res.get("metrics") or {}),
            "elapsedMs": elapsed_ms,
        }
        if bus is not None and invoice_id:
            bus.publish(
                f"audit_{cat_name}",
                "auditor_coordinator",
                "audit_finding",
                invoice_id,
                {"category": cat_name, "passed": child_rec["passed"], "blockingCount": len(child_rec["blocking"])},
                pass_no=pass_no,
            )
        return child_rec

    futures: Dict[str, Future] = {cat: pool.submit(_exec_child, cat) for cat in target_cats}
    child_results: List[Dict[str, Any]] = []
    for cat in target_cats:
        child_results.append(futures[cat].result())

    if truncated and not base_audit.get("truncated"):
        base_audit["truncated"] = True
        base_audit["html_complete"] = False
        if "OCR output was truncated mid-table before end of invoice." not in (base_audit.get("blocking_issues") or []):
            base_audit.setdefault("blocking_issues", []).append("OCR output was truncated mid-table before end of invoice.")
        base_audit["fully_balanced"] = False

    base_audit["auditAgentCount"] = len(child_results)
    base_audit["categoryAgentCount"] = len(target_cats)
    base_audit["perAgentAudit"] = child_results
    return base_audit, child_results
