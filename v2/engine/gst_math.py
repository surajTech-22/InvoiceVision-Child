from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

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
    if len(s) != 15:
        return s, False, f"bad_len_{len(s)}"
    if is_valid_gstin(s):
        return s, True, "exact"

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


def audit_invoice_math(inv: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = inv.get("rows") or []
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
    for idx, r in enumerate(rows):
        tx = float(r.get("taxable") or 0.0)
        cg = float(r.get("cgst") or 0.0)
        sg = float(r.get("sgst") or 0.0)
        ig = float(r.get("igst") or 0.0)
        cs = float(r.get("cess") or 0.0)
        lt = float(r.get("lineTotal") or 0.0)
        rate = float(r.get("gstRate") or 0.0)
        issues = []
        if lt > 0 and abs((tx + cg + sg + ig + cs) - lt) > 0.25:
            issues.append(f"sum_mismatch({tx}+{cg}+{sg}+{ig}+{cs}!={lt})")
        qty = float(r.get("quantity") or 0.0)
        unit_rate = float(r.get("rate") or 0.0)
        disc = float(r.get("discount") or 0.0)
        if qty > 0 and unit_rate > 0 and tx > 0:
            exp_tx = round2((qty * unit_rate) - disc)
            if abs(exp_tx - tx) > max(1.50, tx * 0.01):
                issues.append(f"qty_rate_disc_mismatch(exp={exp_tx:.2f},got={tx:.2f})")
        if rate > 0 and tx > 0:
            if not is_supported_gst_rate(rate):
                issues.append(f"non_standard_gst_rate({rate})")
            exp_tax = tx * (rate / 100.0)
            got_tax = cg + sg + ig
            if abs(exp_tax - got_tax) > max(0.35, tx * 0.005):
                issues.append(f"gst_rate_mismatch(exp={exp_tax:.2f},got={got_tax:.2f})")
        if ig == 0 and (cg > 0 or sg > 0):
            if abs(cg - sg) > 0.25:
                issues.append(f"cgst_sgst_split_mismatch({cg}!={sg})")
            if rate == 0:
                issues.append("missing_gst_rate")
        if tx <= 0 and lt > 0:
            issues.append("missing_row_taxable")
        if issues:
            bad_rows.append({"row": idx + 1, "issues": issues})

    eff_tx = taxable_total if taxable_total > 0 else row_taxable_sum
    tax_sum = cgst_total + sgst_total + igst_total
    row_tax_sum = row_cgst_sum + row_sgst_sum + row_igst_sum
    eff_tax = tax_sum if tax_sum > 0 else row_tax_sum
    eff_cess = cess_total if cess_total > 0 else row_cess_sum

    taxable_match = len(rows) > 0 and eff_tx > 0 and abs(row_taxable_sum - eff_tx) <= max(0.50, 0.001 * eff_tx)
    tax_match = len(rows) > 0 and abs(row_tax_sum - eff_tax) <= max(0.50, 0.002 * max(eff_tax, 1.0))
    header_taxable_ok = (invoice_total <= 0) or (taxable_total > 0)

    expected_grand = eff_tx + eff_tax + eff_cess - credit_note + round_off
    grand_diff = abs(expected_grand - invoice_total) if invoice_total > 0 else 9999.0
    grand_balanced = invoice_total > 0 and (
        grand_diff <= 1.05 or abs((eff_tx + eff_tax + eff_cess - credit_note) - invoice_total) <= 1.05
    )

    seller_gstin = (inv.get("seller") or {}).get("gstin")
    buyer_gstin = (inv.get("buyer") or {}).get("gstin")
    seller_ok = is_valid_gstin(seller_gstin)
    buyer_ok = is_valid_gstin(buyer_gstin)

    return {
        "row_count": len(rows),
        "bad_rows": bad_rows,
        "row_taxable_sum": round2(row_taxable_sum),
        "row_tax_sum": round2(row_tax_sum),
        "row_total_sum": round2(row_total_sum),
        "taxable_match": taxable_match,
        "tax_match": tax_match,
        "grand_balanced": grand_balanced,
        "grand_diff": round2(grand_diff),
        "seller_gstin_valid": seller_ok,
        "buyer_gstin_valid": buyer_ok,
        "fully_balanced": (
            len(rows) > 0
            and len(bad_rows) == 0
            and taxable_match
            and tax_match
            and grand_balanced
            and header_taxable_ok
            and seller_ok
        ),
    }
