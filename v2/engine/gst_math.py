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
                # Repair entity char OCR confusion (e.g. 'Z'->'2', 'I'->'1') before mutating check char
                if cand_with_pan[12] in L2D:
                    cand_ent_fix = cand_with_pan[:12] + L2D[cand_with_pan[12]] + cand_with_pan[13:]
                    if is_valid_gstin(cand_ent_fix):
                        return cand_ent_fix, True, "pan_hint_entity_l2d"
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


PARTY_NOISE_PREFIX_RE = re.compile(
    r"^(?:page\s*(?:no\.?)?\s*\d*|print\s+copy|pan(?:\s+no)?|fssai(?:\s+(?:no|lic))?|essai(?:\s+lic)?|gst(?:\s*(?:no|num|number))?|gstin(?:/uin)?|gstn(?:\s+no)?|state(?:\s+name|\s+code)?|"
    r"phone|ph(?:\s+no)?|mob(?:ile)?|contact|email|e-?mail|tel\.?\s*/\s*email|cin|van|beat|order\s*(?:no|number)|customer\s+order|dse\s+name|"
    r"salesperson|vehicle(?:\s*(?:no|num|number))?|ud(?:ay|y)?am(?:\s*(?:no|num|number|reg))?|msme(?:\s*(?:no|num|number))?|khatha\s+(?:no|number)|pid|mkt|eway|e-?way|irn|tkn|ack\.?\s*(?:no|date)|e-?inv|from|to|buyer(?:\s*\(bill\s*to\))?|"
    r"sn\.?|sl\.?\s*no|sr\.?\s*no|product(?:\s+name)?|particulars|description\s+of\s+goods|item\s+name|hsn(?:/sac)?|qty|quantity|mrp|amount|"
    r"bill\s*to(?:\s+gstin)?|billed\s*to|ship\s*to(?:\s+gstin)?|shipping\s+(?:address|date)|supplier\s+address|registered\s+address|customer\s+(?:address|details)|"
    r"cust\.?\s*code|party\s+(?:mobile|gstin)|branch\s+name|channel|tax\s+type|place\s+of\s+(?:sale|supply)|mode\s+of\s+payment|"
    r"cn\s+(?:number|date)|sdp\s+id|number\s+of\s+totes|ids?\s+of\s+totes|scan\s+this\s+qr|"
    r"date|dated|inv(?:oice)?\s*(?:no|number|date|dt)|bill\s*(?:no|number|date|dt)|doc(?:ument)?\s*(?:no|number|date)|voucher\s*(?:no|number)|sm\s+name|rt\s+name|all\s+taxes\s+are|"
    r"gst\s+invoice(?:/cash)?|tax\s+invoice(?:\s*\(credit\))?|bill\s+of\s+supply|original(?:\s+for\s+recipient)?|"
    r"duplicate|triplicate|reverse\s+charge|for)(?:$|\b|[:.\s])",
    re.IGNORECASE,
)

ADDRESS_HINT_RE = re.compile(
    r"\b(?:main\b|cross|road|rd\b|street|st\b|yard|apmc|a\s*p\s*m\s*c|ayard|nagar|puram|phase|plot|industrial|layout|extension|ddpi|d\.?d\.?p\.?i|circle|enclave|survey|"
    r"ward\s+no|pin\s*code|near|beside|opp\.?|bengaluru|bangalore|tumkur|thumkur|tumakur|tumakuru|mysuru|mysore|karnataka|india|"
    r"k(?:ha|at|ath)a\s+no|bata?wadi|balawadi|mandipet|belagumba)\b",
    re.IGNORECASE,
)

BUSINESS_KEYWORD_RE = re.compile(
    r"\b(?:enterprises?|traders|trading|marketing|distributors|agencies|agro|foods|pvt\s+ltd|private\s+limited|llp|limited|ltd\.?|inc\.?|corp\.?|company|wholesale|retail|cash\s+and\s+carry|stores|industries)\b",
    re.IGNORECASE,
)

_SIGNATORY_NOISE_RE = re.compile(
    r"\b(?:authorised|authorized|signatory|signature|proprietor|partner|director|manager|receiver|recipient|duplicate|triplicate|original|tax\s+invoice)\b",
    re.IGNORECASE,
)


def _strip_party_md(s: str) -> str:
    s = re.sub(r"[*#`\\]+", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def clean_party_name_candidate(s: str) -> str:
    """Normalize and reject obvious noise/label/address-only party name strings."""
    s = _strip_party_md(s)
    s = re.sub(r"^\(\s*(?:registered\s+as\s+)?(.+?)\s*\)$", r"\1", s, flags=re.IGNORECASE)
    s = re.sub(
        r"^(?:party\s*name|customer\s*name|buyer\s*name|supplier\s*name|seller\s*name|company\s+known\s+as|formerly\s+known\s+as|registered\s+as|m/s\.?)\s*[:\-]?\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    m_to = re.match(r"^(?:to|from)\.?\s*[:\-]?\s+(.{3,})$", s, re.IGNORECASE)
    if m_to:
        s = m_to.group(1)
    s = re.sub(r"\s+\d{10}(?:\s+[A-Z])?\s*$", "", s)
    s = re.sub(r"\s+20\d{2}-20\d{2}\s*(?:\([^)]*\))?\s*$", "", s)
    s = s.strip(" :-|,")
    if len(s) < 3 or s.startswith("&") or s.lower() in ("address", "name & address"):
        return ""
    if PARTY_NOISE_PREFIX_RE.match(s):
        return ""
    if ADDRESS_HINT_RE.search(s) and not BUSINESS_KEYWORD_RE.search(s):
        return ""
    if re.fullmatch(r"[\d\W]+", s) or re.match(r"^[0-9]{6,}", s):
        return ""
    if len(re.findall(r"[A-Za-z]", s)) < 3:
        return ""
    return s[:120]


def is_suspicious_party_name(s: str) -> Tuple[bool, str]:
    """Return (is_suspicious, reason) for an extracted Seller/Buyer firm name."""
    raw = _strip_party_md(s).strip(" :-|,")
    if not raw:
        return True, "empty"
    if len(raw) < 3:
        return True, "too_short"
    if PARTY_NOISE_PREFIX_RE.match(raw):
        return True, "noise_label_prefix"
    if ADDRESS_HINT_RE.search(raw) and not BUSINESS_KEYWORD_RE.search(raw):
        return True, "address_or_city_only"
    if re.fullmatch(r"[\d\W]+", raw) or re.match(r"^[0-9]{6,}", raw):
        return True, "numeric_noise"
    if len(re.findall(r"[A-Za-z]", raw)) < 3:
        return True, "insufficient_letters"
    if re.fullmatch(r"(?:unknown|n/?a|nil|none|cash|self)", raw, re.IGNORECASE):
        return True, "placeholder"
    return False, ""


def _norm_party_tokens(s: str) -> List[str]:
    clean = re.sub(r"\b(?:m/s|pvt|private|ltd|limited|co|llp|and)\b", " ", (s or "").lower())
    return [t for t in re.findall(r"[a-z0-9]+", clean) if len(t) >= 2]


def _party_similarity(a: str, b: str) -> float:
    ta, tb = set(_norm_party_tokens(a)), set(_norm_party_tokens(b))
    if not ta or not tb:
        sa, sb = re.sub(r"[^a-z0-9]", "", (a or "").lower()), re.sub(r"[^a-z0-9]", "", (b or "").lower())
        if not sa or not sb:
            return 0.0
        return 1.0 if (sa in sb or sb in sa) else 0.0
    inter = len(ta & tb)
    return inter / max(1, min(len(ta), len(tb)))


def _html_to_logical_lines(raw_text: str) -> List[str]:
    if not raw_text:
        return []
    txt = re.sub(r"<br\s*/?>", "\n", raw_text, flags=re.IGNORECASE)
    txt = re.sub(r"</(?:tr|td|th|p|div|li|h\d)>", "\n", txt, flags=re.IGNORECASE)
    txt = re.sub(r"<[^>]+>", " ", txt)
    out: List[str] = []
    for ln in txt.splitlines():
        s = _strip_party_md(ln)
        if s:
            out.append(s)
    return out


def independent_cross_verify_invoice(
    inv: Dict[str, Any],
    raw_text: str = "",
    qr_einvoice: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Stage-1 Audit Agent independent extraction & cross-verification directly from raw_text.
    Independently extracts Seller/Buyer/Invoice#/Total anchors and checks party-name hygiene
    to catch label prefixes ('VEHICLE No.', 'UDAYAM NO'), city-only strings ('TUMAKUR'),
    party collisions, or mismatches even when GSTIN + math checksums balance.
    """
    seller_obj = inv.get("seller") or {}
    buyer_obj = inv.get("buyer") or {}
    seller_name = str(seller_obj.get("name") or "").strip()
    buyer_name = str(buyer_obj.get("name") or "").strip()
    seller_gstin = str(seller_obj.get("gstin") or "").strip().upper()
    buyer_gstin = str(buyer_obj.get("gstin") or "").strip().upper()
    inv_no = str(inv.get("invoiceNumber") or "").strip()
    inv_total = float(inv.get("invoiceTotal") or 0.0)

    has_raw = bool((raw_text or "").strip())
    lines = _html_to_logical_lines(raw_text) if has_raw else []
    tbl_split = len(lines)
    for idx, ln in enumerate(lines):
        if re.search(r"\b(?:hsn(?:/sac)?|particulars|description\s+of\s+goods|sl\.?\s*no|sr\.?\s*no)\b", ln, re.I):
            tbl_split = max(4, idx)
            break
    header_lines = lines[: min(len(lines), max(tbl_split, 28))]
    footer_lines = lines[max(0, len(lines) - 28) :]

    # Independent Seller extraction: (1) bottom "For <Firm>" signature, (2) top masthead before Buyer/Bill To
    ind_seller = ""
    sig_seller = ""
    for ln in reversed(footer_lines):
        m_sig = re.search(r"\bfor\s+([A-Za-z0-9&.,'\-\s]{3,80})$", ln, re.IGNORECASE)
        if m_sig:
            cand_raw = m_sig.group(1).strip()
            if not _SIGNATORY_NOISE_RE.search(cand_raw):
                cand = clean_party_name_candidate(cand_raw)
                if cand:
                    sig_seller = cand
                    break

    masthead_seller = ""
    for idx, ln in enumerate(header_lines[:15]):
        if re.search(r"\b(?:bill\s*to|billed\s*to|buyer|ship\s*to|sold\s*to|party\s*name)\b", ln, re.IGNORECASE):
            break
        cand = clean_party_name_candidate(ln)
        if cand and (BUSINESS_KEYWORD_RE.search(cand) or (idx <= 5 and len(cand.split()) >= 2)):
            masthead_seller = cand
            break
    ind_seller = sig_seller or masthead_seller
    if sig_seller and masthead_seller and _party_similarity(sig_seller, masthead_seller) >= 0.45:
        ind_seller = masthead_seller if len(masthead_seller) >= len(sig_seller) else sig_seller

    # Independent Buyer extraction: anchor lines around Bill To / Buyer / To
    ind_buyer = ""
    for idx, ln in enumerate(header_lines):
        m_b = re.match(
            r"^(?:bill\s*to|billed\s*to|buyer(?:\s*\(bill\s*to\))?|sold\s*to|party(?:\s*name)?|customer(?:\s*name)?|m/s\.?|to\.?)\s*[:.\-]?\s*(.*)$",
            ln,
            re.IGNORECASE,
        )
        if not m_b:
            continue
        rest = m_b.group(1).strip()
        if rest:
            cand = clean_party_name_candidate(rest)
            if cand and _party_similarity(cand, ind_seller) < 0.75:
                ind_buyer = cand
                break
        for off in range(1, 4):
            if idx + off < len(header_lines):
                cand = clean_party_name_candidate(header_lines[idx + off])
                if cand and _party_similarity(cand, ind_seller) < 0.75:
                    ind_buyer = cand
                    break
        if ind_buyer:
            break

    # Independent Invoice Number & Grand Total from raw OCR
    ind_inv_no = ""
    for ln in header_lines[:24]:
        m_inv = re.search(
            r"(?:invoice|inv\.?|bill|doc(?:ument)?)\s*(?:no\.?|num(?:ber)?|#)\s*[:.\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,28})\b",
            ln,
            re.IGNORECASE,
        )
        if m_inv and not re.search(r"\b(?:e-?way|order|vehicle|ack|irn)\b", m_inv.group(1), re.I):
            ind_inv_no = m_inv.group(1).strip()
            break

    ind_total = 0.0
    for ln in reversed(footer_lines):
        if re.search(r"\b(?:net\s*payable|grand\s*total|invoice\s*total|bill\s*amount|payable\s*amount)\b", ln, re.IGNORECASE):
            nums = re.findall(r"([0-9][0-9,]*\.\d{2}|[0-9][0-9,]{2,})", ln)
            if nums:
                try:
                    ind_total = float(nums[-1].replace(",", ""))
                    break
                except Exception:
                    pass

    suspect_fields: List[str] = []
    mismatches: List[str] = []
    cross_blocking: List[str] = []

    if seller_name:
        s_bad, s_why = is_suspicious_party_name(seller_name)
        if s_bad:
            suspect_fields.append("seller.name")
            msg = f"Seller name '{seller_name}' failed Audit hygiene ({s_why})."
            mismatches.append(msg)
            cross_blocking.append(msg)
    elif has_raw and (inv.get("rows") or []):
        suspect_fields.append("seller.name")
        msg = "Seller name missing despite OCR text present."
        mismatches.append(msg)
        cross_blocking.append(msg)

    if buyer_name:
        b_bad, b_why = is_suspicious_party_name(buyer_name)
        if b_bad:
            suspect_fields.append("buyer.name")
            msg = f"Buyer name '{buyer_name}' failed Audit hygiene ({b_why})."
            mismatches.append(msg)
            cross_blocking.append(msg)
    elif has_raw and is_valid_gstin(buyer_gstin) and ind_buyer:
        suspect_fields.append("buyer.name")
        mismatches.append(f"Buyer name missing while Audit independently found '{ind_buyer}'.")

    if seller_name and buyer_name and _party_similarity(seller_name, buyer_name) >= 0.85:
        suspect_fields.extend(["seller.name", "buyer.name"])
        msg = f"Seller and Buyer names collide ('{seller_name}' vs '{buyer_name}')."
        mismatches.append(msg)
        cross_blocking.append(msg)

    if is_valid_gstin(seller_gstin) and is_valid_gstin(buyer_gstin) and seller_gstin == buyer_gstin:
        suspect_fields.extend(["seller.gstin", "buyer.gstin"])
        msg = f"Seller and Buyer GSTIN are identical ({seller_gstin})."
        mismatches.append(msg)
        cross_blocking.append(msg)

    raw_flat = " ".join(lines).lower() if lines else ""
    if has_raw and seller_name and ind_seller:
        sim_s = _party_similarity(seller_name, ind_seller)
        s_toks = _norm_party_tokens(seller_name)
        grounded = bool(s_toks and sum(1 for t in s_toks if t in raw_flat) >= max(1, len(s_toks) // 2))
        if sim_s < 0.45 and (not grounded or BUSINESS_KEYWORD_RE.search(ind_seller)):
            if "seller.name" not in suspect_fields:
                suspect_fields.append("seller.name")
            mismatches.append(f"Seller name '{seller_name}' differs from Audit independent '{ind_seller}'.")

    if has_raw and buyer_name and ind_buyer:
        sim_b = _party_similarity(buyer_name, ind_buyer)
        b_toks = _norm_party_tokens(buyer_name)
        grounded_b = bool(b_toks and sum(1 for t in b_toks if t in raw_flat) >= max(1, len(b_toks) // 2))
        if sim_b < 0.45 and not grounded_b:
            if "buyer.name" not in suspect_fields:
                suspect_fields.append("buyer.name")
            mismatches.append(f"Buyer name '{buyer_name}' differs from Audit independent '{ind_buyer}'.")

    if has_raw and inv_no and ind_inv_no:
        n1 = re.sub(r"[^A-Z0-9]", "", inv_no.upper())
        n2 = re.sub(r"[^A-Z0-9]", "", ind_inv_no.upper())
        if n1 and n2 and n1 != n2 and n1 not in n2 and n2 not in n1:
            suspect_fields.append("invoiceNumber")
            mismatches.append(f"Invoice number '{inv_no}' differs from Audit independent '{ind_inv_no}'.")

    if ind_total > 0 and inv_total > 0 and abs(ind_total - inv_total) > 2.0:
        if not (qr_einvoice and float(qr_einvoice.get("TotInvVal") or 0.0) > 0 and abs(float(qr_einvoice["TotInvVal"]) - inv_total) <= 1.05):
            suspect_fields.append("invoiceTotal")
            mismatches.append(f"Audit footer total ({ind_total:.2f}) differs from extracted ({inv_total:.2f}).")

    dedup_suspects = list(dict.fromkeys(suspect_fields))
    return {
        "stage1Passed": len(cross_blocking) == 0 and len(mismatches) == 0,
        "sellerNameValid": "seller.name" not in dedup_suspects and bool(seller_name),
        "buyerNameValid": "buyer.name" not in dedup_suspects,
        "independentSellerName": ind_seller,
        "independentBuyerName": ind_buyer,
        "independentInvoiceNumber": ind_inv_no,
        "independentInvoiceTotal": round2(ind_total) if ind_total > 0 else 0.0,
        "suspectFields": dedup_suspects,
        "mismatches": mismatches,
        "crossBlocking": cross_blocking,
    }


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

    cross_verification = independent_cross_verify_invoice(inv, raw_text=raw_text, qr_einvoice=qr_einvoice)
    for c_msg in cross_verification.get("crossBlocking") or []:
        if c_msg not in blocking_issues:
            blocking_issues.append(c_msg)

    html_complete = not (truncated or (raw_text and (raw_text.lower().count("<table") > raw_text.lower().count("</table>") or raw_text.rstrip().endswith("<"))))
    words_match = True if not (amount_in_words and amount_in_words > 0 and invoice_total > 0) else abs(amount_in_words - invoice_total) <= 1.05
    fully_balanced_val = (
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
    )
    needs_ai_crosscheck = (
        not fully_balanced_val
        or not cross_verification.get("stage1Passed", True)
        or (bool(buyer_gstin) and not buyer_ok)
    )

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
        "cross_verification": cross_verification,
        "needs_ai_crosscheck": needs_ai_crosscheck,
        "fully_balanced": fully_balanced_val,
    }


# ---------------- Stage 4 Parallel 1-to-1 Category Audit Child Registry ----------------
AuditChildHandler = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
AUDIT_REGISTRY: Dict[str, AuditChildHandler] = {}


def _audit_child_supplier_identity(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    seller_obj = inv.get("seller") or {}
    s_gstin = seller_obj.get("gstin")
    s_name = str(seller_obj.get("name") or "").strip()
    ok = is_valid_gstin(s_gstin)
    cross = (meta_ctx.get("base_audit") or {}).get("cross_verification") or {}
    blocking: List[str] = [] if ok else ["Seller GSTIN checksum invalid or missing."]
    warnings: List[str] = []
    for m in cross.get("crossBlocking") or []:
        if "seller" in m.lower() and m not in blocking:
            blocking.append(m)
    for m in cross.get("mismatches") or []:
        if "seller" in m.lower() and m not in blocking and m not in warnings:
            warnings.append(m)
    passed = ok and not any("seller" in b.lower() for b in blocking)
    return {
        "passed": passed,
        "blocking": blocking,
        "warnings": warnings,
        "metrics": {
            "sellerGstin": s_gstin or "",
            "sellerName": s_name,
            "independentSellerName": str(cross.get("independentSellerName") or ""),
            "sellerNameValid": bool(cross.get("sellerNameValid", bool(s_name))),
            "valid": ok,
        },
    }


def _audit_child_buyer_direction(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    buyer_obj = inv.get("buyer") or {}
    b_gstin = buyer_obj.get("gstin")
    b_name = str(buyer_obj.get("name") or "").strip()
    ok = is_valid_gstin(b_gstin)
    cross = (meta_ctx.get("base_audit") or {}).get("cross_verification") or {}
    blocking: List[str] = []
    warnings: List[str] = [] if ok or not b_gstin else [f"Buyer GSTIN checksum invalid ({b_gstin})."]
    for m in cross.get("crossBlocking") or []:
        if "buyer" in m.lower() and m not in blocking:
            blocking.append(m)
    for m in cross.get("mismatches") or []:
        if "buyer" in m.lower() and m not in blocking and m not in warnings:
            warnings.append(m)
    return {
        "passed": len(blocking) == 0,
        "blocking": blocking,
        "warnings": warnings,
        "metrics": {
            "buyerGstin": b_gstin or "",
            "buyerName": b_name,
            "independentBuyerName": str(cross.get("independentBuyerName") or ""),
            "buyerNameValid": bool(cross.get("buyerNameValid", True)),
            "valid": ok,
        },
    }


def _audit_child_invoice_header(inv: Dict[str, Any], meta_ctx: Dict[str, Any]) -> Dict[str, Any]:
    inv_no = str(inv.get("invoiceNumber") or "").strip()
    inv_dt = str(inv.get("invoiceDate") or "").strip()
    cross = (meta_ctx.get("base_audit") or {}).get("cross_verification") or {}
    warnings: List[str] = [] if inv_no else ["Invoice number missing."]
    for m in cross.get("mismatches") or []:
        if "invoice number" in m.lower() and m not in warnings:
            warnings.append(m)
    return {
        "passed": bool(inv_no) and "invoiceNumber" not in (cross.get("suspectFields") or []),
        "blocking": [],
        "warnings": warnings,
        "metrics": {
            "invoiceNumber": inv_no,
            "independentInvoiceNumber": str(cross.get("independentInvoiceNumber") or ""),
            "invoiceDate": inv_dt,
        },
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
