from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from gst_math import audit_invoice_math, is_valid_gstin, repair_gstin, round2

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "sept": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _equal_local_tax_half(taxable: float, gst_rate: float, combined_tax: float = 0.0) -> float:
    """Compute equal per-side CGST/SGST without 1-paisa asymmetry."""
    if taxable > 0.0 and gst_rate > 0.0:
        by_rate = round2(taxable * gst_rate / 200.0)
        if combined_tax <= 0.0 or abs(2.0 * by_rate - combined_tax) <= 0.15:
            return by_rate
    return round2(combined_tax / 2.0) if combined_tax > 0.0 else 0.0


def clean_num(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    neg = False
    if "(-)" in s or s.startswith("-") or s.endswith("-"):
        neg = True
    s = s.replace("₹", "").replace("Rs.", "").replace("Rs", "").replace("INR", "").strip()
    s = re.sub(r",(\d{2})(?!\d)", r".\1", s)
    s = s.replace(",", "")
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return 0.0
    num = float(m.group(0))
    if neg and num > 0:
        num = -num
    return num


def parse_nums_in_cell(text: str) -> List[float]:
    if not text:
        return []
    s = re.sub(r",(\d{2})(?!\d)", r".\1", text).replace(",", "")
    return [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", s)]


def normalize_date(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = raw.strip()
    m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})[-\s/]([A-Za-z]{3,9})[-\s/](\d{2,4})", s)
    if m:
        d = int(m.group(1))
        mo = MONTHS.get(m.group(2).lower()[:4]) or MONTHS.get(m.group(2).lower()[:3])
        y = int(m.group(3))
        if y < 100:
            y += 2000
        if mo:
            return f"{y:04d}-{mo}-{d:02d}"
    return s


def find_gstins_in_text(text: str, extra_candidates: List[str] | None = None) -> List[str]:
    if not text:
        return []
    pan_hints = re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text.upper())
    raw_cands = re.findall(r"\b[0-9OQD]{2}[A-Z0-9]{10}[0-9A-Z][Z2S7][0-9A-Z]\b", text.upper())
    # Also catch 16-char OCR insertion artifacts near valid PAN hints (e.g. "29AAKPTD6049LJZD" with PAN "AAKPD6049L")
    for c16 in re.findall(r"\b[0-9OQD]{2}[A-Z0-9]{14}\b", text.upper()):
        norm16 = re.sub(r"[^A-Z0-9]", "", c16)
        for drop_idx in range(2, 12):
            c15 = norm16[:drop_idx] + norm16[drop_idx + 1:]
            if any(sum(1 for a, b in zip(c15[2:12], p) if a == b) >= 9 for p in pan_hints):
                raw_cands.append(c15)
                break
    valid_extras = [re.sub(r"[^A-Za-z0-9]", "", x).upper() for x in (extra_candidates or []) if x and is_valid_gstin(x)]
    valid_list: List[str] = []
    seen = set()
    for c in raw_cands:
        norm_c = re.sub(r"[^A-Za-z0-9]", "", c).upper()
        matched_extra = ""
        for ex in valid_extras:
            if len(norm_c) == 15 and sum(1 for a, b in zip(norm_c, ex) if a == b) >= 12:
                matched_extra = ex
                break
        if matched_extra:
            key = matched_extra
        else:
            fixed, ok, _ = repair_gstin(c, pan_hints=pan_hints)
            # Prefer entity digit '1' over OCR 'J'/'I' if valid check char matches printed last char
            if len(norm_c) == 15 and pan_hints and norm_c[12] in ("J", "I", "L", "T") and norm_c[13] in ("Z", "2", "7", "S"):
                for p in pan_hints:
                    if sum(1 for a, b in zip(norm_c[2:12], p) if a == b) >= 8:
                        cand_e1 = f"{norm_c[:2]}{p}1Z{norm_c[14]}"
                        f1, ok1, _ = repair_gstin(cand_e1, pan_hints=[p])
                        if ok1:
                            fixed, ok = f1, True
                            break
            if not ok and len(norm_c) == 15 and pan_hints:
                for p in pan_hints:
                    if sum(1 for a, b in zip(norm_c[2:12], p) if a == b) >= 8:
                        for ent in "123456789ABCDEF":
                            cand_ent = f"{norm_c[:2]}{p}{ent}Z{norm_c[14]}"
                            f2, ok2, _ = repair_gstin(cand_ent, pan_hints=[p])
                            if ok2:
                                fixed, ok = f2, True
                                break
                        if ok:
                            break
            key = fixed if ok else c
        if key not in seen:
            seen.add(key)
            valid_list.append(key)
    return valid_list


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = s[start:end + 1]
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            obj = json.loads(attempt)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _html_tables_to_matrices(html_text: str) -> List[List[List[str]]]:
    soup = BeautifulSoup(html_text, "lxml")
    tables = []
    for tbl in soup.find_all("table"):
        rows_mat = []
        for tr in tbl.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                txt = " ".join(cell.get_text(" ", strip=True).split())
                colspan = int(cell.get("colspan") or 1)
                cells.append(txt)
                for _ in range(max(0, colspan - 1)):
                    cells.append("")
            if any(cells):
                rows_mat.append(cells)
        if rows_mat:
            tables.append(rows_mat)
    return tables


def _markdown_tables_to_matrices(text: str) -> List[List[List[str]]]:
    tables = []
    cur = []
    pending_th_hdr: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if "<th>" in s.lower() and "|" not in s:
            m = re.search(r"<th>(.*?)</th>", s, re.IGNORECASE)
            if m:
                pending_th_hdr.append(m.group(1).strip())
            continue
        if "<th>" in s.lower() and "|" in s:
            part = re.sub(r"</?th>", " | ", s, flags=re.IGNORECASE)
            parts = [p.strip() for p in part.split("|") if p.strip()]
            pending_th_hdr.extend(parts)
            continue
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 3:
            if re.match(r"^\|[\s:\-|]+\|$", s):
                if not cur and pending_th_hdr:
                    cur.append(list(pending_th_hdr))
                    pending_th_hdr.clear()
                continue
            parts = [" ".join(c.strip().split()) for c in s.strip("|").split("|")]
            cur.append(parts)
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
            if s and "<" not in s:
                pending_th_hdr.clear()
    if len(cur) >= 2:
        tables.append(cur)
    return tables


def _otsl_tables_to_matrices(text: str) -> List[List[List[str]]]:
    if "<fcel>" not in text and "<nl>" not in text:
        return []
    tables: List[List[List[str]]] = []
    cur_rows: List[List[str]] = []
    for raw_line in text.split("<nl>"):
        if "<fcel>" not in raw_line and "<ecel>" not in raw_line:
            if len(cur_rows) >= 2:
                tables.append(cur_rows)
            cur_rows = []
            continue
        first_idx = min(
            [i for i in (raw_line.find("<fcel>"), raw_line.find("<ecel>"), raw_line.find("<lcel>"), raw_line.find("<ucel>"), raw_line.find("<xcel>")) if i != -1],
            default=-1,
        )
        if first_idx > 0:
            prose = raw_line[:first_idx].strip()
            if prose and len(cur_rows) >= 2:
                tables.append(cur_rows)
                cur_rows = []
            raw_line = raw_line[first_idx:]
        tokens = re.split(r"(<fcel>|<ecel>|<lcel>|<ucel>|<xcel>)", raw_line)
        cells: List[str] = []
        i = 1
        while i < len(tokens):
            tag = tokens[i]
            val = " ".join((tokens[i + 1] if i + 1 < len(tokens) else "").split())
            cells.append(val if tag == "<fcel>" else "")
            i += 2
        if any(cells):
            cur_rows.append(cells)
    if len(cur_rows) >= 2:
        tables.append(cur_rows)
    return tables


def _is_item_table_header(header_row: List[str]) -> bool:
    joined = " ".join(header_row).lower()
    has_desc = any(k in joined for k in ("product", "item", "description", "particulars", "goods", "service"))
    has_hsn = "hsn" in joined or "sac" in joined
    has_qty_or_rate = any(k in joined for k in ("qty", "units", "pcs", "rate", "quantity", "shipped", "taxable", "amount"))
    is_tax_summary = (
        "cgst 2.5" in joined
        or ("taxable value" in joined and "central gst" in joined)
        or ("cgst %" in joined and "cgst amount" in joined and not any(k in joined for k in ("qty", "quantity", "rate", "product", "item", "particulars", "description")))
    )
    is_scheme_table = ("initiative name" in joined or "credit note number" in joined)
    if is_scheme_table or is_tax_summary:
        return False
    return (has_hsn and (has_desc or has_qty_or_rate)) or (has_desc and has_qty_or_rate)


def _is_tax_summary_table(rows_mat: List[List[str]]) -> bool:
    joined_hdr = " ".join(" ".join(r) for r in rows_mat[:2]).lower()
    joined = " ".join(" ".join(r) for r in rows_mat[:3]).lower()
    if "hsn" in joined_hdr and ("central gst" in joined_hdr or "taxable value" in joined_hdr) and "rate" in joined_hdr and not any(k in joined_hdr for k in ("qty", "quantity", "sku", "mrp", "gross")):
        return True
    if "cgst %" in joined_hdr and "cgst amount" in joined_hdr and not any(k in joined_hdr for k in ("qty", "quantity", "rate", "product", "item", "particulars", "description")):
        return True
    if "particulars" in joined and ("cgst 2.5" in joined or "cgst 0." in joined or "net payable" in joined):
        return True
    if ("gst%" in joined and ("taxable rs" in joined or "sale val" in joined)) or ("class" in joined and "taxable" in joined and "total gst" in joined):
        return True
    if ("taxable" in joined and ("cgst/ igst" in joined or "cgst/igst" in joined or "tot cgst" in joined)
            and not any(k in joined for k in ("product", "item", "qty", "quantity", "pcs", "hsn"))):
        return True
    return False


def _try_parse_dual_stacked_itc_table(mat_norm: List[List[str]], data_start: int) -> Optional[List[Dict[str, Any]]]:
    hdr_joined = " ".join(c.lower() for c in mat_norm[0])
    hdr_two_rows = " ".join(c.lower() for r in mat_norm[:2] for c in r)
    is_single_merged_hdr = "uom taxable amt" in hdr_joined or ("rate cgst amt" in hdr_joined and "grossamt" in hdr_joined)
    is_two_row_split_hdr = "grossamt" in hdr_two_rows and "tot.tax" in hdr_two_rows and "taxable amt" in hdr_two_rows and "cgst" in hdr_two_rows
    if not (is_single_merged_hdr or is_two_row_split_hdr):
        return None

    h0 = [c.lower() for c in mat_norm[0]]
    h1 = [c.lower() for c in mat_norm[1]] if is_two_row_split_hdr and len(mat_norm) > 1 else []
    desc_col = next((idx for idx, c in enumerate(h0) if "item name" in c), 1)
    uom_col = next((idx for idx, c in enumerate(h0) if "uom" in c), 2 if is_two_row_split_hdr else 3)
    rate_col = next((idx for idx, c in enumerate(h0) if "rate" in c), 4 if is_two_row_split_hdr else 5)
    qty_col = next((idx for idx, c in enumerate(h0) if c.strip() == "qty"), 5 if is_two_row_split_hdr else 6)
    gross_col = next((idx for idx, c in enumerate(h0) if "grossamt" in c), 6 if is_two_row_split_hdr else 7)
    disc_cols = [idx for idx, c in enumerate(h0) if "disc.amt" in c or "other disc" in c] or ([9, 10] if is_two_row_split_hdr else [10, 11])
    tax_col = next((idx for idx, c in enumerate(h0) if "tot.tax" in c), 11 if is_two_row_split_hdr else 12)
    amt_col = next((idx for idx, c in enumerate(h0) if "amount" in c), len(h0) - 1)

    r2_tx_col = next((idx for idx, c in enumerate(h1) if "taxable" in c), -1)
    r2_cgp_col = next((idx for idx, c in enumerate(h1) if "cgst" in c and "%" in c), -1)
    r2_cga_col = next((idx for idx, c in enumerate(h1) if "cgst" in c and "amt" in c), -1)
    r2_sgp_col = next((idx for idx, c in enumerate(h1) if "sgst" in c and "%" in c), -1)
    r2_sga_col = next((idx for idx, c in enumerate(h1) if "sgst" in c and "amt" in c), -1)

    out: List[Dict[str, Any]] = []
    i = data_start
    while i < len(mat_norm):
        r1 = mat_norm[i]
        r2 = mat_norm[i + 1] if i + 1 < len(mat_norm) else []
        is_paired = len(r1) >= 12 and len(r2) >= 8 and not r2[0].strip() and not r2[1].strip()
        if not re.search(r"\b\d{4,8}\b", " ".join(r1)) and not clean_num(r1[-1] if r1 else 0):
            i += 1
            continue
        desc_cell = r1[desc_col].strip() if desc_col < len(r1) else ""
        hsn_m = re.search(r"\b(\d{6,8})\b", desc_cell)
        hsn = hsn_m.group(1) if hsn_m else ""
        desc = re.sub(r"\|\s*\d+(?:\.\d+)?\s*[A-Za-z]+\b", "", desc_cell)
        desc = re.sub(r"\b\d{6,8}\b", "", desc).strip(" |")
        unit_cell = r1[uom_col].strip() if uom_col < len(r1) else ""
        unit = re.sub(r"\s+\d[\d,]*\.?\d*\s*$", "", unit_cell).strip()
        rate_price = clean_num(r1[rate_col]) if rate_col < len(r1) else 0.0
        qty = clean_num(r1[qty_col]) if qty_col < len(r1) else 0.0
        gross = clean_num(r1[gross_col]) if gross_col < len(r1) else 0.0
        disc = round2(sum(clean_num(r1[c]) for c in disc_cols if c < len(r1)))
        tot_tax = clean_num(r1[tax_col]) if tax_col < len(r1) else 0.0
        lt = clean_num(r1[amt_col]) if amt_col < len(r1) else 0.0
        if is_paired:
            if is_two_row_split_hdr and r2_tx_col >= 0 and r2_cga_col >= 0 and r2_sga_col >= 0:
                taxable = clean_num(r2[r2_tx_col]) if r2_tx_col < len(r2) else 0.0
                cg_pct = clean_num(r2[r2_cgp_col]) if 0 <= r2_cgp_col < len(r2) else 0.0
                cgst = clean_num(r2[r2_cga_col]) if r2_cga_col < len(r2) else 0.0
                sg_pct = clean_num(r2[r2_sgp_col]) if 0 <= r2_sgp_col < len(r2) else 0.0
                sgst = clean_num(r2[r2_sga_col]) if r2_sga_col < len(r2) else 0.0
            else:
                taxable = clean_num(r2[3]) if len(r2) > 3 else 0.0
                cg_pct = clean_num(r2[4]) if len(r2) > 4 else 0.0
                cgst = clean_num(r2[5]) if len(r2) > 5 else 0.0
                sg_pct = clean_num(r2[7]) if len(r2) > 7 else 0.0
                sgst = clean_num(r2[8]) if len(r2) > 8 else 0.0
            gst_rate = round2(cg_pct + sg_pct)
            i += 2
        else:
            taxable = round2(gross - disc) if gross > 0 else round2(lt - tot_tax)
            gst_rate = round2((tot_tax / taxable) * 100.0) if (taxable > 0 and tot_tax > 0) else 0.0
            half = _equal_local_tax_half(taxable, gst_rate, tot_tax)
            cgst = half
            sgst = half
            i += 1
        if taxable == 0.0 and gross > 0:
            taxable = round2(gross - disc)
        out.append({
            "description": desc,
            "hsnSac": hsn,
            "quantity": round2(qty),
            "unit": unit,
            "rate": round2(rate_price),
            "discount": round2(disc),
            "taxable": round2(taxable),
            "gstRate": round2(gst_rate),
            "cgst": round2(cgst),
            "sgst": round2(sgst),
            "igst": 0.0,
            "cess": 0.0,
            "lineTotal": round2(lt),
        })
    return out


def _parse_item_rows_from_matrix(mat: List[List[str]]) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    if len(mat) < 2:
        return [], {}
    hdr_idx = 0
    for i in range(min(3, len(mat))):
        if _is_item_table_header(mat[i]):
            hdr_idx = i
            break

    def _strip_leading_blanks(row: List[str]) -> List[str]:
        k = 0
        while k < len(row) and not row[k].strip():
            k += 1
        return row[k:]

    mat_norm = [list(r) for r in mat]
    lead_hdr = len(mat_norm[hdr_idx]) - len(_strip_leading_blanks(mat_norm[hdr_idx]))
    if lead_hdr > 0:
        mat_norm[hdr_idx] = mat_norm[hdr_idx][lead_hdr:]
        if hdr_idx + 1 < len(mat_norm) and len(mat_norm[hdr_idx + 1]) > lead_hdr and all(not x.strip() for x in mat_norm[hdr_idx + 1][:lead_hdr]):
            mat_norm[hdr_idx + 1] = mat_norm[hdr_idx + 1][lead_hdr:]

    hdr1 = [c.lower() for c in mat_norm[hdr_idx]]
    hdr2 = [c.lower() for c in mat_norm[hdr_idx + 1]] if (hdr_idx + 1 < len(mat_norm) and not any(re.search(r"\b\d{4,8}\b", c) for c in mat_norm[hdr_idx + 1])) else []
    data_start = hdr_idx + (2 if hdr2 else 1)

    hdr1_filled = list(hdr1)
    for c in range(1, len(hdr1_filled)):
        if not hdr1_filled[c].strip() and hdr1_filled[c - 1].strip() in ("cgst", "sgst", "s/utgst", "sgst/utgst", "igst", "quantity", "qty", "rate"):
            hdr1_filled[c] = hdr1_filled[c - 1]

    col_map: Dict[str, List[int]] = {}
    ncols = max(len(r) for r in mat_norm)
    stacked_itc_rows = _try_parse_dual_stacked_itc_table(mat_norm, data_start)
    if stacked_itc_rows is not None:
        return stacked_itc_rows, {}
    for c in range(ncols):
        t1 = hdr1_filled[c] if c < len(hdr1_filled) else ""
        t2 = hdr2[c] if c < len(hdr2) else ""
        t = (t1 + " " + t2).strip()
        if "hsn" in t or "sac" in t:
            col_map.setdefault("hsn", []).append(c)
        elif any(k in t for k in ("product", "description", "particulars", "item", "goods", "service")):
            col_map.setdefault("desc", []).append(c)
        elif "total unit" in t or ("qty" in t and "free" not in t) or "quantity" in t or "billed" in t:
            col_map.setdefault("qty", []).append(c)
        elif t in ("unit", "uom", "per"):
            col_map.setdefault("unit", []).append(c)
        elif "taxable" in t or "assessable" in t:
            col_map.setdefault("taxable", []).append(c)
        elif (re.match(r"^(?:gst|tax)\b", t) or re.search(r"\b(?:gst|tax)\s*(?:%|rate)\b", t)) and not any(k in t for k in ("cgst", "sgst", "utgst", "igst", "amt", "amount", "desc")):
            col_map.setdefault("gstrate", []).append(c)
        elif any(re.search(rf"\b{re.escape(k)}\b", t) for k in ("tax amt", "tax amount", "gst amt", "gst amount", "tot.tax", "tot tax", "total tax")) and not any(k in t for k in ("cgst", "sgst", "utgst", "igst", "taxable", "after")):
            col_map.setdefault("tax_amt", []).append(c)
        elif ("bef.tax" in t or "bef tax" in t or "base rate" in t) and "gst" not in t:
            col_map.setdefault("pref_rate", []).append(c)
        elif "rate" in t and ("incl" in t or "inclusive" in t):
            col_map.setdefault("incl_rate", []).append(c)
        elif "rate" in t and "gst" not in t and "cgst" not in t and "sgst" not in t and "igst" not in t and "with tax" not in t:
            col_map.setdefault("rate", []).append(c)
        elif "price" in t and not any(k in t for k in ("mrp", "s price", "s.price", "sale price", "selling price", "gst", "net price")):
            col_map.setdefault("alt_price", []).append(c)
        elif ("cgst" in t or "sgst" in t or "utgst" in t) and ("%" in t or "rate" in t) and "amt" not in t and "amount" not in t:
            col_map.setdefault("half_gstrate", []).append(c)
        elif ("cgst" in t or "igst/ cgst" in t) and "rate" not in t2 and "%" not in t:
            col_map.setdefault("cgst", []).append(c)
        elif ("sgst" in t or "utgst" in t) and "rate" not in t2 and "%" not in t:
            col_map.setdefault("sgst", []).append(c)
        elif "igst" in t and "rate" not in t2 and "%" not in t:
            col_map.setdefault("igst", []).append(c)
        elif "gross amt" in t or "gross amount" in t or "gross value" in t:
            col_map.setdefault("gross", []).append(c)
        elif "disc" in t or "sch amt" in t:
            col_map.setdefault("disc", []).append(c)
        elif "net amt" in t or "net amount" in t or "net value" in t or "total value" in t or "amount" in t or t in ("total", "total amt", "total amount", "line total", "net total", "bill amt", "value"):
            col_map.setdefault("total", []).append(c)

    if "pref_rate" in col_map:
        col_map["rate"] = col_map["pref_rate"] + col_map.get("rate", [])
    if "rate" not in col_map and "alt_price" in col_map:
        col_map["rate"] = col_map["alt_price"]
    if "rate" not in col_map and "incl_rate" in col_map:
        col_map["rate"] = col_map["incl_rate"]

    if "qty" not in col_map:
        for c in range(ncols):
            t1 = hdr1_filled[c] if c < len(hdr1_filled) else ""
            if "pcs" in t1 and "sch" not in t1:
                col_map.setdefault("qty", []).append(c)

    rows: List[Dict[str, Any]] = []
    footer_hints: Dict[str, float] = {}
    current_hsn = ""

    for r in mat_norm[data_start:]:
        row_text = " ".join(r).strip()
        low = row_text.lower()
        if not row_text:
            continue
        if re.search(r"\b(?:c/f|b/f|carry\s*forward|carried\s*forward|brought\s*forward|continued|contd\.?|sub\s*-?\s*total|page\s*\d+\s*of\s*\d+)\b", low):
            has_hsn_col_val = any(
                idx < len(r) and bool(re.search(r"(?<!\.)\b\d{4,8}\b(?![.,]\d)", r[idx]))
                for idx in col_map.get("hsn", [])
            )
            if not has_hsn_col_val:
                continue
        if low.startswith("total") or bool(re.search(r"\btotals?\b", low)) or re.match(r"^no\.?\s*of\s*items", low):
            tot_col_nums = [
                clean_num(r[idx])
                for idx in col_map.get("total", [])
                if idx < len(r) and re.search(r"\d", r[idx])
            ]
            if tot_col_nums:
                footer_hints["table_total_last"] = tot_col_nums[-1]
            else:
                nums = [clean_num(c) for c in r if re.search(r"\d", c)]
                if nums:
                    footer_hints["table_total_last"] = nums[-1]
            continue
        if "output cgst" in low or (len(r) > 1 and "cgst" == r[1].strip().lower()):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["cgstTotal"] = footer_hints.get("cgstTotal", 0.0) + nums[-1]
            continue
        if "output sgst" in low or (len(r) > 1 and "sgst" == r[1].strip().lower()):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["sgstTotal"] = footer_hints.get("sgstTotal", 0.0) + nums[-1]
            continue
        if "output igst" in low or (len(r) > 1 and "igst" == r[1].strip().lower()):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["igstTotal"] = footer_hints.get("igstTotal", 0.0) + nums[-1]
            continue
        if ("round off" in low or "round-off" in low) and not re.search(r"\b\d{6,8}\b", row_text):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                val = nums[-1]
                if "(-)" in row_text or "less" in low:
                    val = -abs(val)
                footer_hints["roundOff"] = val
            continue

        hsn = ""
        for idx in col_map.get("hsn", []):
            if idx < len(r):
                m = re.search(r"\b(\d{4,8})\b", r[idx])
                if m:
                    hsn = m.group(1)
                    break
        if not hsn:
            m = re.search(r"\b(\d{6,8})\b", row_text)
            if m:
                hsn = m.group(1)

        desc = ""
        for idx in col_map.get("desc", []):
            if idx < len(r) and r[idx].strip():
                desc = r[idx].strip()
                break
        if not desc and len(r) >= 2:
            cands = [c.strip() for c in r if re.search(r"[A-Za-z]{3,}", c)]
            if cands:
                desc = max(cands, key=len)

        def pick_num(key: str) -> float:
            indices = col_map.get(key, [])
            if key in ("taxable", "cgst", "sgst", "igst", "total", "tax_amt"):
                for idx in indices:
                    if idx < len(r) and "%" not in r[idx] and re.search(r"\d", r[idx]):
                        nums = parse_nums_in_cell(r[idx])
                        if nums:
                            return nums[-1]
            for idx in indices:
                if idx < len(r) and re.search(r"\d", r[idx]):
                    nums = parse_nums_in_cell(r[idx])
                    if nums:
                        return nums[-1]
            return 0.0

        def pick_first_num(key: str) -> Tuple[float, str]:
            first_zero = None
            for idx in col_map.get(key, []):
                if idx < len(r) and re.search(r"\d", r[idx]):
                    nums = parse_nums_in_cell(r[idx])
                    m_u = re.search(r"\d\s*([A-Za-z]{1,6})\b", r[idx])
                    sub_u = ""
                    if not m_u and key == "qty" and idx < len(hdr2):
                        h_tok = hdr2[idx].strip()
                        if re.fullmatch(r"[a-z]{1,6}", h_tok) and h_tok not in ("qty", "na"):
                            sub_u = h_tok.capitalize() if len(h_tok) > 2 else h_tok.upper()
                    if nums:
                        val = nums[0]
                        u_txt = m_u.group(1).strip() if m_u else sub_u
                        if key == "qty" and len(col_map.get(key, [])) > 1 and val == 0.0:
                            if first_zero is None:
                                first_zero = (val, u_txt)
                            continue
                        return val, u_txt
            return first_zero if first_zero is not None else (0.0, "")

        qty, qty_unit = pick_first_num("qty")
        unit = ""
        for idx in col_map.get("unit", []):
            if idx < len(r) and r[idx].strip():
                unit = r[idx].strip()
                break
        if not unit:
            unit = qty_unit
        rate_price = pick_num("rate")
        gross = pick_num("gross")
        disc_parts = []
        for d_idx in col_map.get("disc", []):
            if d_idx < len(r) and "%" not in r[d_idx] and re.search(r"\d", r[d_idx]):
                nums = parse_nums_in_cell(r[d_idx])
                if nums:
                    disc_parts.append(nums[-1])
        disc = round2(sum(disc_parts))
        taxable = pick_num("taxable")
        if disc < 0 and gross > 0:
            if taxable == 0.0 or abs((gross - abs(disc)) - taxable) <= 0.50:
                disc = abs(disc)
        if taxable == 0.0 and gross > 0:
            taxable = round2(gross - disc)
        gst_rate, _ = pick_first_num("gstrate")
        if gst_rate == 0.0 and "half_gstrate" in col_map:
            hr, _ = pick_first_num("half_gstrate")
            if hr in (0, 1.5, 2.5, 6, 9, 14):
                gst_rate = hr * 2.0
        cgst = pick_num("cgst")
        sgst = pick_num("sgst")
        igst = pick_num("igst")
        combined_tax_col = pick_num("tax_amt")
        tax_from_combined = False
        if cgst == 0.0 and sgst == 0.0 and igst == 0.0 and combined_tax_col > 0:
            half = _equal_local_tax_half(taxable, gst_rate, combined_tax_col)
            cgst = half
            sgst = half
            tax_from_combined = True
        line_total = pick_num("total")

        # Handle Tally <br>-merged trailing tax/round-off ledger lines inside the last item row
        tot_indices = col_map.get("total", [])
        if tot_indices and tot_indices[0] < len(r):
            raw_tot_nums = parse_nums_in_cell(r[tot_indices[0]])
            m_ledgers = re.search(
                r"(?:\s+((?:(?:output|input)\s+)?(?:cgst|sgst|igst|round\s*[-]?\s*off))){1,4}\s*$",
                desc,
                re.IGNORECASE,
            )
            if m_ledgers and len(raw_tot_nums) >= 2:
                toks = re.findall(r"(?:(?:output|input)\s+)?(?:cgst|sgst|igst|round\s*[-]?\s*off)", m_ledgers.group(0), re.IGNORECASE)
                if len(raw_tot_nums) >= 1 + len(toks):
                    line_total = raw_tot_nums[0]
                    if taxable == 0.0:
                        taxable = raw_tot_nums[0]
                    for tok, num in zip(toks, raw_tot_nums[1:1 + len(toks)]):
                        tl = tok.lower()
                        if "cgst" in tl:
                            footer_hints["cgstTotal"] = round2(footer_hints.get("cgstTotal", 0.0) + num)
                        elif "sgst" in tl:
                            footer_hints["sgstTotal"] = round2(footer_hints.get("sgstTotal", 0.0) + num)
                        elif "igst" in tl:
                            footer_hints["igstTotal"] = round2(footer_hints.get("igstTotal", 0.0) + num)
                        elif "round" in tl:
                            footer_hints["roundOff"] = num
                    desc = desc[:m_ledgers.start()].strip()

        if re.match(r"^hsn(?:/sac)?\s*[:\-]?\s*[\d.\s]{4,14}$", desc, re.IGNORECASE) and taxable == 0.0 and line_total == 0.0:
            h_digits = re.sub(r"[^0-9]", "", desc)
            if 4 <= len(h_digits) <= 8:
                current_hsn = h_digits
            continue
        if not hsn and current_hsn:
            hsn = current_hsn

        if gst_rate == 0.0:
            for idx in col_map.get("cgst", []):
                if idx < len(r):
                    nums = parse_nums_in_cell(r[idx])
                    if ("%" in r[idx] or len(nums) >= 2) and nums and nums[0] in (0, 1.5, 2.5, 6, 9, 14):
                        gst_rate = nums[0] * 2.0
                        if len(nums) >= 2 and cgst == nums[0]:
                            cgst = nums[-1]
                        break

        if taxable == 0.0 and line_total == 0.0 and (cgst + sgst + igst) == 0.0:
            continue

        raw_amt_only = 0.0
        if taxable == 0.0 and line_total > 0 and (cgst + sgst + igst) > 0:
            cand_qty_tx = round2(qty * rate_price - disc) if (qty > 0 and rate_price > 0) else 0.0
            if cand_qty_tx > 0 and abs(cand_qty_tx + cgst + sgst + igst - line_total) <= 0.25:
                taxable = cand_qty_tx
            else:
                taxable = round2(line_total - (cgst + sgst + igst))
        elif taxable == 0.0 and line_total > 0 and gst_rate > 0:
            raw_amt_only = line_total
            taxable = round2(line_total / (1.0 + gst_rate / 100.0))
            tax_amt = round2(line_total - taxable)
            if cgst == 0.0 and sgst == 0.0 and igst == 0.0:
                cgst = round2(tax_amt / 2.0)
                sgst = round2(tax_amt - cgst)
        elif taxable == 0.0 and line_total > 0 and gst_rate == 0.0 and (cgst + sgst + igst) == 0.0:
            # 0%-GST / NIL-tax / Bill of Supply amount-only line: Amount == Taxable
            taxable = round2(line_total)

        if taxable > 0 and gst_rate > 0 and cgst == 0.0 and sgst == 0.0 and igst == 0.0:
            tax_amt = round2(taxable * gst_rate / 100.0)
            cgst = round2(tax_amt / 2.0)
            sgst = round2(tax_amt - cgst)
        if line_total == 0.0 and taxable > 0:
            line_total = round2(taxable + cgst + sgst + igst)
        if gst_rate == 0.0 and taxable > 0 and (cgst + sgst + igst) > 0:
            est_rate = ((cgst + sgst + igst) / taxable) * 100.0
            for std in (0, 3, 5, 12, 18, 28):
                if abs(est_rate - std) <= 0.6:
                    gst_rate = float(std)
                    break

        # Case/Box vs per-piece rate (e.g. Inv Qty = 1 CS, Rate = 0.86/pc, Gross Amount = 831.16, Disc = 165.40 -> Taxable = 665.76)
        if qty > 0 and gross > 0 and abs((gross - disc) - taxable) <= 0.25 and rate_price > 0 and abs((qty * rate_price) - gross) > max(1.0, gross * 0.02):
            rate_price = round2(gross / qty)

        # Per-unit discount (e.g. METRO Bill of Supply: Qty = 3, Price = 1820, Discount = 593.04/unit -> Taxable = 3680.88)
        if qty > 1 and disc > 0 and rate_price > 0 and taxable > 0 and abs((qty * rate_price - disc) - taxable) > max(1.5, taxable * 0.01):
            if abs((qty * (rate_price - disc)) - taxable) <= max(1.0, taxable * 0.005):
                disc = round2(disc * qty)

        rows.append({
            "description": desc,
            "hsnSac": hsn,
            "quantity": round2(qty),
            "unit": unit,
            "rate": round2(rate_price),
            "discount": round2(disc),
            "taxable": round2(taxable),
            "gstRate": round2(gst_rate),
            "cgst": round2(cgst),
            "sgst": round2(sgst),
            "igst": round2(igst),
            "cess": 0.0,
            "lineTotal": round2(line_total),
            "_raw_amt_only": raw_amt_only,
            "_tax_from_combined": tax_from_combined,
        })

    return rows, footer_hints


_PARTY_NOISE_PREFIX_RE = re.compile(
    r"^(?:page\s+\d+|print\s+copy|pan(?:\s+no)?|fssai(?:\s+no)?|essai(?:\s+lic)?|gstin(?:/uin)?|gstn(?:\s+no)?|state(?:\s+name|\s+code)?|"
    r"phone|ph(?:\s+no)?|mob(?:ile)?|contact|email|e-?mail|cin|van|beat|order\s+no|dse\s+name|"
    r"salesperson|eway|e-?way|irn|ack\.?\s*(?:no|date)|e-?inv|from|to|buyer(?:\s*\(bill\s*to\))?|"
    r"bill\s*to|billed\s*to|ship\s*to|shipping\s+(?:address|date)|registered\s+address|customer\s+(?:address|details)|"
    r"cust\.?\s*code|party\s+(?:mobile|gstin)|branch\s+name|channel|tax\s+type|place\s+of\s+(?:sale|supply)|"
    r"date\b|dated\b|inv(?:oice)?\s*no|bill\s*no|doc(?:ument)?\s*(?:no|number)|sm\s+name|rt\s+name|all\s+taxes\s+are|"
    r"gst\s+invoice(?:/cash)?|tax\s+invoice(?:\s*\(credit\))?|bill\s+of\s+supply|original(?:\s+for\s+recipient)?|"
    r"duplicate|triplicate|reverse\s+charge|for\s+)\b",
    re.IGNORECASE,
)

_ADDRESS_HINT_RE = re.compile(
    r"\b(?:cross|road|rd\b|street|st\b|yard|apmc|a\s*p\s*m\s*c|ayard|nagar|circle|enclave|survey|plot\s+no|"
    r"ward\s+no|pin\s*code|near|beside|opp\.?|bengaluru|tumkur|thumkur|tumakuru|karnataka|india|"
    r"k(?:ha|at|ath)a\s+no|bata?wadi|balawadi|mandipet|belagumba)\b",
    re.IGNORECASE,
)


def _strip_md(s: str) -> str:
    s = re.sub(r"[*#`]+", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _clean_party_name(s: str) -> str:
    s = _strip_md(s)
    # Strip wrapper parentheses like "(Registered as Metro Cash and Carry India Limited)"
    s = re.sub(r"^\(\s*(?:registered\s+as\s+)?(.+?)\s*\)$", r"\1", s, flags=re.IGNORECASE)
    # Strip explicit label prefixes ("Party Name : BALAJI...", "To BALAJI...", "M/s. ...")
    s = re.sub(r"^(?:party\s*name|customer\s*name|buyer\s*name|supplier\s*name|seller\s*name|m/s\.?)\s*[:\-]?\s+", "", s, flags=re.IGNORECASE)
    m_to = re.match(r"^(?:to|from)\s*[:\-]?\s+(.{3,})$", s, re.IGNORECASE)
    if m_to:
        s = m_to.group(1)
    # Remove trailing phone number / single marker letter (e.g. "BALAJI TRADING CO. 9731329698 D")
    s = re.sub(r"\s+\d{10}(?:\s+[A-Z])?\s*$", "", s)
    # Remove trailing FY ranges ("2026-2027 (from 1-Apr-26)")
    s = re.sub(r"\s+20\d{2}-20\d{2}\s*(?:\([^)]*\))?\s*$", "", s)
    s = s.strip(" :-|,")
    if len(s) < 3 or s.startswith("&") or s.lower() in ("address", "name & address"):
        return ""
    if _PARTY_NOISE_PREFIX_RE.match(s):
        return ""
    if _ADDRESS_HINT_RE.search(s) and not re.search(
        r"\b(?:enterprises|traders|marketing|distributors|trading|agencies|pvt\s+ltd|llp|limited|ltd\.?|inc\.?|corp\.?|company|wholesale|cash\s+and\s+carry)\b",
        s,
        re.IGNORECASE,
    ):
        return ""
    if re.fullmatch(r"[\d\W]+", s) or re.match(r"^[0-9]{6,}", s):
        return ""
    if len(re.findall(r"[A-Za-z]", s)) < 3:
        return ""
    return s[:120]


def _extract_party_name_near(lines: List[str], target_gstin: str, role_keywords: Tuple[str, ...], fallback_top: bool) -> str:
    clean_lines = [_strip_md(ln) for ln in lines[:65]]
    clean_lines = [ln for ln in clean_lines if ln]

    # 1. Explicit role label on line (e.g. "Party Name : BALAJI..." or "To BALAJI TRADING CO" or "From:\nVEERABHADRESHWARA...")
    for i, ln in enumerate(clean_lines[:55]):
        low = ln.lower()
        if any(noise in low for noise in ("original for", "duplicate for", "triplicate for", "for recipient")):
            continue
        m_direct = re.match(r"^(?:to|from|party\s*name|customer\s*name|buyer\s*name|supplier\s*name|seller\s*name)\s*[:\-]?\s+(.+)$", ln, re.IGNORECASE)
        if m_direct and (
            (fallback_top and low.startswith(("from", "supplier", "seller")))
            or (not fallback_top and low.startswith(("to", "party", "customer", "buyer")))
        ):
            after = _clean_party_name(m_direct.group(1))
            if after:
                return after
        if any(k in low for k in role_keywords):
            if ":" in ln:
                after = _clean_party_name(ln.split(":", 1)[1])
                if after:
                    return after
            for nxt in range(1, 4):
                if i + nxt < len(clean_lines):
                    cand = _clean_party_name(clean_lines[i + nxt])
                    if cand:
                        return cand

    # 2. Walk near target GSTIN line (upwards first, then downwards 1..3 lines if seller GSTIN is above heading)
    if target_gstin:
        for i, ln in enumerate(clean_lines[:60]):
            if target_gstin in re.sub(r"[^A-Za-z0-9]", "", ln).upper():
                if not fallback_top:
                    for back in range(1, 9):
                        if i - back >= 0:
                            cand = _clean_party_name(clean_lines[i - back])
                            if cand:
                                return cand
                else:
                    # For seller, do not accidentally walk into a "M/s :" / "Billed To" buyer block right above the seller GSTIN
                    for back in range(1, 9):
                        if i - back < 0:
                            break
                        prev_low = clean_lines[i - back].lower()
                        if re.match(r"^(?:m/s|bill(?:ed)?\s*to|buyer|ship(?:ped)?\s*to)\b", prev_low):
                            break
                        cand = _clean_party_name(clean_lines[i - back])
                        if cand and not any(re.match(r"^(?:m/s|bill(?:ed)?\s*to|buyer)\b", clean_lines[k].lower()) for k in range(max(0, i - back - 2), i - back)):
                            return cand
                for fwd in range(1, 4):
                    if i + fwd < len(clean_lines):
                        cand = _clean_party_name(clean_lines[i + fwd])
                        if cand:
                            return cand

    # 3. Top header fallback for seller
    if fallback_top:
        for ln in clean_lines[:10]:
            cand = _clean_party_name(ln)
            if cand:
                return cand
    return ""


def resolve_seller_buyer(plain: str, gstins: List[str], known_client_gstin: Optional[str] = None, direction_hint: str = "Auto") -> Tuple[str, str]:
    upper_lines = [_strip_md(ln) for ln in plain.splitlines() if ln.strip()]
    seller_g = ""
    buyer_g = ""

    sig_seller_hint = ""
    for ln in reversed(upper_lines):
        m_for = re.search(r"\bfor\s+([A-Z][A-Z0-9 &.,'-]{3,})$", ln, re.IGNORECASE)
        if m_for:
            sig_seller_hint = re.sub(r"[^A-Z0-9]", "", m_for.group(1).upper())
            break

    scores: Dict[str, Tuple[int, int]] = {}
    for g in gstins:
        s_score = 0
        b_score = 0
        pan_part = g[2:12] if len(g) == 15 else g
        for idx, ln in enumerate(upper_lines[:75]):
            norm_ln = re.sub(r"[^A-Za-z0-9]", "", ln).upper()
            if g in norm_ln or (len(pan_part) == 10 and pan_part in norm_ln and ("gst" in ln.lower() or "pan" in ln.lower())):
                ctx_lines = upper_lines[max(0, idx - 4):idx + 2]
                ctx = " | ".join(ctx_lines).lower()
                if any(m in ctx for m in ("buyer", "bill to", "billed to", "ship to", "shipped to", "recipient", "consignee", "fssai no : 0", "fssai no: 0")) or (
                    idx >= 3 and re.search(r"\bm/s\s*[:\-]", ctx)
                ):
                    b_score += 5
                if any(m in ctx for m in ("seller", "supplier", "from:", "consignor", "registered name", "fssai no : 1", "fssai no: 1")):
                    s_score += 5
                if "tax invoice" in ctx and idx > 5:
                    s_score += 3
                if idx <= 6:
                    s_score += 2
                if sig_seller_hint and any(sig_seller_hint in re.sub(r"[^A-Z0-9]", "", cl.upper()) for cl in ctx_lines):
                    s_score += 4
                break
        scores[g] = (s_score, b_score)

    if len(gstins) == 1:
        g0 = gstins[0]
        ss, bs = scores[g0]
        if bs > ss:
            buyer_g = g0
        else:
            seller_g = g0
    elif len(gstins) >= 2:
        g_sorted_seller = sorted(gstins, key=lambda x: (scores[x][0] - scores[x][1]), reverse=True)
        seller_g = g_sorted_seller[0]
        buyer_g = next((x for x in gstins if x != seller_g), "")

    if known_client_gstin:
        cg, cok, _ = repair_gstin(known_client_gstin)
        if cok and cg in gstins:
            hint = (direction_hint or "Auto").strip().lower()
            if hint == "sales" and seller_g != cg:
                if buyer_g == cg:
                    buyer_g = seller_g
                seller_g = cg
            elif hint == "purchase" and buyer_g != cg:
                if seller_g == cg:
                    seller_g = buyer_g
                buyer_g = cg

    return seller_g, buyer_g


def extract_place_of_supply(lines: List[str]) -> str:
    for ln in lines[:60]:
        m = re.search(r"Place\s+of\s+Supply\s*[:\-]?\s*([A-Za-z0-9\s,\-()]{2,50})", ln, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip(" :-,")
    return ""


def detect_document_type(lines: List[str], qr_einvoice: Optional[Dict[str, Any]] = None) -> str:
    doc_typ = str((qr_einvoice or {}).get("DocTyp") or "").strip().upper()
    if doc_typ == "CRN":
        return "Credit Note"
    if doc_typ == "DBN":
        return "Debit Note"
    head = "\n".join(lines[:15]).upper()
    if "CREDIT NOTE" in head:
        return "Credit Note"
    if "DEBIT NOTE" in head:
        return "Debit Note"
    if "BILL OF SUPPLY" in head:
        return "Bill of Supply"
    if "DELIVERY CHALLAN" in head:
        return "Delivery Challan"
    if "PROFORMA" in head:
        return "Proforma Invoice"
    return "Tax Invoice"


def extract_html_tables(raw_text: str) -> List[str]:
    return [m.group(0) for m in re.finditer(r"<table\b[^>]*>.*?</table>", raw_text or "", re.IGNORECASE | re.DOTALL)]


def build_gst_slabs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_rate: Dict[float, Dict[str, float]] = {}
    for r in rows:
        tx = float(r.get("taxable") or 0.0)
        cg = float(r.get("cgst") or 0.0)
        sg = float(r.get("sgst") or 0.0)
        ig = float(r.get("igst") or 0.0)
        cs = float(r.get("cess") or 0.0)
        rt = float(r.get("gstRate") or 0.0)
        if tx <= 0 and (cg + sg + ig) <= 0:
            continue
        bucket = by_rate.setdefault(rt, {"gstRate": rt, "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "cess": 0.0})
        bucket["taxable"] += tx
        bucket["cgst"] += cg
        bucket["sgst"] += sg
        bucket["igst"] += ig
        bucket["cess"] += cs
    slabs = []
    for rt in sorted(by_rate.keys()):
        b = by_rate[rt]
        slabs.append({
            "gstRate": round2(rt),
            "taxable": round2(b["taxable"]),
            "cgst": round2(b["cgst"]),
            "sgst": round2(b["sgst"]),
            "igst": round2(b["igst"]),
            "cess": round2(b["cess"]),
            "combinedTax": round2(b["cgst"] + b["sgst"] + b["igst"] + b["cess"]),
        })
    return slabs


def _extract_table_kv(tables: List[List[List[str]]], label_re: re.Pattern, value_filter) -> str:
    for mat in tables:
        if _is_tax_summary_table(mat):
            continue
        item_hdrs = [i for i, r in enumerate(mat) if _is_item_table_header(r)]
        row_limit = item_hdrs[0] if item_hdrs else len(mat)
        for i in range(row_limit):
            for c, raw_cell in enumerate(mat[i]):
                cell = _strip_md(raw_cell)
                if not cell or len(cell) > 40 or not label_re.search(cell):
                    continue
                cands: List[str] = []
                if i + 1 < row_limit and c < len(mat[i + 1]):
                    cands.append(_strip_md(mat[i + 1][c]))
                if c + 1 < len(mat[i]):
                    cands.append(_strip_md(mat[i][c + 1]))
                for cand in cands:
                    if value_filter(cand):
                        return cand
    return ""


def _split_tables_for_text(txt: str) -> List[List[List[str]]]:
    t = _otsl_tables_to_matrices(txt)
    if not t:
        t = _html_tables_to_matrices(txt) + _markdown_tables_to_matrices(txt)
    return t


def _to_plain_text(txt: str) -> str:
    cleaned = re.sub(r"<(?:fcel|ecel|lcel|ucel|xcel)>", " ", txt).replace("<nl>", "\n")
    soup = BeautifulSoup(cleaned, "lxml") if "<table" in cleaned or "<td" in cleaned else None
    return soup.get_text("\n") if soup else cleaned


def parse_document_text_to_canonical(
    raw_text: str,
    qr_einvoice: Optional[Dict[str, Any]] = None,
    known_client_gstin: Optional[str] = None,
    direction_hint: str = "Auto",
) -> Dict[str, Any]:
    """Unified parser handling JSON VLM output, multi-page OTSL/HTML/Markdown tables, or plain OCR text."""
    obj = extract_json_object(raw_text)
    if obj and (obj.get("rows") or obj.get("invoiceNumber") or obj.get("invoiceTotal")):
        return normalize_canonical_dict(obj, raw_text, qr_einvoice)

    page_texts = [p.strip() for p in re.split(r"<!--\s*PAGE\s+BREAK\s*-->", raw_text or "", flags=re.IGNORECASE) if p.strip()]
    if not page_texts:
        page_texts = [raw_text or ""]

    page_tables_list = [_split_tables_for_text(pt) for pt in page_texts]
    tables = [mat for pts in page_tables_list for mat in pts]
    plain_pages = [_to_plain_text(pt) for pt in page_texts]
    plain = "\n\n".join(plain_pages)
    plain_lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    first_page_plain = plain_pages[0]
    first_page_lines = [ln.strip() for ln in first_page_plain.splitlines() if ln.strip()]

    all_rows: List[Dict[str, Any]] = []
    footer_hints: Dict[str, float] = {}
    last_item_hdr_rows: List[List[str]] = []

    for page_mats in page_tables_list:
        for mat in page_mats:
            if _is_tax_summary_table(mat):
                continue
            item_start_indices = [i for i, r in enumerate(mat) if _is_item_table_header(r)]
            effective_mat = mat
            if not item_start_indices and last_item_hdr_rows:
                ncols_cur = max((len(r) for r in mat), default=0)
                ncols_prev = max((len(r) for r in last_item_hdr_rows), default=0)
                joined_mat = " ".join(" ".join(r) for r in mat)
                if ncols_prev > 0 and abs(ncols_cur - ncols_prev) <= 1 and (
                    re.search(r"\b\d{4,8}\b", joined_mat) or re.search(r"\b\d+[.,]\d{2}\b", joined_mat)
                ) and not re.search(r"\b(?:delivery note|dispatch doc|buyer.?s order|terms of delivery)\b", joined_mat, re.IGNORECASE):
                    effective_mat = last_item_hdr_rows + mat
                    item_start_indices = [0]

            if item_start_indices:
                idx0 = item_start_indices[0]
                sub = effective_mat[idx0:]
                cut_at = len(sub)
                j_start = 2 if (len(sub) > 1 and not any(re.search(r"\b\d{4,8}\b", c) for c in sub[1])) else 1
                for j in range(j_start, len(sub)):
                    jl = " ".join(sub[j]).lower()
                    if (
                        ("cgst 2.5" in jl and "sgst" in jl)
                        or ("particulars" in jl and "gross amt" in jl)
                        or ("tax desc" in jl and "tax%" in jl)
                        or ("taxable" in jl and ("cgst" in jl or "sgst" in jl or "igst" in jl) and "net" not in jl and "product" not in jl and "rate" not in jl and "gross" not in jl)
                        or ("initiative name" in jl)
                        or ("credit note number" in jl)
                        or ("digital signature" in jl)
                        or ("terms & conditions" in jl)
                    ):
                        cut_at = j
                        break
                parsed_rows, fh = _parse_item_rows_from_matrix(sub[:cut_at])
                if parsed_rows:
                    has_hdr2 = len(sub) > 1 and not any(re.search(r"\b\d{4,8}\b", c) for c in sub[1])
                    last_item_hdr_rows = sub[:2] if has_hdr2 else sub[:1]
                    all_rows.extend(parsed_rows)
                    footer_hints.update(fh)
                if cut_at < len(sub) and _is_tax_summary_table(sub[cut_at:]):
                    tables.append(sub[cut_at:])
            elif _is_tax_summary_table(mat):
                continue

    rows = all_rows
    plain_lines_clean = [_strip_md(re.sub(r"\|+", " ", ln)) for ln in plain.splitlines()]
    plain_lines_clean = [ln for ln in plain_lines_clean if ln]
    plain_joined = "\n".join(plain_lines_clean)

    first_lines_clean = [_strip_md(re.sub(r"\|+", " ", ln)) for ln in first_page_plain.splitlines()]
    first_lines_clean = [ln for ln in first_lines_clean if ln]
    first_joined = "\n".join(first_lines_clean)

    header_scope_text = first_joined if len(page_texts) > 1 else plain_joined
    header_scope_lines = first_page_lines if len(page_texts) > 1 else plain_lines

    gstins = find_gstins_in_text(header_scope_text, extra_candidates=[known_client_gstin] if known_client_gstin else None)
    if not gstins and len(page_texts) > 1:
        gstins = find_gstins_in_text(plain_joined, extra_candidates=[known_client_gstin] if known_client_gstin else None)
    seller_gstin, buyer_gstin = resolve_seller_buyer(first_page_plain if len(page_texts) > 1 else plain, gstins, known_client_gstin, direction_hint)
    seller_name = _extract_party_name_near(header_scope_lines, seller_gstin, ("registered name", "supplier", "seller", "from:"), fallback_top=True)
    buyer_name = _extract_party_name_near(header_scope_lines, buyer_gstin, ("buyer (bill to)", "customer name", "party name", "buyer", "bill to", "billed to", "recipient", "customer", "consignee", "to:"), fallback_top=False)
    if len(page_texts) > 1 and not buyer_name:
        buyer_name = _extract_party_name_near(plain_lines, buyer_gstin, ("buyer (bill to)", "customer name", "party name", "buyer", "bill to", "billed to", "recipient", "customer", "consignee", "to:"), fallback_top=False)
    if seller_name and buyer_name and seller_name.lower() == buyer_name.lower():
        buyer_name = ""

    # Convert row CGST+SGST to IGST for interstate GSTINs when tax came from a combined Tax Amt column
    is_interstate = len(seller_gstin) == 15 and len(buyer_gstin) == 15 and seller_gstin[:2] != buyer_gstin[:2]
    for r in rows:
        if r.pop("_tax_from_combined", False) and is_interstate and (r["cgst"] + r["sgst"]) > 0 and r["igst"] == 0.0:
            r["igst"] = round2(r["cgst"] + r["sgst"])
            r["cgst"] = 0.0
            r["sgst"] = 0.0

    inv_no = _extract_table_kv(
        page_tables_list[0] if len(page_texts) > 1 else tables,
        re.compile(r"^(?:tax\s*invoice\s*no\.?|bill\s*no\.?|invoice\s*no\.?|inv\.?\s*no\.?|document\s*(?:no\.?|number)|voucher\s*no\.?)\s*[:#\-]?$", re.IGNORECASE),
        lambda v: bool(re.search(r"\d", v)) and 2 <= len(v) <= 28 and v.lower() not in ("date", "dated", "no", "amt", "number"),
    )
    if not inv_no:
        for pat in [
            r"\b(?:Tax\s*Invoice\s*No\.?|Bill\s*No\.?|Invoice\s*No\.?|Inv\.?\s*No\.?|Document\s*(?:No\.?|Number)|Voucher\s*No\.?)(?=$|[\s:#\-|\n])(?:\s*[:#\-]+\s*|\s*\n\s*|\s+)([A-Z]{1,6}\s+\d[A-Z0-9\-/]{1,20}|[A-Z0-9][A-Z0-9\-/]{1,28})",
        ]:
            for m in re.finditer(pat, header_scope_text, re.IGNORECASE):
                cand = m.group(1).strip(" :-|,")
                if re.search(r"\d", cand) and cand.lower() not in ("date", "dated", "no", "amt", "number"):
                    inv_no = cand
                    break
            if inv_no:
                break

    inv_date = _extract_table_kv(
        page_tables_list[0] if len(page_texts) > 1 else tables,
        re.compile(r"^(?:bill\s*date|invoice\s*date|inv\.?\s*date|dated|date)\s*[:\-]?$", re.IGNORECASE),
        lambda v: len(normalize_date(v)) == 10,
    )
    if not inv_date:
        for pat in [
            r"\b(?:Bill\s*Date|Invoice\s*Date|Inv\.?\s*Date|Dated|Date)(?=$|[\s:#\-|\n])(?:\s*[:\-]+\s*|\s*\n\s*|\s+)([0-9]{1,2}[./-][A-Za-z0-9]{2,9}[./-][0-9]{2,4})",
            r"\b([0-3]?\d[./-](?:0?[1-9]|1[0-2]|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[./-](?:19|20)?\d{2})\b",
        ]:
            m = re.search(pat, header_scope_text, re.IGNORECASE)
            if m:
                inv_date = normalize_date(m.group(1))
                if len(inv_date) == 10:
                    break

    # Search totals/roundoff/credit note from final page backwards using markdown-cleaned text
    rev_plain_clean = "\n".join(
        reversed([
            "\n".join([ln for ln in (_strip_md(re.sub(r"\|+", " ", l)) for l in pp.splitlines()) if ln])
            for pp in plain_pages
        ])
    )
    inv_total = 0.0
    for pat in [
        r"Net\s*(?:Amount\s*)?(?:Payable|Receivable)(?:\s*Amt)?\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9,]+[.,]\d{2}|[0-9,]{3,})",
        r"Net\s*Amt(?:\s*Payable)?\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9,]+[.,]\d{2}|[0-9,]{3,})",
        r"Net\s*Amount(?:\s*after\s*TAX)?\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9,]+[.,]\d{2}|[0-9,]{3,})",
        r"Bill\s*Amount\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9,]+[.,]\d{2}|[0-9,]{3,})",
        r"(?:Grand\s*Total|Invoice\s*Total|Total\s*Invoice\s*Value|Total\s*Payable)\s*[:\-]?\s*(?:INR|Rs\.?)?\s*([0-9,]+[.,]\d{2})",
        r"(?:^|\n)Total\b[^\n]{0,60}(?:₹|INR|Rs\.?)\s*([0-9,]+\.\d{2})",
    ]:
        m = re.search(pat, rev_plain_clean, re.IGNORECASE)
        if m:
            inv_total = clean_num(m.group(1))
            if inv_total > 0:
                break

    credit_note = 0.0
    m_cn = re.search(r"Credit\s*(?:Note|Adj/Payout)[^\d\n]{0,20}([0-9,]+\.\d{2})", rev_plain_clean, re.IGNORECASE)
    if m_cn:
        credit_note = clean_num(m_cn.group(1))

    round_off = footer_hints.get("roundOff", 0.0)
    m_ro = re.search(r"Round\s*Off(?:\s*Amt)?\s*[:\-]?\s*(\(?-\)?\s*\d+\.\d{2}-?|[-+]?\d+\.\d{2}-?)", rev_plain_clean, re.IGNORECASE)
    if m_ro:
        round_off = clean_num(m_ro.group(1))

    if inv_total == 0.0 and footer_hints.get("table_total_last", 0.0) > 0:
        inv_total = round2(footer_hints["table_total_last"])

    summary_taxable = 0.0
    summary_cgst = 0.0
    summary_sgst = 0.0
    summary_igst = 0.0
    summary_credit_note = 0.0
    summary_net_payable = 0.0
    summary_slabs: Dict[float, float] = {}
    hsn_rate_map: Dict[str, float] = {}

    for mat in reversed(tables):
        if _is_tax_summary_table(mat):
            hdr_cells = [c.lower() for c in mat[0]]
            taxable_col_idx = next((idx for idx, h in enumerate(hdr_cells) if "taxable" in h), -1)
            hsn_col_idx = next((idx for idx, h in enumerate(hdr_cells) if "hsn" in h or "sac" in h), -1)
            for tr in mat:
                joined_tr = " ".join(tr).lower()
                # Extract per-slab taxable amounts from lines like "CGST 9 + SGST 9" or "CGST 2.5 + SGST 2.5"
                cg_m = re.search(r"\bcgst\s*(\d+(?:\.\d+)?)", joined_tr)
                sg_m = re.search(r"\bsgst\s*(\d+(?:\.\d+)?)", joined_tr)
                ig_m = re.search(r"\bigst\s*(\d+(?:\.\d+)?)", joined_tr)
                slab_rate = 0.0
                if cg_m and sg_m:
                    slab_rate = round2(float(cg_m.group(1)) + float(sg_m.group(1)))
                elif ig_m:
                    slab_rate = round2(float(ig_m.group(1)))
                if slab_rate == 0.0:
                    pcts = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", joined_tr)]
                    if len(pcts) >= 2 and abs(pcts[0] - pcts[1]) <= 0.1 and (pcts[0] + pcts[1]) in (0, 3, 5, 12, 18, 28):
                        slab_rate = round2(pcts[0] + pcts[1])
                    elif len(pcts) == 1 and pcts[0] in (0, 3, 5, 12, 18, 28):
                        slab_rate = round2(pcts[0])
                if slab_rate > 0 and taxable_col_idx != -1 and taxable_col_idx < len(tr) and re.search(r"\d", tr[taxable_col_idx]):
                    summary_slabs[slab_rate] = round2(summary_slabs.get(slab_rate, 0.0) + clean_num(tr[taxable_col_idx]))
                if slab_rate > 0 and hsn_col_idx != -1 and hsn_col_idx < len(tr):
                    h_digits = re.sub(r"[^0-9]", "", tr[hsn_col_idx])
                    if 4 <= len(h_digits) <= 8:
                        hsn_rate_map[h_digits] = slab_rate

                if "total" in joined_tr:
                    if len(tr) == len(hdr_cells) and any("net payable" in h or "credit note" in h or "taxable" in h for h in hdr_cells):
                        for h, val in zip(hdr_cells, tr):
                            if not re.search(r"\d", val):
                                continue
                            v = clean_num(val)
                            if "credit note" in h and v > 0:
                                summary_credit_note = v
                            elif "net payable" in h and v > 0:
                                summary_net_payable = v
                            elif "taxable" in h and v > 0:
                                summary_taxable = v
                    nums = [clean_num(c) for c in tr if re.search(r"\d", c)]
                    if len(nums) >= 4 and abs((nums[1] + nums[2]) - nums[3]) <= 0.2:
                        summary_taxable, summary_cgst, summary_sgst = nums[0], nums[1], nums[2]
                    elif len(nums) >= 3 and abs(nums[1] - nums[2]) <= 0.2:
                        summary_taxable, summary_cgst, summary_sgst = nums[0], nums[1], nums[2]

    # Parse inline text tax summary line (e.g. "Tax Per 5% Taxable 2477.14 SGST 61.93 CGST 61.93 IGST 0")
    for m_in in re.finditer(
        r"Tax\s*(?:Per|%)?\s*(\d+(?:\.\d+)?)\s*%?\s*Taxable\s*[:\-]?\s*([0-9,]+\.\d{2})\s*"
        r"(?:SGST\s*[:\-]?\s*([0-9,]+(?:\.\d{2})?)\s*CGST\s*[:\-]?\s*([0-9,]+(?:\.\d{2})?)|"
        r"CGST\s*[:\-]?\s*([0-9,]+(?:\.\d{2})?)\s*SGST\s*[:\-]?\s*([0-9,]+(?:\.\d{2})?))"
        r"(?:\s*IGST\s*[:\-]?\s*([0-9,]+(?:\.\d{2})?))?",
        rev_plain_clean,
        re.IGNORECASE,
    ):
        r_pct = clean_num(m_in.group(1))
        r_tx = clean_num(m_in.group(2))
        if m_in.group(3) is not None:
            r_sg, r_cg = clean_num(m_in.group(3)), clean_num(m_in.group(4))
        else:
            r_cg, r_sg = clean_num(m_in.group(5)), clean_num(m_in.group(6))
        r_ig = clean_num(m_in.group(7))
        if r_tx > 0:
            summary_taxable = round2(summary_taxable + r_tx) if summary_slabs else r_tx
            summary_cgst = round2(summary_cgst + r_cg) if summary_slabs else r_cg
            summary_sgst = round2(summary_sgst + r_sg) if summary_slabs else r_sg
            summary_igst = round2(summary_igst + r_ig) if summary_slabs else r_ig
            if r_pct > 0:
                summary_slabs[round2(r_pct)] = r_tx

    if credit_note == 0.0 and summary_credit_note > 0:
        credit_note = round2(summary_credit_note)
    if summary_net_payable > 0 and (inv_total == 0.0 or summary_credit_note > 0 or abs(inv_total - summary_net_payable) <= 1.0):
        inv_total = round2(summary_net_payable)

    raw_only_rows = [r for r in rows if r.get("_raw_amt_only", 0.0) > 0]
    if raw_only_rows and len(raw_only_rows) == len(rows):
        sum_raw_only = round2(sum(r["_raw_amt_only"] for r in rows))
        has_tax_payble_hint = bool(re.search(r"\b(?:cgst|sgst|igst)\s*pay(?:a)?ble\b", plain, re.IGNORECASE))
        is_tax_excl = (
            (summary_taxable > 0 and abs(sum_raw_only - summary_taxable) <= 1.0)
            or (inv_total > sum_raw_only + 1.0 and (
                "output cgst" in plain.lower()
                or "output sgst" in plain.lower()
                or has_tax_payble_hint
                or (summary_cgst + summary_sgst + summary_igst) > 0
            ))
        )
        if is_tax_excl:
            for r in rows:
                tx = round2(r["_raw_amt_only"])
                rt = r["gstRate"]
                half = round2(tx * rt / 200.0)
                r["taxable"] = tx
                r["cgst"] = half
                r["sgst"] = half
                r["lineTotal"] = round2(tx + 2.0 * half)
    for r in rows:
        r.pop("_raw_amt_only", None)
        if r["quantity"] > 0 and r["rate"] > 0 and r["taxable"] > 0 and abs((r["quantity"] * r["rate"] - r["discount"]) - r["taxable"]) > max(1.5, r["taxable"] * 0.01):
            if r["lineTotal"] > r["taxable"] and abs((r["quantity"] * r["rate"] - r["discount"]) - r["lineTotal"]) <= max(1.5, r["lineTotal"] * 0.01):
                r["rate"] = round2((r["taxable"] + r["discount"]) / r["quantity"])
            elif r["discount"] > 0 and abs((r["quantity"] * r["rate"]) - r["taxable"]) <= max(1.5, r["taxable"] * 0.01):
                r["rate"] = round2((r["taxable"] + r["discount"]) / r["quantity"])

    # Single-row digit-slip repair via Net Amount - Tax & slab taxable summary cross-check
    for r in rows:
        if r["lineTotal"] > 0 and abs((r["taxable"] + r["cgst"] + r["sgst"] + r["igst"] + r["cess"]) - r["lineTotal"]) > 0.25:
            row_tax = round2(r["cgst"] + r["sgst"] + r["igst"] + r["cess"])
            cand_tx = round2(r["lineTotal"] - row_tax)
            tax_only = round2(r["cgst"] + r["sgst"] + r["igst"])
            rate_ok = r["gstRate"] == 0.0 or abs(cand_tx * (r["gstRate"] / 100.0) - tax_only) <= max(0.35, cand_tx * 0.005)
            qty_rate_ok = True
            if r["quantity"] > 0 and r["rate"] > 0:
                qr_tx = round2(r["quantity"] * r["rate"] - r["discount"])
                qty_rate_ok = abs(qr_tx - cand_tx) < abs(qr_tx - r["taxable"])
            if cand_tx > 0 and rate_ok and qty_rate_ok:
                snapped = cand_tx
                if r["gstRate"] in summary_slabs:
                    other_tx = sum(
                        o["taxable"] for o in rows if o is not r and abs(o["gstRate"] - r["gstRate"]) <= 0.05
                    )
                    slab_res = round2(summary_slabs[r["gstRate"]] - other_tx)
                    if abs(slab_res - cand_tx) <= 0.10:
                        snapped = slab_res
                r["taxable"] = round2(snapped)

    taxable_total = round2(sum(r["taxable"] for r in rows)) if rows else round2(summary_taxable)
    discount_total = round2(sum(r.get("discount", 0.0) for r in rows)) if rows else 0.0
    cgst_total = round2(sum(r["cgst"] for r in rows)) if (rows and sum(r["cgst"] for r in rows) > 0) else round2(summary_cgst or footer_hints.get("cgstTotal", 0.0))
    sgst_total = round2(sum(r["sgst"] for r in rows)) if (rows and sum(r["sgst"] for r in rows) > 0) else round2(summary_sgst or footer_hints.get("sgstTotal", 0.0))
    igst_total = round2(sum(r["igst"] for r in rows)) if (rows and sum(r["igst"] for r in rows) > 0) else round2(summary_igst or footer_hints.get("igstTotal", 0.0))

    for row_item in rows:
        if row_item["gstRate"] == 0.0 and row_item.get("hsnSac") in hsn_rate_map:
            row_item["gstRate"] = hsn_rate_map[row_item["hsnSac"]]
        elif row_item["gstRate"] == 0.0 and len(summary_slabs) == 1:
            row_item["gstRate"] = next(iter(summary_slabs.keys()))
        if row_item["taxable"] > 0 and row_item["gstRate"] > 0 and (row_item["cgst"] + row_item["sgst"] + row_item["igst"]) == 0.0:
            if igst_total > 0 and cgst_total == 0 and sgst_total == 0:
                tax_amt = round2(row_item["taxable"] * row_item["gstRate"] / 100.0)
                row_item["igst"] = tax_amt
                row_item["lineTotal"] = round2(row_item["taxable"] + tax_amt)
            else:
                half = round2(row_item["taxable"] * row_item["gstRate"] / 200.0)
                row_item["cgst"] = half
                row_item["sgst"] = half
                row_item["lineTotal"] = round2(row_item["taxable"] + 2.0 * half)

    if inv_total == 0.0 and taxable_total > 0:
        inv_total = round2(taxable_total + cgst_total + sgst_total + igst_total - credit_note + round_off)
    elif inv_total > 0 and taxable_total > 0:
        computed_no_ro = round2(taxable_total + cgst_total + sgst_total + igst_total - credit_note)
        if round_off == 0.0:
            residual = round2(inv_total - computed_no_ro)
            if 0.0 < abs(residual) <= 1.00:
                round_off = residual
        elif abs((computed_no_ro + round_off) - inv_total) > 0.25 and abs((computed_no_ro - round_off) - inv_total) <= 0.25:
            round_off = -round_off

    raw_dict = {
        "seller": {"name": seller_name, "gstin": seller_gstin},
        "buyer": {"name": buyer_name, "gstin": buyer_gstin},
        "invoiceNumber": inv_no,
        "invoiceDate": inv_date,
        "documentType": detect_document_type(first_page_lines if len(page_texts) > 1 else plain_lines, qr_einvoice),
        "placeOfSupply": extract_place_of_supply(header_scope_lines),
        "reverseCharge": bool(re.search(r"Reverse\s+Charge\s*[:\-]?\s*Yes\b", plain, re.IGNORECASE)),
        "taxableTotal": taxable_total,
        "discountTotal": discount_total,
        "cgstTotal": cgst_total,
        "sgstTotal": sgst_total,
        "igstTotal": igst_total,
        "cessTotal": 0.0,
        "creditNoteTotal": credit_note,
        "roundOff": round_off,
        "invoiceTotal": inv_total,
        "rows": rows,
        "rawTablesHtml": extract_html_tables(raw_text),
    }
    return normalize_canonical_dict(raw_dict, raw_text, qr_einvoice)


def normalize_canonical_dict(obj: Dict[str, Any], raw_text: str = "", qr_einvoice: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    seller_obj = obj.get("seller") if isinstance(obj.get("seller"), dict) else {}
    buyer_obj = obj.get("buyer") if isinstance(obj.get("buyer"), dict) else {}
    s_gstin_raw = seller_obj.get("gstin") or obj.get("sellerGstin") or ""
    b_gstin_raw = buyer_obj.get("gstin") or obj.get("buyerGstin") or ""
    pan_hints = re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", (raw_text or "").upper())
    s_gstin, _, _ = repair_gstin(s_gstin_raw, pan_hints=pan_hints)
    b_gstin, _, _ = repair_gstin(b_gstin_raw, pan_hints=pan_hints)

    inv_no = str(obj.get("invoiceNumber") or obj.get("invoiceNo") or "").strip()
    inv_date = normalize_date(str(obj.get("invoiceDate") or ""))

    norm_rows: List[Dict[str, Any]] = []
    for r in (obj.get("rows") or []):
        if not isinstance(r, dict):
            continue
        desc = str(r.get("description") or r.get("productName") or "").strip()
        hsn = re.sub(r"[^0-9]", "", str(r.get("hsnSac") or r.get("hsn") or ""))
        qty = clean_num(r.get("quantity") or r.get("qty"))
        unit = str(r.get("unit") or "").strip()
        rate_price = clean_num(r.get("rate") or r.get("unitPrice"))
        disc = clean_num(r.get("discount"))
        taxable = clean_num(r.get("taxable") or r.get("taxableAmount"))
        gst_rate = clean_num(r.get("gstRate") or r.get("gstPercent"))
        cgst = clean_num(r.get("cgst"))
        sgst = clean_num(r.get("sgst"))
        igst = clean_num(r.get("igst"))
        cess = clean_num(r.get("cess"))
        lt = clean_num(r.get("lineTotal") or r.get("netAmount"))

        if taxable == 0.0 and lt > 0 and (cgst + sgst + igst) > 0:
            taxable = round2(lt - (cgst + sgst + igst + cess))
        elif taxable == 0.0 and lt > 0 and gst_rate > 0:
            taxable = round2(lt / (1.0 + gst_rate / 100.0))
        if taxable > 0 and gst_rate > 0 and (cgst + sgst + igst) == 0.0:
            half = round2(taxable * gst_rate / 200.0)
            cgst = half
            sgst = half
        if igst == 0.0 and (cgst > 0.0 or sgst > 0.0) and abs(cgst - sgst) > 0.005:
            old_sum = round2(cgst + sgst)
            chosen: Optional[float] = None
            if taxable > 0.0 and gst_rate > 0.0:
                exp_half = round2(taxable * gst_rate / 200.0)
                if abs(cgst - exp_half) <= 0.05 and abs(sgst - exp_half) <= 0.05:
                    chosen = exp_half
                elif abs(cgst - exp_half) <= 0.05 or abs(sgst - exp_half) <= 0.05:
                    chosen = cgst if abs(cgst - exp_half) <= abs(sgst - exp_half) else sgst
                elif abs(cgst - sgst) <= 0.25:
                    chosen = exp_half
            elif abs(cgst - sgst) <= 0.15:
                chosen = round2((cgst + sgst) / 2.0)
            if chosen is not None:
                cgst = round2(chosen)
                sgst = round2(chosen)
                if lt > 0.0 and abs((taxable + old_sum + cess) - lt) <= 0.25:
                    lt = round2(taxable + cgst + sgst + igst + cess)
        if lt == 0.0 and taxable > 0:
            lt = round2(taxable + cgst + sgst + igst + cess)
        if taxable > 0 and (cgst + sgst + igst) > 0:
            est = ((cgst + sgst + igst) / taxable) * 100.0
            if gst_rate == 0.0 or abs(est - gst_rate * 2.0) <= 0.6:
                for std in (0, 3, 5, 12, 18, 28):
                    if abs(est - std) <= 0.6:
                        gst_rate = float(std)
                        break

        if desc or hsn or taxable > 0 or lt > 0:
            norm_rows.append({
                "description": desc,
                "hsnSac": hsn,
                "quantity": round2(qty),
                "unit": unit,
                "rate": round2(rate_price),
                "discount": round2(disc),
                "taxable": round2(taxable),
                "gstRate": round2(gst_rate),
                "cgst": round2(cgst),
                "sgst": round2(sgst),
                "igst": round2(igst),
                "cess": round2(cess),
                "lineTotal": round2(lt),
            })

    taxable_total = round2(clean_num(obj.get("taxableTotal")))
    discount_total = round2(clean_num(obj.get("discountTotal")))
    cgst_total = round2(clean_num(obj.get("cgstTotal")))
    sgst_total = round2(clean_num(obj.get("sgstTotal")))
    igst_total = round2(clean_num(obj.get("igstTotal")))
    cess_total = round2(clean_num(obj.get("cessTotal")))
    credit_note = round2(clean_num(obj.get("creditNoteTotal")))
    round_off = round2(clean_num(obj.get("roundOff")))
    inv_total = round2(clean_num(obj.get("invoiceTotal")))

    if taxable_total == 0.0 and norm_rows:
        taxable_total = round2(sum(r["taxable"] for r in norm_rows))
    if discount_total == 0.0 and norm_rows:
        discount_total = round2(sum(r["discount"] for r in norm_rows))
    if igst_total == 0.0 and norm_rows and any((r["cgst"] > 0.0 or r["sgst"] > 0.0) for r in norm_rows):
        row_cg_sum = round2(sum(r["cgst"] for r in norm_rows))
        row_sg_sum = round2(sum(r["sgst"] for r in norm_rows))
        if cgst_total == 0.0 or sgst_total == 0.0 or abs(cgst_total - sgst_total) > 0.005:
            cgst_total = row_cg_sum
            sgst_total = row_sg_sum
    if igst_total == 0.0 and (cgst_total > 0.0 or sgst_total > 0.0) and 0.005 < abs(cgst_total - sgst_total) <= 0.15:
        avg_half = round2((cgst_total + sgst_total) / 2.0)
        cgst_total = avg_half
        sgst_total = avg_half
    if inv_total > 0.0 and taxable_total > 0.0:
        computed_no_ro = round2(taxable_total + cgst_total + sgst_total + igst_total + cess_total - credit_note)
        if abs((computed_no_ro + round_off) - inv_total) > 0.005:
            cand_ro = round2(inv_total - computed_no_ro)
            if abs(cand_ro) <= 1.00:
                round_off = cand_ro
    if igst_total == 0.0 and norm_rows:
        igst_total = round2(sum(r["igst"] for r in norm_rows))
    if cess_total == 0.0 and norm_rows:
        cess_total = round2(sum(r["cess"] for r in norm_rows))

    if qr_einvoice:
        if qr_einvoice.get("SellerGstin"):
            qg, qok, _ = repair_gstin(qr_einvoice["SellerGstin"])
            if qok:
                s_gstin = qg
        if qr_einvoice.get("BuyerGstin"):
            qg, qok, _ = repair_gstin(qr_einvoice["BuyerGstin"])
            if qok:
                b_gstin = qg
        if qr_einvoice.get("DocNo"):
            inv_no = str(qr_einvoice["DocNo"]).strip()
        if qr_einvoice.get("DocDt"):
            inv_date = normalize_date(str(qr_einvoice["DocDt"]))
        if qr_einvoice.get("TotInvVal"):
            inv_total = round2(clean_num(qr_einvoice["TotInvVal"]))

    canon = {
        "seller": {"name": str(seller_obj.get("name") or obj.get("sellerName") or "").strip(), "gstin": s_gstin},
        "buyer": {"name": str(buyer_obj.get("name") or obj.get("buyerName") or "").strip(), "gstin": b_gstin},
        "invoiceNumber": inv_no,
        "invoiceDate": inv_date,
        "documentType": str(obj.get("documentType") or "Tax Invoice").strip() or "Tax Invoice",
        "placeOfSupply": str(obj.get("placeOfSupply") or "").strip(),
        "reverseCharge": bool(obj.get("reverseCharge", False)),
        "taxableTotal": taxable_total,
        "discountTotal": discount_total,
        "cgstTotal": cgst_total,
        "sgstTotal": sgst_total,
        "igstTotal": igst_total,
        "cessTotal": cess_total,
        "creditNoteTotal": credit_note,
        "roundOff": round_off,
        "invoiceTotal": inv_total,
        "rows": norm_rows,
        "gstSlabs": build_gst_slabs(norm_rows),
        "rawTablesHtml": list(obj.get("rawTablesHtml") or []),
    }
    canon["_audit"] = audit_invoice_math(canon)
    return canon
