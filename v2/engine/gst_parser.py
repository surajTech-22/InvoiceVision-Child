from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from gst_math import audit_invoice_math, is_supported_gst_rate, is_valid_gstin, repair_gstin, round2

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
    s = re.sub(r"(\d+\.\d)\s+(\d)\b", r"\1\2", text)
    s = re.sub(r",(\d{2})(?!\d)", r".\1", s).replace(",", "")
    return [float(x) for x in re.findall(r"[-+]?\d+(?:\.\d+)?", s)]


_WORD_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_WORD_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000, "crore": 10000000, "crores": 10000000}


def _words_to_int(phrase: str) -> Optional[int]:
    toks = re.findall(r"[a-z]+", (phrase or "").lower().replace("-", " "))
    if not toks:
        return None
    total = 0
    cur = 0
    seen = False
    for tok in toks:
        if tok in ("and", "rs", "rupee", "rupees", "inr", "only", "paise", "paisa"):
            continue
        if tok in _WORD_ONES:
            cur += _WORD_ONES[tok]
            seen = True
        elif tok in _WORD_TENS:
            cur += _WORD_TENS[tok]
            seen = True
        elif tok == "hundred":
            cur = (cur or 1) * 100
            seen = True
        elif tok in _WORD_SCALES:
            total += (cur or 1) * _WORD_SCALES[tok]
            cur = 0
            seen = True
        else:
            # Unknown noise word breaks cleanly if we already parsed something
            if seen:
                continue
    return (total + cur) if seen else None


def extract_amount_in_words(plain_text: str) -> Optional[float]:
    """Extract grand total from printed Indian Amount-in-Words, skipping Tax-Amount-in-Words lines."""
    if not plain_text:
        return None
    lines = [_strip_md(re.sub(r"\|+", " ", ln)) for ln in plain_text.splitlines()]
    lines = [ln for ln in lines if ln]
    candidates: List[Tuple[int, float]] = []
    for idx, ln in enumerate(lines):
        low = ln.lower()
        prev_low = lines[idx - 1].lower() if idx > 0 else ""
        if "tax amount" in low or ("tax" in low and "in words" in low) or ("tax amount" in prev_low and "in words" in prev_low):
            continue
        phrase = ""
        priority = 0
        if re.search(r"\b(?:rupees|inr|rs\.?)\b", low) and re.search(r"\b(?:only|paise|paisa|hundred|thousand|lakh|lac|crore)\b", low):
            phrase = ln
            if "chargeable" in prev_low or "charged" in prev_low or "chargeable" in low or "charged" in low:
                priority = 2
            elif "rupees" in low or "inr" in low or "rs." in low:
                priority = 1
        elif re.search(r"(?:amount\s+(?:chargeable|charged|in\s+words)|total\s+amount\s+in\s+words)", low) and idx + 1 < len(lines):
            nxt = lines[idx + 1]
            if "tax amount" not in low:
                phrase = nxt
                priority = 2
        if not phrase:
            continue
        m_split = re.split(r"(?:(?:\band\b|&|,)\s+|\brupees?\b\s*(?=(?:[a-z\-]+\s+){1,2}(?:paise|paisa)\b))(?=(?:[a-z\-]+\s+){1,3}(?:paise|paisa)\b)", phrase, maxsplit=1, flags=re.IGNORECASE)
        if len(m_split) == 2:
            main_val = _words_to_int(m_split[0])
            paise_val = _words_to_int(m_split[1])
            if main_val is not None:
                p_num = float(paise_val) if (paise_val is not None and 0 <= paise_val < 100) else 0.0
                val = round2(main_val + p_num / 100.0)
                if val > 0:
                    candidates.append((priority, val))
                    continue
        m_paise = re.search(r"(.+?)(?:\band\b|&|\brupees?\b)\s+([a-z\-\s]+?)\s*(?:paise|paisa)\b", phrase, re.IGNORECASE)
        if m_paise:
            main_val = _words_to_int(m_paise.group(1))
            paise_val = _words_to_int(m_paise.group(2))
            if main_val is not None:
                p_num = float(paise_val) if (paise_val is not None and 0 <= paise_val < 100) else 0.0
                val = round2(main_val + p_num / 100.0)
                if val > 0:
                    candidates.append((priority, val))
                    continue
        main_val = _words_to_int(phrase)
        if main_val is not None and main_val > 0:
            candidates.append((priority, round2(float(main_val))))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _subset_match_indices(values: List[float], target: float, tol: float = 1.00, available: Optional[List[int]] = None) -> Optional[List[int]]:
    """Find subset of indices whose values sum to target within tolerance."""
    pool = list(available) if available is not None else list(range(len(values)))
    if not pool or target <= 0.0:
        return None
    if len(pool) <= 20:
        best_subset: Optional[List[int]] = None
        best_diff = tol + 1.0

        def dfs(pos: int, cur_sum: float, chosen: List[int]) -> None:
            nonlocal best_subset, best_diff
            diff = abs(cur_sum - target)
            if chosen and diff <= tol and diff < best_diff:
                best_diff = diff
                best_subset = list(chosen)
                if diff <= 0.01:
                    return
            if pos >= len(pool) or cur_sum > target + tol or best_diff <= 0.01:
                return
            idx = pool[pos]
            v = values[idx]
            if cur_sum + v <= target + tol:
                chosen.append(idx)
                dfs(pos + 1, cur_sum + v, chosen)
                chosen.pop()
            dfs(pos + 1, cur_sum, chosen)

        dfs(0, 0.0, [])
        return best_subset
    # Greedy fallback for large invoices (>20 rows)
    pool_sorted = sorted(pool, key=lambda idx: values[idx], reverse=True)
    chosen: List[int] = []
    cur = 0.0
    for idx in pool_sorted:
        if cur + values[idx] <= target + tol:
            chosen.append(idx)
            cur += values[idx]
            if abs(cur - target) <= tol:
                return sorted(chosen)
    return None


def _partition_rows_to_inclusive_slabs(row_totals: List[float], rate_targets: Dict[float, float], tol: float = 1.00) -> Optional[Dict[int, float]]:
    """Partition row indices cleanly into {row_idx: gst_rate} so each slab matches its inclusive target."""
    if not row_totals or not rate_targets:
        return None
    rates_ordered = sorted(rate_targets.keys(), key=lambda r: (0 if r == 0.0 else 1, rate_targets[r]))
    if len(row_totals) <= 18 and len(rates_ordered) <= 5:
        assignment: Dict[int, float] = {}
        remaining = list(range(len(row_totals)))

        def solve(step: int, rem: List[int]) -> bool:
            if step == len(rates_ordered) - 1:
                last_rate = rates_ordered[step]
                s = sum(row_totals[i] for i in rem)
                if abs(s - rate_targets[last_rate]) <= tol:
                    for i in rem:
                        assignment[i] = last_rate
                    return True
                return False
            r_cur = rates_ordered[step]
            tgt = rate_targets[r_cur]
            cand = _subset_match_indices(row_totals, tgt, tol=tol, available=rem)
            if not cand:
                return False
            for i in cand:
                assignment[i] = r_cur
            next_rem = [i for i in rem if i not in cand]
            if solve(step + 1, next_rem):
                return True
            for i in cand:
                assignment.pop(i, None)
            return False

        if solve(0, remaining):
            return assignment
    return None


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
    valid_extras = [re.sub(r"[^A-Za-z0-9]", "", x).upper() for x in (extra_candidates or []) if x and is_valid_gstin(x)]
    upper_text = text.upper()
    pan_hints = re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", upper_text)
    compressed_gst_lines: List[str] = []
    slash_gst_lines: List[str] = []
    for ln in upper_text.splitlines():
        if "PAN" in ln:
            comp_pan = re.sub(r"(?<=[A-Z0-9])\s+(?=[A-Z0-9])", "", ln)
            for p in re.findall(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", comp_pan):
                if p not in pan_hints:
                    pan_hints.append(p)
        if "GST" in ln:
            compressed_gst_lines.append(re.sub(r"(?<=[A-Z0-9])\s+(?=[A-Z0-9])", "", ln))
            slash_gst_lines.append(ln)
    for ex in valid_extras:
        if len(ex) == 15 and ex[2:12] not in pan_hints:
            pan_hints.append(ex[2:12])
    raw_cands = re.findall(r"\b[0-9OQD]{2}[A-Z0-9]{10}[0-9A-Z][Z2S7][0-9A-Z]\b", upper_text)
    if compressed_gst_lines:
        raw_cands.extend(re.findall(r"\b[0-9OQD]{2}[A-Z0-9]{10}[0-9A-Z][Z2S7][0-9A-Z]\b", "\n".join(compressed_gst_lines)))
    # Recover 15-char GSTINs with 1 OCR punctuation glyph (e.g. 29ABZPB5530/1ZE) when backed by PAN/extra hints
    if slash_gst_lines and (pan_hints or valid_extras):
        for s_tok in re.findall(r"\b[0-9OQD]{2}[A-Z0-9/\\|!]{10}[0-9A-Z/\\|!][Z2S7][0-9A-Z]\b", "\n".join(slash_gst_lines)):
            if "/" not in s_tok and "\\" not in s_tok and "|" not in s_tok and "!" not in s_tok:
                continue
            for p in pan_hints:
                cand_from_pan = f"{s_tok[:2]}{p}{s_tok[12:]}"
                if re.fullmatch(r"[0-9OQD]{2}[A-Z0-9]{13}", cand_from_pan) and sum(1 for a, b in zip(s_tok, cand_from_pan) if a == b) >= 13:
                    raw_cands.append(cand_from_pan)
                    break
    # Also catch 16-char OCR insertion artifacts near valid PAN hints (or near known client GSTIN PAN core)
    for c16 in re.findall(r"\b[0-9OQD]{2}[A-Z0-9]{14}\b", text.upper()):
        norm16 = re.sub(r"[^A-Z0-9]", "", c16)
        matched_c16_extra = False
        for ex in valid_extras:
            if norm16[:2] == ex[:2] and (ex[4:11] in norm16 or ex[5:12] in norm16):
                raw_cands.append(ex)
                matched_c16_extra = True
                break
        if matched_c16_extra:
            continue
        for drop_idx in range(2, 12):
            c15 = norm16[:drop_idx] + norm16[drop_idx + 1:]
            if any(sum(1 for a, b in zip(c15[2:12], p) if a == b) >= 8 for p in pan_hints):
                raw_cands.append(c15)
                break
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
            fixed, ok, reason = repair_gstin(c, pan_hints=pan_hints)
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
            if not ok and reason == "not_gstin_pattern":
                continue
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


def _expand_br_stacked_row(raw_cells: List[str], has_th: bool) -> Optional[List[List[str]]]:
    """Expand a single <tr> whose cells stack K items separated by <br>/newlines."""
    if has_th or len(raw_cells) < 3:
        return None
    split_cells: List[List[str]] = [
        [" ".join(part.split()) for part in c.splitlines() if part.strip()]
        for c in raw_cells
    ]
    num_lengths: List[int] = []
    for lines in split_cells:
        if len(lines) >= 2 and sum(1 for ln in lines if re.search(r"\d", ln)) >= 2:
            num_lengths.append(len(lines))
    if len(num_lengths) < 2:
        return None
    k = max(set(num_lengths), key=num_lengths.count)
    if k < 2 or k > 60 or num_lengths.count(k) < 2:
        return None

    out_rows: List[List[str]] = []
    for idx in range(k):
        row_i: List[str] = []
        for c_idx, lines in enumerate(split_cells):
            if not lines:
                row_i.append("")
            elif len(lines) == k:
                row_i.append(lines[idx])
            elif len(lines) == 1:
                row_i.append(lines[0] if idx == 0 else "")
            elif len(lines) > k:
                # Extra lines in text/description columns -> keep paired slice and append leftovers on last row
                if idx < k - 1:
                    row_i.append(lines[idx])
                else:
                    row_i.append(" ".join(lines[idx:]))
            else:
                row_i.append(lines[idx] if idx < len(lines) else "")
        if any(row_i):
            out_rows.append(row_i)
    return out_rows if len(out_rows) >= 2 else None


def _html_tables_to_matrices(html_text: str) -> List[List[List[str]]]:
    soup = BeautifulSoup(html_text, "lxml")
    tables = []
    for tbl in soup.find_all("table"):
        rows_mat = []
        occupied: Dict[Tuple[int, int], str] = {}
        r_idx = 0
        for tr in tbl.find_all("tr"):
            cells: List[str] = []
            raw_cells: List[str] = []
            has_th = False
            tr_cells = tr.find_all(["th", "td"])
            has_rowspan_pending = any(ri == r_idx for (ri, _) in occupied)
            c_idx = 0
            for cell in tr_cells:
                while (r_idx, c_idx) in occupied:
                    cells.append(occupied.pop((r_idx, c_idx)))
                    raw_cells.append("")
                    c_idx += 1
                if cell.name == "th":
                    has_th = True
                raw_txt = cell.get_text("\n", strip=True)
                txt = " ".join(raw_txt.split())
                colspan = max(1, int(cell.get("colspan") or 1))
                rowspan = max(1, int(cell.get("rowspan") or 1))
                cells.append(txt)
                raw_cells.append(raw_txt)
                if rowspan > 1:
                    for dr in range(1, rowspan):
                        for dc in range(colspan):
                            occupied[(r_idx + dr, c_idx + dc)] = ""
                for _ in range(colspan - 1):
                    cells.append("")
                    raw_cells.append("")
                c_idx += colspan
            while (r_idx, c_idx) in occupied:
                cells.append(occupied.pop((r_idx, c_idx)))
                raw_cells.append("")
                c_idx += 1
            expanded = None if has_rowspan_pending else _expand_br_stacked_row(raw_cells, has_th)
            if expanded:
                rows_mat.extend(expanded)
                r_idx += len(expanded)
            elif any(cells):
                rows_mat.append(cells)
                r_idx += 1
            else:
                r_idx += 1
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
    has_hsn = "hsn" in joined or "sac" in joined or bool(re.search(r"(?:^|\s)hs[n\\/|]?(?:\s|$)", joined))
    has_qty_or_rate = any(k in joined for k in ("qty", "units", "pcs", "box", "rate", "quantity", "shipped", "taxable", "amount"))
    is_tax_summary = (
        "cgst 2.5" in joined
        or ("taxable value" in joined and "central gst" in joined)
        or (has_hsn and "taxable" in joined and not has_desc and not any(k in joined for k in ("qty", "quantity", "units", "pcs", "rate", "mrp", "sku", "pack")))
        or ("cgst %" in joined and "cgst amount" in joined and not any(k in joined for k in ("qty", "quantity", "rate", "product", "item", "particulars", "description")))
        or ("class" in joined and "total gst" in joined)
    )
    is_scheme_table = ("initiative name" in joined or "credit note number" in joined)
    if is_scheme_table or is_tax_summary:
        return False
    return (has_hsn and (has_desc or has_qty_or_rate)) or (has_desc and has_qty_or_rate)


def _is_tax_summary_table(rows_mat: List[List[str]]) -> bool:
    joined_hdr = " ".join(" ".join(r) for r in rows_mat[:2]).lower()
    joined = " ".join(" ".join(r) for r in rows_mat[:3]).lower()
    if ("hsn" in joined_hdr or "sac" in joined_hdr) and "taxable" in joined_hdr and not any(
        k in joined_hdr for k in ("product", "item", "description", "particulars", "goods", "service", "qty", "quantity", "pcs", "units", "mrp", "sku", "pack")
    ):
        if "rate" not in joined_hdr or any(k in joined_hdr for k in ("central gst", "state gst", "cgst", "sgst", "igst", "total tax")):
            return True
    if "hsn" in joined_hdr and ("central gst" in joined_hdr or "taxable value" in joined_hdr) and "rate" in joined_hdr and not any(k in joined_hdr for k in ("qty", "quantity", "sku", "mrp", "gross")):
        return True
    if "cgst %" in joined_hdr and "cgst amount" in joined_hdr and not any(k in joined_hdr for k in ("qty", "quantity", "rate", "product", "item", "particulars", "description")):
        return True
    if "particulars" in joined and ("cgst 2.5" in joined or "cgst 0." in joined or "net payable" in joined):
        return True
    if ("gst%" in joined and ("taxable rs" in joined or "sale val" in joined)) or ("class" in joined and "total gst" in joined and ("taxable" in joined or "sgst" in joined or "cgst" in joined)):
        return True
    if (("taxable" in joined or "taxa." in joined) and ("cgst/ igst" in joined or "cgst/igst" in joined or "tot cgst" in joined or "cgst" in joined or "sgst" in joined)
            and not any(k in joined for k in ("product", "item", "qty", "quantity", "pcs", "hsn", "description"))):
        return True
    if (("taxable" in joined_hdr or "taxa." in joined_hdr) and any(k in joined_hdr for k in ("cgst", "sgst", "utgst", "igst", "total tax"))
            and not any(k in joined_hdr for k in ("product", "item", "description", "particulars", "goods", "service", "qty", "quantity", "pcs", "units", "mrp", "sku", "pack"))):
        return True
    if rows_mat and max((len(r) for r in rows_mat), default=0) <= 3:
        all_txt = " ".join(" ".join(r) for r in rows_mat).lower()
        has_sub = any(k in all_txt for k in ("sub total", "subtotal", "taxable", "grand total", "net amt", "net payable"))
        has_tax_lbl = any(re.search(rf"\b{k}\b", all_txt) for k in ("cgst", "sgst", "utgst", "igst"))
        has_item_hdr = any(k in joined_hdr for k in ("product", "item", "description", "particulars", "goods", "qty", "quantity", "hsn", "sac", "mrp"))
        if has_sub and has_tax_lbl and not has_item_hdr:
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


def _parse_item_rows_from_matrix(
    mat: List[List[str]],
    learned_rules: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
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
    hdr_cols = max(len(hdr1_filled), len(hdr2))
    ncols = max(len(r) for r in mat_norm)
    stacked_itc_rows = _try_parse_dual_stacked_itc_table(mat_norm, data_start)
    if stacked_itc_rows is not None:
        return stacked_itc_rows, {}
    learned_aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in ((learned_rules or {}).get("columnAliases") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    for c in range(ncols):
        t1 = hdr1_filled[c] if c < len(hdr1_filled) else ""
        t2 = hdr2[c] if c < len(hdr2) else ""
        t = (t1 + " " + t2).strip()
        if t in learned_aliases or t1 in learned_aliases:
            col_map.setdefault(learned_aliases.get(t) or learned_aliases[t1], []).append(c)
        elif "hsn" in t or "sac" in t or bool(re.fullmatch(r"hs[n\\/|]?", t.strip())):
            col_map.setdefault("hsn", []).append(c)
        elif any(k in t for k in ("product", "description", "particulars", "item", "goods", "service")):
            col_map.setdefault("desc", []).append(c)
        elif "alt" in t and ("qty" in t or "quantity" in t or "unit" in t):
            col_map.setdefault("alt_qty", []).append(c)
        elif "total unit" in t or ("qty" in t and "free" not in t) or "quantity" in t or "billed" in t:
            col_map.setdefault("qty", []).append(c)
        elif t in ("unit", "uom", "per"):
            col_map.setdefault("unit", []).append(c)
        elif "taxable" in t or "assessable" in t:
            col_map.setdefault("taxable", []).append(c)
        elif (re.match(r"^(?:gst|tax)\b", t) or re.search(r"\b(?:gst|tax)\s*(?:%|rate)\b", t)) and not any(k in t for k in ("cgst", "sgst", "utgst", "igst", "c/i", "s/ut", "amt", "amount", "desc")):
            col_map.setdefault("gstrate", []).append(c)
        elif any(re.search(rf"\b{re.escape(k)}\b", t) for k in ("tax amt", "tax amount", "gst amt", "gst amount", "tot.tax", "tot tax", "total tax")) and not any(k in t for k in ("cgst", "sgst", "utgst", "igst", "c/i", "s/ut", "taxable", "after")):
            col_map.setdefault("tax_amt", []).append(c)
        elif ("bef.tax" in t or "bef tax" in t or "base rate" in t) and "gst" not in t:
            col_map.setdefault("pref_rate", []).append(c)
        elif "rate" in t and ("incl" in t or "inclusive" in t):
            col_map.setdefault("incl_rate", []).append(c)
        elif ("rate" in t or re.fullmatch(r"r\.?\s*p\.?\s*u\.?", t)) and "gst" not in t and "cgst" not in t and "sgst" not in t and "igst" not in t and "with tax" not in t and not any(k in t for k in ("pcsrate", "pcs rate", "piece rate", "brate", "b.rate")):
            col_map.setdefault("rate", []).append(c)
        elif ("price" in t or "pcsrate" in t or "pcs rate" in t or "brate" in t) and not any(k in t for k in ("mrp", "s price", "s.price", "sale price", "selling price", "gst", "net price")):
            col_map.setdefault("alt_price", []).append(c)
        elif ("cgst" in t or "sgst" in t or "utgst" in t or re.search(r"(?:c\s*/\s*i|s\s*/\s*ut)\s*gst", t)) and ("%" in t or "rate" in t) and "amt" not in t and "amount" not in t:
            col_map.setdefault("half_gstrate", []).append(c)
        elif ("cgst" in t or "igst/ cgst" in t or re.search(r"c\s*/\s*i\s*gst", t)) and "rate" not in t2 and "%" not in t:
            col_map.setdefault("cgst", []).append(c)
        elif ("sgst" in t or "utgst" in t or re.search(r"s\s*/\s*ut\s*gst", t)) and "rate" not in t2 and "%" not in t:
            col_map.setdefault("sgst", []).append(c)
        elif "igst" in t and "rate" not in t2 and "%" not in t:
            col_map.setdefault("igst", []).append(c)
        elif "gross amt" in t or "gross amount" in t or "gross value" in t:
            col_map.setdefault("gross", []).append(c)
        elif ("disc" in t or "scheme" in t or "dis" == t.strip()) and ("%" in t or "pct" in t):
            col_map.setdefault("disc_pct", []).append(c)
        elif "disc" in t or "sch amt" in t or "scheme" in t or t.strip() in ("dis", "dis."):
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
        pcs_cols = [c for c in range(ncols) if "pcs" in hdr1_filled[c] and "sch" not in hdr1_filled[c]]
        box_cols = [c for c in range(ncols) if hdr1_filled[c].strip() in ("box", "boxes", "cs", "case", "cases")]
        if pcs_cols or box_cols:
            col_map["qty"] = pcs_cols + box_cols
        elif "alt_qty" in col_map:
            col_map["qty"] = col_map["alt_qty"]

    rows: List[Dict[str, Any]] = []
    footer_hints: Dict[str, Any] = {}
    if any(idx < len(hdr1_filled) and "incl" in hdr1_filled[idx] for idx in col_map.get("total", [])):
        footer_hints["_table_is_incl"] = True
    current_hsn = ""

    for r in mat_norm[data_start:]:
        row_text = " ".join(r).strip()
        low = row_text.lower()
        if not row_text:
            continue
        has_hsn_col_val = any(
            idx < len(r) and bool(re.search(r"(?<!\.)\b\d{4,8}\b(?![.,]\d)", r[idx]))
            for idx in col_map.get("hsn", [])
        )
        if re.search(r"\b(?:c/f|b/f|carry\s*forward|carried\s*forward|brought\s*forward|continued|contd\.?|sub\s*-?\s*total|page\s*\d+\s*of\s*\d+)\b", low):
            if not has_hsn_col_val:
                continue
        non_num_cells = [c.strip() for c in r if c.strip() and not re.fullmatch(r"[\d,().+\-%₹RsINR\s]+", c.strip())]
        label_joined = " ".join(non_num_cells).lower().strip()
        label_core = re.sub(r"^(?:less|add)\s*[:\-]\s*", "", re.sub(r"[:\-0-9.%₹Rs\s]+$", "", label_joined)).strip()
        if "output cgst" in low or bool(re.fullmatch(r"(?:(?:output|input)\s+)?c[\s\-]?gst(?:\s+(?:output|input))?(?:\s*tax)?(?:\s*@.*)?", label_joined)):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["cgstTotal"] = footer_hints.get("cgstTotal", 0.0) + nums[-1]
                m_lr = re.search(r"@\s*(\d+(?:\.\d+)?)\s*%", label_joined)
                if m_lr and nums[-1] > 0:
                    footer_hints.setdefault("_ledger_rates", []).append(("CGST", float(m_lr.group(1)), nums[-1]))
            continue
        if "output sgst" in low or bool(re.fullmatch(r"(?:(?:output|input)\s+)?s[\s\-]?gst(?:\s*/\s*utgst)?(?:\s+(?:output|input))?(?:\s*tax)?(?:\s*@.*)?", label_joined)):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["sgstTotal"] = footer_hints.get("sgstTotal", 0.0) + nums[-1]
                m_lr = re.search(r"@\s*(\d+(?:\.\d+)?)\s*%", label_joined)
                if m_lr and nums[-1] > 0:
                    footer_hints.setdefault("_ledger_rates", []).append(("SGST", float(m_lr.group(1)), nums[-1]))
            continue
        if "output igst" in low or bool(re.fullmatch(r"(?:(?:output|input)\s+)?i[\s\-]?gst(?:\s+(?:output|input))?(?:\s*tax)?(?:\s*@.*)?", label_joined)):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                footer_hints["igstTotal"] = footer_hints.get("igstTotal", 0.0) + nums[-1]
                m_lr = re.search(r"@\s*(\d+(?:\.\d+)?)\s*%", label_joined)
                if m_lr and nums[-1] > 0:
                    footer_hints.setdefault("_ledger_rates", []).append(("IGST", float(m_lr.group(1)), nums[-1]))
            continue
        if ("round off" in low or "round-off" in low) and not re.search(r"\b\d{6,8}\b", row_text):
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            if nums:
                val = nums[-1]
                if "(-)" in row_text or "less" in low:
                    val = -abs(val)
                footer_hints["roundOff"] = val
            continue
        is_summary_label_row = bool(
            re.fullmatch(
                r"(?:taxable\s*(?:value|val|amt|amount)|net\s*(?:amt|amount|payable)|(?:gross|collectable|receivable|bill)\s*(?:amt|amount)|"
                r"total\s*(?:amount|amt|value)|sub\s*total|subtotal|grand\s*total|ut\s*/\s*sgst|cgst|sgst|igst|cess|"
                r"(?:(?:bill|cash|trade|spl|special|scheme|sch|other)\s*)?disc(?:ount)?(?:\s+allowed)?(?:\s*[:%0-9.\-]*))(?:\s*[:\-])?",
                label_core,
            )
            or re.match(r"^(?:taxable\s*(?:value|amt|amount)|bill\s*discount|discount\s*allowed|collectable\s*amount|receivable\s*amt|net\s*amount)\b", label_core)
        )
        if low.startswith("total") or bool(re.search(r"\btotals?\b|\bbill\s*summary\b", low)) or re.match(r"^no\.?\s*of\s*items", low) or (
            is_summary_label_row and not has_hsn_col_val and len(rows) > 0
        ):
            tot_col_nums = [
                clean_num(r[idx])
                for idx in col_map.get("total", [])
                if idx < len(r) and re.search(r"\d", r[idx])
            ]
            last_num = tot_col_nums[-1] if tot_col_nums else (([clean_num(c) for c in r if re.search(r"\d", c)] or [0.0])[-1])
            if ("disc" in label_core) and (last_num != 0.0):
                footer_hints["preTaxDiscount"] = round2(footer_hints.get("preTaxDiscount", 0.0) + abs(last_num))
            elif re.search(r"collectable|receivable|net\s*(?:payable|amt|amount)|grand\s*total|^total", label_joined or low) and last_num > 0:
                footer_hints["table_total_last"] = last_num
            elif not is_summary_label_row and last_num > 0:
                footer_hints["table_total_last"] = last_num
            continue
        if not non_num_cells and len(rows) > 0:
            nums = [clean_num(c) for c in r if re.search(r"\d", c)]
            running_tot = round2(sum(x["lineTotal"] for x in rows))
            if nums and abs(nums[-1] - running_tot) <= 1.50:
                footer_hints["subtotal"] = nums[-1]
                continue

        hsn = ""
        for idx in col_map.get("hsn", []):
            if idx < len(r):
                h_cell = re.sub(r"\.0+\b", "", r[idx].strip())
                m = re.search(r"\b(\d{4,8})\b", h_cell)
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

        overwide = max(0, len(r) - hdr_cols)
        use_right_shift = False
        if overwide > 0 and hdr_cols >= 6 and r[-1].strip():
            tot_cols = col_map.get("total", [])
            gr_cols = col_map.get("gstrate", [])
            has_pct_shift = any(
                idx < len(r) and "%" not in r[idx] and (idx + overwide) < len(r) and "%" in r[idx + overwide]
                for idx in gr_cols
            )
            has_tot_shift = bool(tot_cols) and any(
                idx < len(r) and (not r[idx].strip() or clean_num(r[idx]) <= 100.0) and (idx + overwide) == len(r) - 1
                for idx in tot_cols
            )
            use_right_shift = has_pct_shift or has_tot_shift or bool((learned_rules or {}).get("rightAlignOverwideRows"))
        shift_pivot = max(col_map.get("qty") or col_map.get("desc") or col_map.get("hsn") or [hdr_cols // 2])

        def _row_idx(idx: int) -> int:
            if use_right_shift and idx > shift_pivot and (idx + overwide) < len(r):
                return idx + overwide
            return idx

        def pick_num(key: str) -> float:
            indices = [_row_idx(i) for i in col_map.get(key, [])]
            if key in ("taxable", "cgst", "sgst", "igst", "total", "tax_amt", "gross", "disc"):
                for idx in indices:
                    if idx < len(r) and "%" not in r[idx] and re.search(r"\d", r[idx]):
                        m_sp = re.fullmatch(r"\s*(?:₹|Rs\.?|INR)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*|\d{3,})\s+(\d{2})\s*", r[idx].strip(), re.IGNORECASE)
                        if m_sp and "." not in r[idx]:
                            big = m_sp.group(1).replace(",", "")
                            return float(f"{big}.{m_sp.group(2)}")
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
            for raw_idx in col_map.get(key, []):
                idx = _row_idx(raw_idx)
                if idx < len(r) and re.search(r"\d", r[idx]):
                    nums = parse_nums_in_cell(r[idx])
                    m_u = re.search(r"\d\s*([A-Za-z]{1,6})\b", r[idx])
                    sub_u = ""
                    if not m_u and key == "qty" and raw_idx < len(hdr2):
                        h_tok = hdr2[raw_idx].strip()
                        if re.fullmatch(r"[a-z]{1,6}", h_tok) and h_tok not in ("qty", "na"):
                            sub_u = h_tok.capitalize() if len(h_tok) > 2 else h_tok.upper()
                    if nums:
                        val = nums[0]
                        u_txt = m_u.group(1).strip() if m_u else sub_u
                        if key == "qty" and len(col_map.get(key, [])) > 1 and val == 0.0:
                            if first_zero is None:
                                first_zero = (val, u_txt)
                            continue
                        if key == "qty" and not u_txt and raw_idx < len(hdr1_filled):
                            h_u = hdr1_filled[raw_idx].strip().upper()
                            if h_u in ("BOX", "PCS", "CS"):
                                u_txt = h_u
                        return val, u_txt
            return first_zero if first_zero is not None else (0.0, "")

        qty, qty_unit = pick_first_num("qty")
        unit = ""
        for raw_idx in col_map.get("unit", []):
            idx = _row_idx(raw_idx)
            if idx < len(r) and r[idx].strip():
                unit = r[idx].strip()
                break
        if not unit:
            unit = qty_unit
        rate_price = pick_num("rate")
        gross = pick_num("gross")
        disc_parts = []
        disc_pct_vals = []
        for raw_d_idx in col_map.get("disc", []):
            d_idx = _row_idx(raw_d_idx)
            if d_idx < len(r) and re.search(r"\d", r[d_idx]):
                nums = parse_nums_in_cell(r[d_idx])
                if not nums:
                    continue
                if "%" in r[d_idx]:
                    disc_pct_vals.append(nums[-1])
                else:
                    disc_parts.append(nums[-1])
        for raw_dp_idx in col_map.get("disc_pct", []):
            dp_idx = _row_idx(raw_dp_idx)
            if dp_idx < len(r) and re.search(r"\d", r[dp_idx]):
                nums = parse_nums_in_cell(r[dp_idx])
                if nums:
                    disc_pct_vals.append(nums[-1])
        disc = round2(sum(disc_parts))
        taxable = pick_num("taxable")
        if disc < 0 and gross > 0:
            if taxable == 0.0 or abs((gross - abs(disc)) - taxable) <= 0.50:
                disc = abs(disc)
        if taxable == 0.0 and gross > 0:
            taxable = round2(gross - disc)
        gst_rate = 0.0
        combined_tax_from_rate_cell = 0.0
        for raw_gr_idx in col_map.get("gstrate", []):
            gr_idx = _row_idx(raw_gr_idx)
            if gr_idx < len(r) and re.search(r"\d", r[gr_idx]):
                gr_cell = r[gr_idx]
                m_pct = re.search(r"(\d+(?:\.\d+)?)\s*%", gr_cell)
                if m_pct:
                    pct_val = clean_num(m_pct.group(1))
                    if is_supported_gst_rate(pct_val):
                        gst_rate = pct_val
                    # Catch combined GST cells like "₹ 17.86 (5%)" where the amount precedes (pct%)
                    stripped_pct = gr_cell[:m_pct.start()] + " " + gr_cell[m_pct.end():]
                    extra_nums = parse_nums_in_cell(stripped_pct)
                    if extra_nums:
                        combined_tax_from_rate_cell = extra_nums[-1]
                else:
                    nums_gr = parse_nums_in_cell(gr_cell)
                    if nums_gr:
                        gst_rate = nums_gr[0]
                if gst_rate > 0 or "%" in gr_cell:
                    break
        if gst_rate == 0.0 and "half_gstrate" in col_map:
            hr, _ = pick_first_num("half_gstrate")
            if hr in (0, 1.5, 2.5, 6, 9, 14):
                gst_rate = hr * 2.0
        def _pick_tax_amt_and_rate(key: str) -> Tuple[float, float]:
            """Extract tax amount + optional inline rate from cells like '₹ 18.10 (2.5%)' or '9.00% 24.71'."""
            for raw_idx in col_map.get(key, []):
                idx = _row_idx(raw_idx)
                if idx < len(r) and re.search(r"\d", r[idx]):
                    cell = r[idx].strip()
                    m_pct = re.search(r"\(?\s*(\d+(?:\.\d+)?)\s*%\s*\)?", cell)
                    pct_v = clean_num(m_pct.group(1)) if m_pct else 0.0
                    stripped = (cell[:m_pct.start()] + " " + cell[m_pct.end():]) if m_pct else cell
                    m_sp = re.fullmatch(r"\s*(?:₹|Rs\.?|INR)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*|\d{3,})\s+(\d{2})\s*", stripped.strip(), re.IGNORECASE)
                    if m_sp and "." not in stripped:
                        big = m_sp.group(1).replace(",", "")
                        return float(f"{big}.{m_sp.group(2)}"), pct_v
                    nums = parse_nums_in_cell(stripped)
                    if nums:
                        return nums[-1], pct_v
                    nums_raw = parse_nums_in_cell(cell)
                    if nums_raw and not m_pct:
                        return nums_raw[-1], 0.0
            return 0.0, 0.0

        cgst, cg_inline_pct = _pick_tax_amt_and_rate("cgst")
        sgst, sg_inline_pct = _pick_tax_amt_and_rate("sgst")
        igst, ig_inline_pct = _pick_tax_amt_and_rate("igst")
        if gst_rate == 0.0:
            if ig_inline_pct > 0 and is_supported_gst_rate(ig_inline_pct):
                gst_rate = ig_inline_pct
            elif (cg_inline_pct > 0 or sg_inline_pct > 0):
                comb_inline = round2(cg_inline_pct + sg_inline_pct if (cg_inline_pct > 0 and sg_inline_pct > 0) else 2.0 * (cg_inline_pct or sg_inline_pct))
                if is_supported_gst_rate(comb_inline):
                    gst_rate = comb_inline
        combined_tax_col = pick_num("tax_amt")
        if combined_tax_col == 0.0 and combined_tax_from_rate_cell > 0.0:
            combined_tax_col = combined_tax_from_rate_cell
        tax_from_combined = False
        if cgst == 0.0 and sgst == 0.0 and igst == 0.0 and combined_tax_col > 0:
            half = _equal_local_tax_half(taxable, gst_rate, combined_tax_col)
            cgst = half
            sgst = half
            tax_from_combined = True
        line_total = pick_num("total")
        if disc == 0.0 and disc_pct_vals and qty > 0 and rate_price > 0:
            dpct = disc_pct_vals[0]
            if 0.0 < dpct < 100.0:
                cand_disc = round2(qty * rate_price * dpct / 100.0)
                target_tx = taxable if taxable > 0 else line_total
                if target_tx > 0 and abs((qty * rate_price - cand_disc) - target_tx) <= max(1.50, target_tx * 0.01):
                    disc = cand_disc

        # Handle Tally <br>-merged trailing tax/round-off ledger lines inside the last item row
        tot_indices = [_row_idx(i) for i in col_map.get("total", [])]
        if tot_indices and tot_indices[0] < len(r):
            raw_tot_nums = parse_nums_in_cell(r[tot_indices[0]])
            m_ledgers = re.search(
                r"(?:\s+((?:(?:output|input)\s+)?(?:c[\s\-]?gst|s[\s\-]?gst|i[\s\-]?gst|round\s*[-]?\s*off))){1,4}\s*$",
                desc,
                re.IGNORECASE,
            )
            if m_ledgers and len(raw_tot_nums) >= 2:
                toks = re.findall(r"(?:(?:output|input)\s+)?(?:c[\s\-]?gst|s[\s\-]?gst|i[\s\-]?gst|round\s*[-]?\s*off)", m_ledgers.group(0), re.IGNORECASE)
                if len(raw_tot_nums) >= 1 + len(toks):
                    taxable = raw_tot_nums[0]
                    line_total = 0.0
                    for tok, num in zip(toks, raw_tot_nums[1:1 + len(toks)]):
                        tl = re.sub(r"[\s\-]+", "", tok.lower())
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

    # Detect MARG ERP half-rate SGST/CGST columns (e.g. 2.50 / 9.00 in SGST/CGST columns on tax-inclusive items)
    if rows and "taxable" not in col_map and "cgst" in col_map and "sgst" in col_map:
        half_rate_hits = 0
        rate_eligible = 0
        for rw in rows:
            cg_v, sg_v, lt_v = rw["cgst"], rw["sgst"], rw["lineTotal"]
            if (cg_v > 0 or sg_v > 0) and lt_v > 0:
                rate_eligible += 1
                comb = round2(cg_v + sg_v)
                if abs(cg_v - sg_v) <= 0.01 and any(abs(comb - s) <= 0.05 for s in (0, 3, 5, 12, 18, 28, 40)):
                    q_v, r_v, d_v = rw["quantity"], rw["rate"], rw["discount"]
                    if q_v > 0 and r_v > 0:
                        incl_est = round2((q_v * r_v - d_v) * (1.0 + comb / 100.0))
                        excl_diff = abs(((q_v * r_v - d_v) + cg_v + sg_v) - lt_v)
                        if abs(incl_est - lt_v) <= max(2.0, lt_v * 0.015) and excl_diff > 2.0:
                            half_rate_hits += 1
        if rate_eligible > 0 and half_rate_hits * 2 >= rate_eligible:
            for rw in rows:
                comb = round2(rw["cgst"] + rw["sgst"])
                lt_v = rw["lineTotal"]
                if lt_v > 0 and comb > 0:
                    rw["gstRate"] = comb
                    tx_v = round2(lt_v / (1.0 + comb / 100.0))
                    half = _equal_local_tax_half(tx_v, comb, round2(lt_v - tx_v))
                    if abs((tx_v + 2.0 * half) - lt_v) <= 0.02:
                        tx_v = round2(lt_v - 2.0 * half)
                    rw["taxable"] = tx_v
                    rw["cgst"] = half
                    rw["sgst"] = half

    return rows, footer_hints


_PARTY_NOISE_PREFIX_RE = re.compile(
    r"^(?:page\s+\d+|print\s+copy|pan(?:\s+no)?|fssai(?:\s+(?:no|lic))?|essai(?:\s+lic)?|gst(?:\s*(?:no|num|number))?\s*:|gstin(?:/uin)?|gstn(?:\s+no)?|state(?:\s+name|\s+code)?|"
    r"phone|ph(?:\s+no)?|mob(?:ile)?|contact|email|e-?mail|cin|van|beat|order\s*(?:no|number)|customer\s+order|dse\s+name|"
    r"salesperson|eway|e-?way|irn\b|tkn\b|ack\.?\s*(?:no|date)|e-?inv|from|to|buyer(?:\s*\(bill\s*to\))?|"
    r"bill\s*to(?:\s+gstin)?|billed\s*to|ship\s*to(?:\s+gstin)?|shipping\s+(?:address|date)|supplier\s+address|registered\s+address|customer\s+(?:address|details)|"
    r"cust\.?\s*code|party\s+(?:mobile|gstin)|branch\s+name|channel|tax\s+type|place\s+of\s+(?:sale|supply)|mode\s+of\s+payment|"
    r"cn\s+(?:number|date)|sdp\s+id|number\s+of\s+totes|ids?\s+of\s+totes|scan\s+this\s+qr|"
    r"date\b|dated\b|inv(?:oice)?\s*(?:no|number|date|dt)|bill\s*(?:no|number|date|dt)|doc(?:ument)?\s*(?:no|number|date)|voucher\s*(?:no|number)|sm\s+name|rt\s+name|all\s+taxes\s+are|"
    r"gst\s+invoice(?:/cash)?|tax\s+invoice(?:\s*\(credit\))?|bill\s+of\s+supply|original(?:\s+for\s+recipient)?|"
    r"duplicate|triplicate|reverse\s+charge|for\s+)\b",
    re.IGNORECASE,
)

_ADDRESS_HINT_RE = re.compile(
    r"\b(?:main\b|cross|road|rd\b|street|st\b|yard|apmc|a\s*p\s*m\s*c|ayard|nagar|puram|phase|plot|industrial|layout|extension|ddpi|d\.?d\.?p\.?i|circle|enclave|survey|"
    r"ward\s+no|pin\s*code|near|beside|opp\.?|bengaluru|tumkur|thumkur|tumakuru|karnataka|india|"
    r"k(?:ha|at|ath)a\s+no|bata?wadi|balawadi|mandipet|belagumba)\b",
    re.IGNORECASE,
)


def _strip_md(s: str) -> str:
    s = re.sub(r"[*#`\\]+", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


_BUSINESS_KEYWORD_RE = re.compile(
    r"\b(?:enterprises|traders|trading|marketing|distributors|agencies|agro|foods|pvt\s+ltd|private\s+limited|llp|limited|ltd\.?|inc\.?|corp\.?|company|wholesale|retail|cash\s+and\s+carry|stores|industries)\b",
    re.IGNORECASE,
)


def _clean_party_name(s: str) -> str:
    s = _strip_md(s)
    # Strip wrapper parentheses like "(Registered as Metro Cash and Carry India Limited)"
    s = re.sub(r"^\(\s*(?:registered\s+as\s+)?(.+?)\s*\)$", r"\1", s, flags=re.IGNORECASE)
    # Strip explicit label prefixes ("Party Name : BALAJI...", "Company known as ...", "M/s. ...")
    s = re.sub(r"^(?:party\s*name|customer\s*name|buyer\s*name|supplier\s*name|seller\s*name|company\s+known\s+as|formerly\s+known\s+as|registered\s+as|m/s\.?)\s*[:\-]?\s+", "", s, flags=re.IGNORECASE)
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
    if _ADDRESS_HINT_RE.search(s) and not _BUSINESS_KEYWORD_RE.search(s):
        return ""
    if re.fullmatch(r"[\d\W]+", s) or re.match(r"^[0-9]{6,}", s):
        return ""
    if len(re.findall(r"[A-Za-z]", s)) < 3:
        return ""
    return s[:120]


def _extract_party_name_near(lines: List[str], target_gstin: str, role_keywords: Tuple[str, ...], fallback_top: bool, sig_hint: str = "") -> str:
    clean_lines = [_strip_md(ln) for ln in lines[:65]]
    clean_lines = [ln for ln in clean_lines if ln]

    def _with_top_brand_prefix(name: str) -> str:
        if fallback_top and clean_lines:
            top_brand = _clean_party_name(clean_lines[0])
            if (
                top_brand
                and re.fullmatch(r"[A-Z][A-Z0-9&.\-]{2,15}", top_brand)
                and top_brand.lower() not in name.lower()
                and re.match(r"^(?:cash\s+and\s+carry|wholesale|retail|india\s+ltd|private\s+ltd|pvt\.?\s*ltd)\b", name, re.IGNORECASE)
            ):
                return f"{top_brand} {name}"[:120]
        return name

    # 1. Explicit role label on line (e.g. "Party Name : BALAJI..." or "To BALAJI TRADING CO" or "From:\nVEERABHADRESHWARA...")
    for i, ln in enumerate(clean_lines[:55]):
        low = ln.lower()
        if any(noise in low for noise in ("original for", "duplicate for", "triplicate for", "for recipient", "supplier address", "registered address", "shipping address")):
            continue
        m_direct = re.match(r"^(?:to|from|party\s*name|customer\s*name|buyer\s*name|supplier\s*name|seller\s*name)\s*[:\-]?\s+(.+)$", ln, re.IGNORECASE)
        if m_direct and (
            (fallback_top and low.startswith(("from", "supplier", "seller")))
            or (not fallback_top and low.startswith(("to", "party", "customer", "buyer")))
        ):
            after = _clean_party_name(m_direct.group(1))
            if after:
                return _with_top_brand_prefix(after)
        if any(k in low for k in role_keywords):
            if ":" in ln:
                after = _clean_party_name(ln.split(":", 1)[1])
                if after:
                    return _with_top_brand_prefix(after)
            for nxt in range(1, 4):
                if i + nxt < len(clean_lines):
                    cand = _clean_party_name(clean_lines[i + nxt])
                    if cand:
                        return _with_top_brand_prefix(cand)

    # 2. Walk near target GSTIN line (scoring seller candidates so business names beat closer street/locality lines)
    if target_gstin:
        sig_norm = re.sub(r"[^A-Z0-9]", "", (sig_hint or "").upper())
        for i, ln in enumerate(clean_lines[:60]):
            if target_gstin in re.sub(r"[^A-Za-z0-9]", "", ln).upper():
                if not fallback_top:
                    for back in range(1, 9):
                        if i - back >= 0:
                            cand = _clean_party_name(clean_lines[i - back])
                            if cand:
                                return cand
                else:
                    seller_cands: List[Tuple[int, str]] = []
                    for back in range(1, 10):
                        if i - back < 0:
                            break
                        prev_low = clean_lines[i - back].lower()
                        if re.match(r"^(?:m/s|bill(?:ed)?\s*to|buyer|ship(?:ped)?\s*to)\b", prev_low):
                            break
                        cand = _clean_party_name(clean_lines[i - back])
                        if cand and not any(re.match(r"^(?:m/s|bill(?:ed)?\s*to|buyer)\b", clean_lines[k].lower()) for k in range(max(0, i - back - 2), i - back)):
                            sc = 0
                            cand_norm = re.sub(r"[^A-Z0-9]", "", cand.upper())
                            if _BUSINESS_KEYWORD_RE.search(cand):
                                sc += 10
                            if sig_norm and (sig_norm in cand_norm or cand_norm in sig_norm):
                                sc += 20
                            if re.fullmatch(r"[A-Z][A-Z0-9&.\-]{2,15}", cand):
                                sc -= 2
                            sc -= back  # prefer closer only as tie-breaker when no stronger keyword/signature
                            seller_cands.append((sc, cand))
                    if seller_cands:
                        seller_cands.sort(key=lambda x: x[0], reverse=True)
                        return _with_top_brand_prefix(seller_cands[0][1])
                for fwd in range(1, 4):
                    if i + fwd < len(clean_lines):
                        cand = _clean_party_name(clean_lines[i + fwd])
                        if cand:
                            return _with_top_brand_prefix(cand)

    # 3. Top header fallback for seller
    if fallback_top:
        for idx, ln in enumerate(clean_lines[:10]):
            cand = _clean_party_name(ln)
            if cand:
                if re.fullmatch(r"[A-Z][A-Z0-9&.\-]{2,15}", cand):
                    for nxt_ln in clean_lines[idx + 1:idx + 6]:
                        nxt_cand = _clean_party_name(nxt_ln)
                        if nxt_cand and cand.lower() not in nxt_cand.lower() and re.match(
                            r"^(?:cash\s+and\s+carry|wholesale|retail|india\s+ltd|private\s+ltd|pvt\.?\s*ltd)\b",
                            nxt_cand,
                            re.IGNORECASE,
                        ):
                            return f"{cand} {nxt_cand}"[:120]
                return _with_top_brand_prefix(cand)
    return ""


def _table_party_column_scores(
    tables: Optional[List[List[List[str]]]],
    gstins: List[str],
    sig_seller_hint: str,
) -> Dict[str, Tuple[int, int]]:
    """Score Seller vs Buyer using same-column cell groups in HTML header tables (avoids 2-column line interleaving)."""
    col_scores: Dict[str, Tuple[int, int]] = {}
    if not tables or not gstins:
        return col_scores
    buyer_kw = ("buyer", "bill to", "billed to", "ship to", "shipped to", "recipient", "consignee", "customer", "sold to", "party :", "party:", "fssai no : 0", "fssai no: 0")
    seller_kw = ("seller", "supplier", "from:", "consignor", "registered name", "branch name", "fssai no : 1", "fssai no: 1")
    item_hdr_kw = ("hsn", "taxable", "particulars", "description of goods", "item name", "cgst", "sgst", "igst")

    for mat in tables[:2]:
        if not mat or len(mat) < 2:
            continue
        hdr_blob = " ".join(c for c in mat[0] if c).lower()
        if any(k in hdr_blob for k in item_hdr_kw):
            continue
        col_texts: Dict[int, List[str]] = {}
        gst_locs: Dict[str, Tuple[int, int]] = {}
        for r_idx, row in enumerate(mat):
            for c_idx, cell in enumerate(row):
                txt = _strip_md(str(cell or "")).strip()
                if not txt:
                    continue
                col_texts.setdefault(c_idx, []).append(txt)
                norm_c = re.sub(r"[^A-Za-z0-9]", "", txt).upper()
                for g in gstins:
                    if g in gst_locs:
                        continue
                    pan_p = g[2:12] if len(g) == 15 else g
                    if g in norm_c or (len(pan_p) == 10 and pan_p in norm_c and ("gst" in txt.lower() or "pan" in txt.lower())):
                        gst_locs[g] = (r_idx, c_idx)
        if not gst_locs:
            continue
        min_col = min(c for _, c in gst_locs.values())
        max_col = max(c for _, c in gst_locs.values())
        for g, (_, c_idx) in gst_locs.items():
            grp = list(col_texts.get(c_idx, []))
            # Include right-adjacent metadata columns in split multi-column headers (e.g. col 2 GSTN under col 4 Customer Name)
            if c_idx > min_col:
                for adj_c, adj_lines in col_texts.items():
                    if adj_c > c_idx:
                        grp.extend(adj_lines)
            ctx = " | ".join(grp).lower()
            ctx_norm = re.sub(r"[^A-Z0-9]", "", ctx.upper())
            s_sc, b_sc = 0, 0
            if any(m in ctx for m in buyer_kw) or re.search(r"\bm/s\.?(?:\s|[:\-])", ctx):
                b_sc += 6
            if any(m in ctx for m in seller_kw):
                s_sc += 6
            if sig_seller_hint and sig_seller_hint in ctx_norm:
                s_sc += 6
            if len(gst_locs) >= 2 and max_col > min_col:
                if c_idx == min_col and b_sc == 0:
                    s_sc += 3
                elif c_idx > min_col and s_sc == 0:
                    b_sc += 3
            prev = col_scores.get(g, (0, 0))
            col_scores[g] = (max(prev[0], s_sc), max(prev[1], b_sc))
    return col_scores


def resolve_seller_buyer(
    plain: str,
    gstins: List[str],
    known_client_gstin: Optional[str] = None,
    direction_hint: str = "Auto",
    tables: Optional[List[List[List[str]]]] = None,
    learned_rules: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    upper_lines = [_strip_md(ln) for ln in plain.splitlines() if ln.strip()]
    seller_g = ""
    buyer_g = ""

    sig_seller_hint = ""
    for ln in reversed(upper_lines):
        m_for = re.search(r"\bfor\s+([A-Z][A-Z0-9 &.,'-]{3,})$", ln, re.IGNORECASE)
        if m_for:
            sig_seller_hint = re.sub(r"[^A-Z0-9]", "", m_for.group(1).upper())
            break

    party_hints = (learned_rules or {}).get("partyRoleHints") or {}
    learned_seller_anchors = tuple(str(a).lower() for a in (party_hints.get("sellerAnchors") or []) if str(a).strip())
    learned_buyer_anchors = tuple(str(a).lower() for a in (party_hints.get("buyerAnchors") or []) if str(a).strip())

    col_scores = _table_party_column_scores(tables, gstins, sig_seller_hint)
    scores: Dict[str, Tuple[int, int]] = {}
    for g in gstins:
        if g in col_scores and (col_scores[g][0] != col_scores[g][1]):
            scores[g] = col_scores[g]
            continue
        s_score = col_scores.get(g, (0, 0))[0]
        b_score = col_scores.get(g, (0, 0))[1]
        pan_part = g[2:12] if len(g) == 15 else g
        for idx, ln in enumerate(upper_lines):
            norm_ln = re.sub(r"[^A-Za-z0-9]", "", ln).upper()
            if g in norm_ln or (len(pan_part) == 10 and pan_part in norm_ln and ("gst" in ln.lower() or "pan" in ln.lower())):
                ctx_lines = upper_lines[max(0, idx - 4):idx + 2]
                ctx = " | ".join(ctx_lines).lower()
                ctx_self = ln.lower()
                if re.search(r"company['\u2019]?s\s+gstin", ctx_self):
                    s_score += 8
                elif any(m in ctx for m in ("buyer", "bill to", "billed to", "ship to", "shipped to", "recipient", "consignee", "customer", "sold to", "party :", "party:", "fssai no : 0", "fssai no: 0") + learned_buyer_anchors) or (
                    idx >= 3 and re.search(r"\bm/s\.?(?:\s|[:\-])", ctx)
                ):
                    b_score += 5
                if any(m in ctx for m in ("seller", "supplier", "from:", "consignor", "registered name", "fssai no : 1", "fssai no: 1") + learned_seller_anchors):
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
            elif hint == "auto" and seller_g == cg:
                ss, bs = scores.get(cg, (0, 0))
                if bs > ss:
                    if len(gstins) >= 2:
                        others = [x for x in gstins if x != cg]
                        seller_g = max(others, key=lambda x: scores[x][0] - scores[x][1])
                    else:
                        seller_g = ""
                    buyer_g = cg
        elif cok and buyer_g == "" and seller_g and seller_g != cg:
            # Fill buyer GSTIN from client GSTIN when only client's PAN is printed under Buyer/BillTo/ShipTo (e.g. Metro Cash & Carry)
            cg_pan = cg[2:12]
            for idx, ln in enumerate(upper_lines[:75]):
                norm_ln = re.sub(r"[^A-Za-z0-9]", "", ln).upper()
                if cg_pan in norm_ln:
                    ctx = " | ".join(upper_lines[max(0, idx - 6):idx + 3]).lower()
                    if any(m in ctx for m in ("billed to", "bill to", "ship to", "buyer", "customer", "consignee", "recipient")):
                        buyer_g = cg
                        break

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
    cleaned = (
        cleaned.replace("\u00e2\u0086\u0092", "\u2192")
        .replace("\u00e2\u2020\u2019", "\u2192")
        .replace("\u00e2\u0082\u00b9", "\u20b9")
        .replace("\u00e2\u201a\u00b9", "\u20b9")
    )
    soup = BeautifulSoup(cleaned, "lxml") if "<table" in cleaned or "<td" in cleaned else None
    return soup.get_text("\n") if soup else cleaned


def _repair_single_digit_qty_slip(qty: float, rate_price: float, disc: float, taxable: float) -> float:
    """Repair a single-digit OCR slip on Qty (e.g. 160 -> 150) when Qty * Rate differs from Taxable."""
    if (
        qty > 0
        and rate_price > 0
        and taxable > 0
        and disc == 0.0
        and abs(qty * rate_price - taxable) > max(1.5, taxable * 0.01)
    ):
        implied_qty = taxable / rate_price
        if implied_qty > 0 and abs(implied_qty - round(implied_qty)) <= 1e-4 and abs(qty - round(qty)) <= 1e-4:
            s_old = str(int(round(qty)))
            s_new = str(int(round(implied_qty)))
            if len(s_old) == len(s_new) and sum(a != b for a, b in zip(s_old, s_new)) == 1:
                return float(int(round(implied_qty)))
    return qty


def parse_document_text_to_canonical(
    raw_text: str,
    qr_einvoice: Optional[Dict[str, Any]] = None,
    known_client_gstin: Optional[str] = None,
    direction_hint: str = "Auto",
    qr_upi_meta: Optional[Dict[str, Any]] = None,
    learned_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Unified parser handling JSON VLM output, multi-page OTSL/HTML/Markdown tables, or plain OCR text."""
    obj = extract_json_object(raw_text)
    if obj and (obj.get("rows") or obj.get("invoiceNumber") or obj.get("invoiceTotal")):
        return normalize_canonical_dict(obj, raw_text, qr_einvoice, qr_upi_meta=qr_upi_meta)

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
    if isinstance(learned_rules, dict) and learned_rules.get("taxInclusive"):
        footer_hints["_table_is_incl"] = True
    last_item_hdr_rows: List[List[str]] = []

    for page_mats in page_tables_list:
        seen_page_table_fps = set()
        for mat in page_mats:
            if _is_tax_summary_table(mat):
                continue
            mat_fp = tuple(tuple(re.sub(r"\s+", " ", c).strip() for c in r) for r in mat)
            if mat_fp in seen_page_table_fps:
                continue
            seen_page_table_fps.add(mat_fp)
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
                parsed_rows, fh = _parse_item_rows_from_matrix(sub[:cut_at], learned_rules=learned_rules)
                if parsed_rows:
                    has_hdr2 = len(sub) > 1 and not any(re.search(r"\b\d{4,8}\b", c) for c in sub[1])
                    last_item_hdr_rows = sub[:2] if has_hdr2 else sub[:1]
                    all_rows.extend(parsed_rows)
                    for fk, fv in fh.items():
                        if fk in ("preTaxDiscount", "cgstTotal", "sgstTotal", "igstTotal"):
                            footer_hints[fk] = round2(footer_hints.get(fk, 0.0) + float(fv or 0.0))
                        else:
                            footer_hints[fk] = fv
                if cut_at < len(sub) and _is_tax_summary_table(sub[cut_at:]):
                    tables.append(sub[cut_at:])
            elif _is_tax_summary_table(mat):
                continue

    rows = all_rows
    if rows:
        named_rows = [r for r in rows if (r.get("description") or "").strip()]
        unnamed_summary_rows = [
            r for r in rows
            if not (r.get("description") or "").strip() and float(r.get("quantity") or 0.0) == 0.0 and float(r.get("rate") or 0.0) == 0.0
        ]
        if named_rows and unnamed_summary_rows and len(named_rows) + len(unnamed_summary_rows) == len(rows):
            named_tx = round2(sum(float(r.get("taxable") or 0.0) for r in named_rows))
            unnamed_tx = round2(sum(float(r.get("taxable") or 0.0) for r in unnamed_summary_rows))
            if named_tx > 0 and (abs(named_tx - unnamed_tx) <= 1.0 or (footer_hints.get("cgstTotal", 0.0) + footer_hints.get("sgstTotal", 0.0) + footer_hints.get("igstTotal", 0.0) > 0 and unnamed_tx > named_tx * 0.5)):
                rows = named_rows

    plain_lines_clean = [_strip_md(re.sub(r"\|+", " ", ln)) for ln in plain.splitlines()]
    plain_lines_clean = [ln for ln in plain_lines_clean if ln]
    plain_joined = "\n".join(plain_lines_clean)

    first_lines_clean = [_strip_md(re.sub(r"\|+", " ", ln)) for ln in first_page_plain.splitlines()]
    first_lines_clean = [ln for ln in first_lines_clean if ln]
    first_joined = "\n".join(first_lines_clean)

    header_scope_text = first_joined if len(page_texts) > 1 else plain_joined
    header_scope_lines = first_page_lines if len(page_texts) > 1 else plain_lines

    extra_gstin_hints: List[str] = []
    if known_client_gstin:
        extra_gstin_hints.append(known_client_gstin)
    upi_seller_gstin = str((qr_upi_meta or {}).get("sellerGstin") or "").strip().upper()
    if upi_seller_gstin and is_valid_gstin(upi_seller_gstin):
        extra_gstin_hints.append(upi_seller_gstin)

    gstins = find_gstins_in_text(header_scope_text, extra_candidates=extra_gstin_hints or None)
    if not gstins and len(page_texts) > 1:
        gstins = find_gstins_in_text(plain_joined, extra_candidates=extra_gstin_hints or None)
    sig_hint = ""
    for ln in reversed(plain_lines_clean):
        m_for = re.search(r"\bfor\s+([A-Z][A-Z0-9 &.,'-]{3,})$", ln, re.IGNORECASE)
        if m_for:
            sig_hint = m_for.group(1).strip(" .,")
            break
    seller_gstin, buyer_gstin = resolve_seller_buyer(
        first_page_plain if len(page_texts) > 1 else plain,
        gstins,
        known_client_gstin,
        direction_hint,
        tables=page_tables_list[0] if len(page_texts) > 1 else tables,
        learned_rules=learned_rules,
    )
    seller_name = _extract_party_name_near(header_scope_lines, seller_gstin, ("registered name", "supplier", "seller", "from:"), fallback_top=True, sig_hint=sig_hint)
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
            r"(?:^|\n)\s*([A-Z0-9\-/]{3,18})\s*\n\s*(?:Bill\s*No\.?|Invoice\s*No\.?|No\.?)\s*(?=$|\n)",
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
    rev_lines_bot = "\n".join(reversed(rev_plain_clean.splitlines()))
    amount_in_words = extract_amount_in_words(rev_plain_clean)

    def _clean_total_str(raw_num: str) -> float:
        m_sp = re.fullmatch(r"([0-9,]+)[ \t]+(\d{2})", raw_num.strip())
        if m_sp:
            return float(f"{m_sp.group(1).replace(',', '')}.{m_sp.group(2)}")
        return clean_num(raw_num)

    inv_total = 0.0
    for text_src, pats in (
        (rev_plain_clean, [
            r"(?:Net\s*(?:Amount\s*)?(?:Payable|Receivable)|(?:Receivable|Collectable)\s*Amt(?:ount)?|Payable\s*Amt)\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+(?:[.,]\d{2}|[ \t]+\d{2}(?!\d))|[0-9,]{3,}(?!\d))",
            r"(?:Grand\s*Total|Invoice\s*Total|Total\s*Invoice\s*Value|Total\s*Payable)\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+(?:[.,]\d{2}|[ \t]+\d{2}(?!\d))|[0-9,]{2,}(?!\d))",
            r"Net\s*Amt(?:\s*Payable)?\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+(?:[.,]\d{2}|[ \t]+\d{2}(?!\d))|[0-9,]{3,}(?!\d))",
            r"Net\s*Amount(?:\s*after\s*TAX)?\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+(?:[.,]\d{2}|[ \t]+\d{2}(?!\d))|[0-9,]{3,}(?!\d))",
            r"Bill\s*Amount\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+(?:[.,]\d{2}|[ \t]+\d{2}(?!\d))|[0-9,]{3,}(?!\d))",
        ]),
        (rev_lines_bot, [
            r"(?:^|\n)Total\b[^\n]{0,60}(?:→|₹|INR|Rs\.?)\s*([0-9,]+\.\d{2})",
            r"(?:^|\n)₹\s*([0-9,]+\.\d{2})\s*(?:\n|$)",
        ]),
    ):
        for pat in pats:
            for m in re.finditer(pat, text_src, re.IGNORECASE):
                cand_val = _clean_total_str(m.group(1))
                if cand_val >= 1.0:
                    inv_total = cand_val
                    break
                elif inv_total == 0.0 and cand_val > 0.0:
                    inv_total = cand_val
            if inv_total >= 1.0:
                break
        if inv_total >= 1.0:
            break

    credit_note = 0.0
    m_cn = re.search(r"Credit\s*(?:Note|Adj/Payout)[^\d\n]{0,20}(?:₹|INR|Rs\.?)?\s*([0-9,]+\.\d{2})", rev_plain_clean, re.IGNORECASE)
    if m_cn:
        credit_note = clean_num(m_cn.group(1))

    round_off = footer_hints.get("roundOff", 0.0)
    m_ro = re.search(r"(?:Less\s*:\s*)?Round\s*Off(?:\s*Amt)?\s*[:\-]?\s*(?:₹|INR|Rs\.?)?\s*(\(?-\)?\s*\d+\.\d{2}-?|[-+]?\d+\.\d{2}-?)", rev_plain_clean, re.IGNORECASE)
    if m_ro:
        round_off = clean_num(m_ro.group(1))
        if m_ro.group(0).lower().startswith("less") and round_off > 0:
            round_off = -round_off

    if inv_total == 0.0 and footer_hints.get("table_total_last", 0.0) > 0:
        inv_total = round2(footer_hints["table_total_last"])

    summary_taxable = 0.0
    summary_cgst = 0.0
    summary_sgst = 0.0
    summary_igst = 0.0
    summary_cess = 0.0
    summary_credit_note = 0.0
    summary_discount_kv = 0.0
    summary_net_payable = 0.0
    summary_slabs: Dict[float, float] = {}
    summary_slabs_detail: List[Dict[str, Any]] = []
    hsn_rate_map: Dict[str, float] = {}

    for mat in reversed(tables):
        if _is_tax_summary_table(mat):
            # Also inspect all rows (including <thead> row 0) for rightmost KV pairs (e.g. SUB TOTAL / DISCOUNT / SGST AMT / CGST AMT / NET AMT)
            for tr_kv in mat:
                if len(tr_kv) >= 2 and re.search(r"\d", tr_kv[-1]):
                    lbl_r = tr_kv[-2].strip().lower()
                    val_r = clean_num(tr_kv[-1])
                    if val_r <= 0:
                        continue
                    if "grand total" in lbl_r or "net amt" in lbl_r or "net payable" in lbl_r or "receivable" in lbl_r:
                        summary_net_payable = val_r
                    elif ("%" not in lbl_r and "rate" not in lbl_r) and (
                        "sgst pay" in lbl_r or "sgst amt" in lbl_r or "sgst amount" in lbl_r
                        or re.fullmatch(r"(?:output\s+)?(?:sgst|utgst|state\s+tax)", lbl_r.rstrip(":"))
                    ) and summary_sgst == 0.0:
                        summary_sgst = val_r
                    elif ("%" not in lbl_r and "rate" not in lbl_r) and (
                        "cgst pay" in lbl_r or "cgst amt" in lbl_r or "cgst amount" in lbl_r
                        or re.fullmatch(r"(?:output\s+)?(?:cgst|central\s+tax)", lbl_r.rstrip(":"))
                    ) and summary_cgst == 0.0:
                        summary_cgst = val_r
                    elif ("%" not in lbl_r and "rate" not in lbl_r) and (
                        "igst pay" in lbl_r or "igst amt" in lbl_r or "igst amount" in lbl_r
                        or re.fullmatch(r"(?:output\s+)?(?:igst|integrated\s+tax)", lbl_r.rstrip(":"))
                    ) and summary_igst == 0.0:
                        summary_igst = val_r
                    elif "sub total" in lbl_r or "subtotal" in lbl_r:
                        summary_taxable = val_r
                    elif ("discount" in lbl_r or "cash disc" in lbl_r) and "%" not in lbl_r:
                        summary_discount_kv = val_r
            h0 = [c.lower() for c in mat[0]]
            has_h1 = len(mat) > 1 and any(any(k in c.lower() for k in ("rate", "amt", "amount")) for c in mat[1]) and not any("total" in c.lower() for c in mat[1])
            h1 = [c.lower() for c in mat[1]] if has_h1 else [""] * len(h0)
            h0_filled = list(h0)
            for ci in range(1, len(h0_filled)):
                if not h0_filled[ci].strip() and any(k in h0_filled[ci - 1] for k in ("cgst", "central", "sgst", "utgst", "state", "igst", "integrated", "cess")):
                    h0_filled[ci] = h0_filled[ci - 1]
            ncols_ts = max(len(h0_filled), len(h1))
            taxable_col_idx = -1
            hsn_col_idx = -1
            cg_rate_idx = cg_amt_idx = sg_rate_idx = sg_amt_idx = ig_rate_idx = ig_amt_idx = cs_amt_idx = -1

            # Detect OCR-flattened colspan multi-column tax summary headers (e.g. METRO:
            # row 0 has [HSN, Taxable, CGST, SGST, IGST, Cess, Total Tax, '', '', '', '']
            # while row 1 has ['', '', Rate (%), Amt, Rate (%), Amt, Rate (%), Amt, Rate (%), Amt, ''])
            h1_rate_cols = [ci for ci, c1 in enumerate(h1) if "rate" in c1] if has_h1 else []
            ordered_tax_groups: List[str] = []
            for c0 in h0:
                cl = c0.strip().lower()
                if ("cgst" in cl or "central" in cl) and "cgst" not in ordered_tax_groups:
                    ordered_tax_groups.append("cgst")
                elif ("sgst" in cl or "utgst" in cl or "state gst" in cl or "state tax" in cl) and "sgst" not in ordered_tax_groups:
                    ordered_tax_groups.append("sgst")
                elif ("igst" in cl or "integrated" in cl) and "igst" not in ordered_tax_groups:
                    ordered_tax_groups.append("igst")
                elif "cess" in cl and "cess" not in ordered_tax_groups:
                    ordered_tax_groups.append("cess")

            tax_desc_col_idx = -1
            tax_pct_col_idx = -1
            generic_tax_amt_idx = -1
            if has_h1 and len(h1_rate_cols) >= 2 and len(ordered_tax_groups) >= 2:
                # Bind HSN / Taxable from row 0 before the first Rate column, and pair each Rate+Amt with ordered_tax_groups
                for ci in range(ncols_ts):
                    c0 = h0[ci] if ci < len(h0) else ""
                    if hsn_col_idx == -1 and ("hsn" in c0 or "sac" in c0):
                        hsn_col_idx = ci
                    if taxable_col_idx == -1 and ("taxable" in c0 or "taxa." in c0 or ("class" in h0 and c0.strip() == "total")):
                        taxable_col_idx = ci
                for grp, r_ci in zip(ordered_tax_groups, h1_rate_cols):
                    a_ci = r_ci + 1 if (r_ci + 1 < ncols_ts and any(k in h1[r_ci + 1] for k in ("amt", "amount", "val"))) else -1
                    if grp == "cgst":
                        cg_rate_idx, cg_amt_idx = r_ci, a_ci
                    elif grp == "sgst":
                        sg_rate_idx, sg_amt_idx = r_ci, a_ci
                    elif grp == "igst":
                        ig_rate_idx, ig_amt_idx = r_ci, a_ci
                    elif grp == "cess" and cs_amt_idx == -1:
                        cs_amt_idx = a_ci
            else:
                for ci in range(ncols_ts):
                    c0 = h0_filled[ci] if ci < len(h0_filled) else ""
                    c1 = h1[ci] if ci < len(h1) else ""
                    ch = (c0 + " " + c1).strip()
                    if tax_desc_col_idx == -1 and any(k in ch for k in ("tax desc", "tax type", "tax name", "particulars")):
                        tax_desc_col_idx = ci
                    if taxable_col_idx == -1 and ("taxable" in ch or "taxa." in ch or ("class" in h0 and ("sub total" in ch or "subtotal" in ch or c0.strip() == "total"))):
                        taxable_col_idx = ci
                    if hsn_col_idx == -1 and ("hsn" in ch or "sac" in ch):
                        hsn_col_idx = ci
                    if ("cgst" in ch or "central" in ch or (c0.strip() == "cost" and "sgst" in " ".join(h0_filled))):
                        if "rate" in c1 or "%" in ch:
                            cg_rate_idx = ci
                        elif cg_amt_idx == -1:
                            cg_amt_idx = ci
                    elif "sgst" in ch or "utgst" in ch or "state gst" in ch or "state tax" in ch:
                        if "rate" in c1 or "%" in ch:
                            sg_rate_idx = ci
                        elif sg_amt_idx == -1:
                            sg_amt_idx = ci
                    elif "igst" in ch or "integrated" in ch:
                        if "rate" in c1 or "%" in ch:
                            ig_rate_idx = ci
                        elif ig_amt_idx == -1:
                            ig_amt_idx = ci
                    elif "cess" in ch and "rate" not in c1 and "%" not in ch and cs_amt_idx == -1:
                        cs_amt_idx = ci
                    elif generic_tax_amt_idx == -1 and any(k in ch for k in ("taxamt", "tax amt", "tax amount")):
                        generic_tax_amt_idx = ci
                    elif tax_pct_col_idx == -1 and (ch in ("tax %", "tax%", "rate") or ("tax" in ch and "%" in ch)) and "amt" not in ch:
                        tax_pct_col_idx = ci

            hdr_cells = h0
            data_row_start = 2 if has_h1 else 1
            comp_cgst = comp_sgst = comp_igst = 0.0
            comp_slabs_seen: set = set()
            is_comp_tbl = (tax_desc_col_idx != -1 and generic_tax_amt_idx != -1 and cg_amt_idx == -1 and sg_amt_idx == -1 and ig_amt_idx == -1)
            for tr in mat[data_row_start:]:
                joined_tr = " ".join(tr).lower()
                # Check rightmost 2 cells on MARG Tax Summary for SUB TOTAL / CGST PAYBLE / SGST PAYBLE / GRAND TOTAL
                if len(tr) >= 2:
                    lbl_r = tr[-2].strip().lower()
                    val_r = clean_num(tr[-1])
                    if "grand total" in lbl_r and val_r > 0:
                        summary_net_payable = val_r
                    elif ("sgst pay" in lbl_r) and val_r > 0:
                        summary_sgst = val_r
                    elif ("cgst pay" in lbl_r) and val_r > 0:
                        summary_cgst = val_r
                    elif "sub total" in lbl_r and val_r > 0:
                        summary_taxable = val_r

                if "total" in (tr[0].lower() if tr else "") or joined_tr.startswith("total"):
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
                    if taxable_col_idx != -1 and taxable_col_idx < len(tr) and re.search(r"\d", tr[taxable_col_idx]):
                        summary_taxable = clean_num(tr[taxable_col_idx])
                    if cg_amt_idx != -1 and cg_amt_idx < len(tr) and re.search(r"\d", tr[cg_amt_idx]):
                        summary_cgst = clean_num(tr[cg_amt_idx])
                    if sg_amt_idx != -1 and sg_amt_idx < len(tr) and re.search(r"\d", tr[sg_amt_idx]):
                        summary_sgst = clean_num(tr[sg_amt_idx])
                    if ig_amt_idx != -1 and ig_amt_idx < len(tr) and re.search(r"\d", tr[ig_amt_idx]):
                        summary_igst = clean_num(tr[ig_amt_idx])
                    if cs_amt_idx != -1 and cs_amt_idx < len(tr) and re.search(r"\d", tr[cs_amt_idx]):
                        summary_cess = clean_num(tr[cs_amt_idx])
                    if summary_cgst == 0.0 and summary_sgst == 0.0:
                        nums = [clean_num(c) for c in tr if re.search(r"\d", c)]
                        if len(nums) >= 4 and abs((nums[1] + nums[2]) - nums[3]) <= 0.2:
                            summary_taxable, summary_cgst, summary_sgst = nums[0], nums[1], nums[2]
                        elif len(nums) >= 3 and abs(nums[1] - nums[2]) <= 0.2:
                            summary_taxable, summary_cgst, summary_sgst = nums[0], nums[1], nums[2]
                    continue

                if is_comp_tbl and tax_desc_col_idx < len(tr):
                    td_name = tr[tax_desc_col_idx].strip().lower()
                    c_tx = clean_num(tr[taxable_col_idx]) if (0 <= taxable_col_idx < len(tr)) else 0.0
                    c_pct = clean_num(tr[tax_pct_col_idx]) if (0 <= tax_pct_col_idx < len(tr)) else 0.0
                    c_amt = clean_num(tr[generic_tax_amt_idx]) if generic_tax_amt_idx < len(tr) else 0.0
                    if re.match(r"^(?:c[\s\-]?gst|central)", td_name):
                        comp_cgst = round2(comp_cgst + c_amt)
                        full_r = round2(c_pct * 2.0) if c_pct > 0 else 0.0
                        k_s = (full_r, round2(c_tx))
                        if c_tx > 0 and k_s not in comp_slabs_seen:
                            comp_slabs_seen.add(k_s)
                            summary_slabs[full_r] = round2(summary_slabs.get(full_r, 0.0) + c_tx)
                            summary_slabs_detail.append({"hsn": "", "rate": full_r, "taxable": round2(c_tx), "cgst": round2(c_amt), "sgst": round2(c_amt), "igst": 0.0, "cess": 0.0})
                        continue
                    elif re.match(r"^(?:s[\s\-]?gst|utgst|state)", td_name):
                        comp_sgst = round2(comp_sgst + c_amt)
                        full_r = round2(c_pct * 2.0) if c_pct > 0 else 0.0
                        k_s = (full_r, round2(c_tx))
                        if c_tx > 0 and k_s not in comp_slabs_seen:
                            comp_slabs_seen.add(k_s)
                            summary_slabs[full_r] = round2(summary_slabs.get(full_r, 0.0) + c_tx)
                            summary_slabs_detail.append({"hsn": "", "rate": full_r, "taxable": round2(c_tx), "cgst": round2(c_amt), "sgst": round2(c_amt), "igst": 0.0, "cess": 0.0})
                        continue
                    elif re.match(r"^(?:i[\s\-]?gst|integrated)", td_name):
                        comp_igst = round2(comp_igst + c_amt)
                        full_r = round2(c_pct)
                        k_s = (full_r, round2(c_tx))
                        if c_tx > 0 and k_s not in comp_slabs_seen:
                            comp_slabs_seen.add(k_s)
                            summary_slabs[full_r] = round2(summary_slabs.get(full_r, 0.0) + c_tx)
                            summary_slabs_detail.append({"hsn": "", "rate": full_r, "taxable": round2(c_tx), "cgst": 0.0, "sgst": 0.0, "igst": round2(c_amt), "cess": 0.0})
                        continue
                    elif td_name.startswith("tcs") or td_name.startswith("cess"):
                        continue

                cg_m = re.search(r"\bcgst\s*(\d+(?:\.\d+)?)", joined_tr)
                sg_m = re.search(r"\bsgst\s*(\d+(?:\.\d+)?)", joined_tr)
                ig_m = re.search(r"\bigst\s*(\d+(?:\.\d+)?)", joined_tr)
                gst_m = re.search(r"\bgst\s*(\d+(?:\.\d+)?)", joined_tr)
                slab_rate = 0.0
                has_explicit_zero = False
                if cg_m and sg_m:
                    slab_rate = round2(float(cg_m.group(1)) + float(sg_m.group(1)))
                elif ig_m:
                    slab_rate = round2(float(ig_m.group(1)))
                elif gst_m:
                    slab_rate = round2(float(gst_m.group(1)))
                elif cg_rate_idx != -1 or sg_rate_idx != -1 or ig_rate_idx != -1:
                    cgr = clean_num(tr[cg_rate_idx]) if 0 <= cg_rate_idx < len(tr) else 0.0
                    sgr = clean_num(tr[sg_rate_idx]) if 0 <= sg_rate_idx < len(tr) else 0.0
                    igr = clean_num(tr[ig_rate_idx]) if 0 <= ig_rate_idx < len(tr) else 0.0
                    if igr > 0:
                        slab_rate = round2(igr)
                    elif (cgr + sgr) > 0:
                        slab_rate = round2(cgr + sgr)
                    else:
                        has_explicit_zero = True
                if slab_rate == 0.0 and not has_explicit_zero:
                    pcts = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", joined_tr)]
                    if len(pcts) >= 2 and abs(pcts[0] - pcts[1]) <= 0.1 and (pcts[0] + pcts[1]) in (0, 3, 5, 12, 18, 28):
                        slab_rate = round2(pcts[0] + pcts[1])
                        if slab_rate == 0.0:
                            has_explicit_zero = True
                    elif len(pcts) == 1 and pcts[0] in (0, 3, 5, 12, 18, 28):
                        slab_rate = round2(pcts[0])
                        if slab_rate == 0.0:
                            has_explicit_zero = True

                row_tx_val = clean_num(tr[taxable_col_idx]) if (0 <= taxable_col_idx < len(tr) and re.search(r"\d", tr[taxable_col_idx])) else 0.0
                row_cg_val = clean_num(tr[cg_amt_idx]) if (0 <= cg_amt_idx < len(tr) and re.search(r"\d", tr[cg_amt_idx])) else 0.0
                row_sg_val = clean_num(tr[sg_amt_idx]) if (0 <= sg_amt_idx < len(tr) and re.search(r"\d", tr[sg_amt_idx])) else 0.0
                row_ig_val = clean_num(tr[ig_amt_idx]) if (0 <= ig_amt_idx < len(tr) and re.search(r"\d", tr[ig_amt_idx])) else 0.0
                row_cs_val = clean_num(tr[cs_amt_idx]) if (0 <= cs_amt_idx < len(tr) and re.search(r"\d", tr[cs_amt_idx])) else 0.0
                if slab_rate == 0.0 and row_tx_val > 0 and (row_cg_val + row_sg_val + row_ig_val) > 0:
                    est = ((row_cg_val + row_sg_val + row_ig_val) / row_tx_val) * 100.0
                    for std in (3, 5, 12, 18, 28):
                        if abs(est - std) <= 0.6:
                            slab_rate = float(std)
                            break
                if row_tx_val > 0 and (slab_rate > 0 or has_explicit_zero or (row_cg_val + row_sg_val + row_ig_val) == 0.0):
                    summary_slabs[slab_rate] = round2(summary_slabs.get(slab_rate, 0.0) + row_tx_val)
                    h_digits = ""
                    if 0 <= hsn_col_idx < len(tr):
                        h_digits = re.sub(r"[^0-9]", "", re.sub(r"\.0+\b", "", tr[hsn_col_idx]))
                        if 4 <= len(h_digits) <= 8 and slab_rate > 0:
                            hsn_rate_map[h_digits] = slab_rate
                    summary_slabs_detail.append({
                        "hsn": h_digits,
                        "rate": slab_rate,
                        "taxable": round2(row_tx_val),
                        "cgst": round2(row_cg_val),
                        "sgst": round2(row_sg_val),
                        "igst": round2(row_ig_val),
                        "cess": round2(row_cs_val),
                    })
            if comp_cgst > 0 and summary_cgst == 0.0:
                summary_cgst = comp_cgst
            if comp_sgst > 0 and summary_sgst == 0.0:
                summary_sgst = comp_sgst
            if comp_igst > 0 and summary_igst == 0.0:
                summary_igst = comp_igst
            if summary_taxable == 0.0 and summary_slabs_detail:
                summary_taxable = round2(sum(d["taxable"] for d in summary_slabs_detail))
                if summary_cgst == 0.0:
                    summary_cgst = round2(sum(d["cgst"] for d in summary_slabs_detail))
                if summary_sgst == 0.0:
                    summary_sgst = round2(sum(d["sgst"] for d in summary_slabs_detail))
                if summary_igst == 0.0:
                    summary_igst = round2(sum(d["igst"] for d in summary_slabs_detail))
                if summary_cess == 0.0:
                    summary_cess = round2(sum(d["cess"] for d in summary_slabs_detail))

    # Parse Tally footer ledger lines (e.g. "CGST @ 2.5%: 2.50 % → 550.00" or "SGST @ 2.5% ₹ 83.18")
    footer_ledger_rates: List[Tuple[str, float, float]] = list(footer_hints.get("_ledger_rates") or [])
    for kind, lrate, lamt in footer_ledger_rates:
        if kind == "CGST" and summary_cgst == 0.0:
            summary_cgst = lamt
        elif kind in ("SGST", "UTGST") and summary_sgst == 0.0:
            summary_sgst = lamt
        elif kind == "IGST" and summary_igst == 0.0:
            summary_igst = lamt
    seen_ledger = set(footer_ledger_rates)
    for m_arr in re.finditer(
        r"\b(CGST|SGST|UTGST|IGST)\s*@\s*(\d+(?:\.\d+)?)\s*%[^\n]{0,60}?(?:→|[:\-|]|\s)\s*(?:₹|INR|Rs\.?)?\s*([0-9,]+\.\d{2})(?!\s*%)",
        rev_plain_clean,
        re.IGNORECASE,
    ):
        kind = m_arr.group(1).upper()
        lrate = float(m_arr.group(2))
        lamt = clean_num(m_arr.group(3))
        if lamt > 0 and (kind, lrate, lamt) not in seen_ledger:
            seen_ledger.add((kind, lrate, lamt))
            footer_ledger_rates.append((kind, lrate, lamt))
            if kind == "CGST" and summary_cgst == 0.0:
                summary_cgst = lamt
            elif kind in ("SGST", "UTGST") and summary_sgst == 0.0:
                summary_sgst = lamt
            elif kind == "IGST" and summary_igst == 0.0:
                summary_igst = lamt

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
    _sum_tx_cmp = round2(sum(r["taxable"] for r in rows)) if rows else 0.0
    _sum_tax_cmp = round2(sum(r["cgst"] + r["sgst"] + r["igst"] + r["cess"] for r in rows)) if rows else 0.0
    if _sum_tax_cmp == 0.0 and (summary_cgst + summary_sgst + summary_igst) > 0:
        _sum_tax_cmp = round2(summary_cgst + summary_sgst + summary_igst)
    _exp_net_cmp = round2(_sum_tx_cmp + _sum_tax_cmp - credit_note) if _sum_tx_cmp > 0 else 0.0
    if summary_net_payable > 0 and (
        inv_total == 0.0
        or summary_credit_note > 0
        or abs(inv_total - summary_net_payable) <= 1.0
        or inv_total < summary_net_payable * 0.5
        or (_exp_net_cmp > 0 and abs(summary_net_payable - _exp_net_cmp) <= 2.0 and abs(inv_total - _exp_net_cmp) > 2.0)
    ):
        inv_total = round2(summary_net_payable)

    raw_only_rows = [r for r in rows if r.get("_raw_amt_only", 0.0) > 0]
    if raw_only_rows and len(raw_only_rows) == len(rows):
        sum_raw_only = round2(sum(r["_raw_amt_only"] for r in rows))
        footer_tax_sum = round2(
            footer_hints.get("cgstTotal", 0.0)
            + footer_hints.get("sgstTotal", 0.0)
            + footer_hints.get("igstTotal", 0.0)
        )
        # Single-row qty * rate OCR slip repair when tax-inclusive AMOUNT rows total slightly off printed inv_total
        if inv_total > 0.0 and (summary_cgst + summary_sgst + summary_igst) > 0.0 and summary_taxable > 0.0 and summary_taxable < inv_total * 0.96:
            gap_raw = round2(inv_total - sum_raw_only)
            sum_all_t = round2(summary_cgst + summary_sgst + summary_igst + summary_cess)
            if 0.50 <= abs(gap_raw) <= max(50.0, inv_total * 0.05) and abs((summary_taxable + sum_all_t + round_off) - inv_total) <= 1.50:
                cands_qr = []
                for rw in rows:
                    if rw["quantity"] > 0 and rw["rate"] > 0:
                        exp_qr = round2(rw["quantity"] * rw["rate"] - rw.get("discount", 0.0))
                        if abs(exp_qr - round2(rw["_raw_amt_only"] + gap_raw)) <= 0.15:
                            cands_qr.append((rw, exp_qr))
                if len(cands_qr) == 1:
                    others_ok = all(
                        (o is cands_qr[0][0]) or (o["quantity"] <= 0 or o["rate"] <= 0)
                        or abs(round2(o["quantity"] * o["rate"] - o.get("discount", 0.0)) - o["_raw_amt_only"]) <= max(0.50, o["_raw_amt_only"] * 0.02)
                        for o in rows
                    )
                    if others_ok:
                        rw0, exp0 = cands_qr[0]
                        rw0["_raw_amt_only"] = exp0
                        rw0["lineTotal"] = exp0
                        rt0 = rw0["gstRate"]
                        if rt0 > 0:
                            tx0 = round2(exp0 / (1.0 + rt0 / 100.0))
                            tx_a0 = round2(exp0 - tx0)
                            rw0["taxable"] = tx0
                            if summary_igst > 0 and summary_cgst == 0 and summary_sgst == 0:
                                rw0["igst"] = tx_a0
                                rw0["cgst"] = 0.0
                                rw0["sgst"] = 0.0
                            else:
                                rw0["cgst"] = round2(tx_a0 / 2.0)
                                rw0["sgst"] = round2(tx_a0 - rw0["cgst"])
                        sum_raw_only = round2(sum(r["_raw_amt_only"] for r in rows))

        has_tax_payble_hint = bool(re.search(r"\b(?:cgst|sgst|igst)\s*pay(?:a)?ble\b", plain, re.IGNORECASE))
        pre_tax_d = round2(float(footer_hints.get("preTaxDiscount") or 0.0))
        is_tax_excl = (
            (summary_taxable > 0 and abs(sum_raw_only - summary_taxable) <= 1.0)
            or (pre_tax_d > 0.0 and abs(round2((sum_raw_only - pre_tax_d) + summary_cgst + summary_sgst + summary_igst + footer_tax_sum + round_off) - inv_total) <= 0.65)
            or (footer_hints.get("subtotal", 0.0) > 0 and abs(sum_raw_only - footer_hints["subtotal"]) <= 1.0 and (summary_cgst + summary_sgst + summary_igst + footer_tax_sum) > 0)
            or (inv_total > sum_raw_only + 1.0 and (
                "output cgst" in plain.lower()
                or "output sgst" in plain.lower()
                or has_tax_payble_hint
                or (summary_cgst + summary_sgst + summary_igst + footer_tax_sum) > 0
            ))
            or (amount_in_words is not None and amount_in_words > sum_raw_only + 1.0 and footer_tax_sum > 0)
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
            else:
                r["quantity"] = _repair_single_digit_qty_slip(r["quantity"], r["rate"], r["discount"], r["taxable"])

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

    # 1) Tax-inclusive multi-slab subset allocation (e.g. METRO 0% + 5% sharing same HSN)
    inclusive_slab_partitioned = False
    summary_total_tax = round2(summary_cgst + summary_sgst + summary_igst + summary_cess)
    row_lt_sum = round2(sum(r["lineTotal"] for r in rows))
    row_tax_cur = round2(sum(r["cgst"] + r["sgst"] + r["igst"] for r in rows))
    if (
        rows
        and summary_slabs_detail
        and summary_taxable > 0
        and summary_total_tax > 0
        and row_tax_cur == 0.0
        and abs((summary_taxable + summary_total_tax) - row_lt_sum) <= max(1.50, 0.002 * len(rows))
    ):
        rate_incl_targets: Dict[float, float] = {}
        rate_tx_targets: Dict[float, float] = {}
        for sd in summary_slabs_detail:
            rt = float(sd["rate"])
            incl = round2(sd["taxable"] + sd["cgst"] + sd["sgst"] + sd["igst"] + sd["cess"])
            rate_incl_targets[rt] = round2(rate_incl_targets.get(rt, 0.0) + incl)
            rate_tx_targets[rt] = round2(rate_tx_targets.get(rt, 0.0) + sd["taxable"])
        part = _partition_rows_to_inclusive_slabs([float(r["lineTotal"]) for r in rows], rate_incl_targets, tol=1.00)
        if part is not None:
            inclusive_slab_partitioned = True
            is_igst_doc = summary_igst > 0 and summary_cgst == 0 and summary_sgst == 0
            by_rate_idx: Dict[float, List[int]] = {}
            for ridx, rrate in part.items():
                rw = rows[ridx]
                lt_v = float(rw["lineTotal"])
                rw["gstRate"] = round2(rrate)
                if rrate == 0.0:
                    rw["taxable"] = round2(lt_v)
                    rw["cgst"] = 0.0
                    rw["sgst"] = 0.0
                    rw["igst"] = 0.0
                elif is_igst_doc:
                    tx_v = round2(lt_v / (1.0 + rrate / 100.0))
                    ig_v = round2(lt_v - tx_v)
                    rw["taxable"] = tx_v
                    rw["igst"] = ig_v
                    rw["cgst"] = 0.0
                    rw["sgst"] = 0.0
                else:
                    tx_v = round2(lt_v / (1.0 + rrate / 100.0))
                    half = _equal_local_tax_half(tx_v, rrate, round2(lt_v - tx_v))
                    rw["taxable"] = tx_v
                    rw["cgst"] = half
                    rw["sgst"] = half
                    rw["igst"] = 0.0
                by_rate_idx.setdefault(rrate, []).append(ridx)
            # Reconcile exact 1-2 paisa rounding against summary slab taxable target
            for rrate, idxs in by_rate_idx.items():
                if not idxs:
                    continue
                tgt_tx = rate_tx_targets.get(rrate, 0.0)
                cur_tx = round2(sum(rows[i]["taxable"] for i in idxs))
                delta = round2(tgt_tx - cur_tx)
                if 0.0 < abs(delta) <= 0.15:
                    rows[idxs[-1]]["taxable"] = round2(rows[idxs[-1]]["taxable"] + delta)

    # 2) Tax-exclusive mixed-rate footer-implied slab allocation (e.g. Sri Rajalakshmi CGST @ 2.5% = 550.00 -> 22,000 @ 5%)
    if (
        rows
        and round2(sum(r["cgst"] + r["sgst"] + r["igst"] for r in rows)) == 0.0
        and not summary_slabs_detail
        and footer_ledger_rates
    ):
        rate_amts: Dict[float, float] = {}
        is_igst_ledger = any(k == "IGST" for k, _, _ in footer_ledger_rates)
        for kind, lrate, lamt in footer_ledger_rates:
            if kind == "CGST" and lrate > 0:
                full_rate = round2(lrate * 2.0)
                rate_amts[full_rate] = lamt
            elif kind == "IGST" and lrate > 0:
                rate_amts[round2(lrate)] = lamt
        used_indices: set[int] = set()
        for full_rate, cmp_amt in rate_amts.items():
            div = (full_rate / 100.0) if is_igst_ledger else (full_rate / 200.0)
            if div <= 0:
                continue
            implied_tx = round2(cmp_amt / div)
            avail = [i for i in range(len(rows)) if i not in used_indices]
            matched = _subset_match_indices([float(r["taxable"]) for r in rows], implied_tx, tol=1.50, available=avail)
            if matched:
                for i in matched:
                    used_indices.add(i)
                    rw = rows[i]
                    rw["gstRate"] = full_rate
                    tx_v = float(rw["taxable"])
                    if is_igst_ledger:
                        ig_v = round2(tx_v * full_rate / 100.0)
                        rw["igst"] = ig_v
                        rw["lineTotal"] = round2(tx_v + ig_v)
                    else:
                        half = round2(tx_v * full_rate / 200.0)
                        rw["cgst"] = half
                        rw["sgst"] = half
                        rw["lineTotal"] = round2(tx_v + 2.0 * half)

    # 3) Snap MARG/Tax-Summary per-slab 1-2 paisa rounding differences when rows already carry tax
    if rows and summary_slabs_detail and round2(sum(r["cgst"] + r["sgst"] + r["igst"] for r in rows)) > 0.0:
        for sd in summary_slabs_detail:
            rt = float(sd["rate"])
            slab_rows = [r for r in rows if abs(r["gstRate"] - rt) <= 0.05]
            if not slab_rows:
                continue
            diff_tx = round2(sd["taxable"] - sum(r["taxable"] for r in slab_rows))
            if 0.0 < abs(diff_tx) <= 0.15:
                slab_rows[-1]["taxable"] = round2(slab_rows[-1]["taxable"] + diff_tx)

    pre_tax_disc = round2(float(footer_hints.get("preTaxDiscount") or 0.0))
    _eff_cg_pre = round2(summary_cgst or footer_hints.get("cgstTotal", 0.0))
    _eff_sg_pre = round2(summary_sgst or footer_hints.get("sgstTotal", 0.0))
    _eff_ig_pre = round2(summary_igst or footer_hints.get("igstTotal", 0.0))
    if pre_tax_disc > 0.0 and rows and inv_total > 0.0 and (_eff_cg_pre + _eff_sg_pre + _eff_ig_pre) > 0.0:
        _raw_tx_s = round2(sum(r["taxable"] for r in rows))
        _sum_tax_s = round2(_eff_cg_pre + _eff_sg_pre + _eff_ig_pre + summary_cess)
        if _raw_tx_s > pre_tax_disc and abs(round2((_raw_tx_s - pre_tax_disc) + _sum_tax_s + round_off) - inv_total) <= 0.65:
            _rem_d = pre_tax_disc
            _is_ig_pre = _eff_ig_pre > 0 and _eff_cg_pre == 0 and _eff_sg_pre == 0
            for _ri, _rw in enumerate(rows):
                if _ri == len(rows) - 1:
                    _d_part = round2(_rem_d)
                else:
                    _d_part = round2(pre_tax_disc * _rw["taxable"] / _raw_tx_s)
                    _rem_d = round2(_rem_d - _d_part)
                _rw["discount"] = round2(_rw.get("discount", 0.0) + _d_part)
                _rw["taxable"] = round2(max(0.0, _rw["taxable"] - _d_part))
                _rw["cgst"] = 0.0
                _rw["sgst"] = 0.0
                _rw["igst"] = 0.0
                if _rw["gstRate"] > 0 and _rw["taxable"] > 0:
                    if _is_ig_pre:
                        _rw["igst"] = round2(_rw["taxable"] * _rw["gstRate"] / 100.0)
                    else:
                        _hf = round2(_rw["taxable"] * _rw["gstRate"] / 200.0)
                        _rw["cgst"] = _hf
                        _rw["sgst"] = _hf
                _rw["lineTotal"] = round2(_rw["taxable"] + _rw["cgst"] + _rw["sgst"] + _rw["igst"])
            row_lt_sum = round2(sum(r["lineTotal"] for r in rows))

    if inv_total > 0.0 and rows and (_eff_cg_pre + _eff_sg_pre + _eff_ig_pre) > 0.0:
        _gap_lt = round2(inv_total - row_lt_sum)
        _sum_all_tax = round2(_eff_cg_pre + _eff_sg_pre + _eff_ig_pre + summary_cess)
        if 0.50 <= abs(_gap_lt) <= max(50.0, inv_total * 0.05) and abs((summary_taxable + _sum_all_tax + round_off) - inv_total) <= 1.50:
            _off_cands = []
            for _rw in rows:
                if _rw["quantity"] > 0 and _rw["rate"] > 0 and _rw["lineTotal"] > 0:
                    _exp_qr = round2(_rw["quantity"] * _rw["rate"] - _rw.get("discount", 0.0))
                    if abs(_exp_qr - round2(_rw["lineTotal"] + _gap_lt)) <= 0.15:
                        _off_cands.append((_rw, _exp_qr))
            if len(_off_cands) == 1:
                _others_ok = all(
                    (_o is _off_cands[0][0]) or (_o["quantity"] <= 0 or _o["rate"] <= 0)
                    or abs(round2(_o["quantity"] * _o["rate"] - _o.get("discount", 0.0)) - _o["lineTotal"]) <= max(0.50, _o["lineTotal"] * 0.02)
                    for _o in rows
                )
                if _others_ok:
                    _rw0, _exp0 = _off_cands[0]
                    _rw0["lineTotal"] = _exp0
                    if _rw0["cgst"] + _rw0["sgst"] + _rw0["igst"] == 0.0:
                        _rw0["taxable"] = _exp0
                    row_lt_sum = round2(sum(r["lineTotal"] for r in rows))

    taxable_total = round2(sum(r["taxable"] for r in rows)) if rows else round2(summary_taxable)
    discount_total = round2(sum(r.get("discount", 0.0) for r in rows)) if rows else 0.0
    cgst_total = round2(summary_cgst or footer_hints.get("cgstTotal", 0.0) or (sum(r["cgst"] for r in rows) if rows else 0.0))
    sgst_total = round2(summary_sgst or footer_hints.get("sgstTotal", 0.0) or (sum(r["sgst"] for r in rows) if rows else 0.0))
    igst_total = round2(summary_igst or footer_hints.get("igstTotal", 0.0) or (sum(r["igst"] for r in rows) if rows else 0.0))
    cess_total = round2(summary_cess or (sum(r["cess"] for r in rows) if rows else 0.0))

    table_is_inclusive = bool(footer_hints.get("_table_is_incl")) or (
        inv_total > 0
        and abs(row_lt_sum - inv_total) <= max(2.0, inv_total * 0.015)
        and (cgst_total + sgst_total + igst_total) > 0
        and abs((row_lt_sum + cgst_total + sgst_total + igst_total) - inv_total) > 2.0
    )

    for row_item in rows:
        if not inclusive_slab_partitioned:
            if row_item["gstRate"] == 0.0 and row_item.get("hsnSac") in hsn_rate_map:
                row_item["gstRate"] = hsn_rate_map[row_item["hsnSac"]]
            elif row_item["gstRate"] == 0.0 and len(summary_slabs) == 1:
                row_item["gstRate"] = next(iter(summary_slabs.keys()))
        if row_item["taxable"] > 0 and row_item["gstRate"] > 0 and (row_item["cgst"] + row_item["sgst"] + row_item["igst"]) == 0.0:
            if table_is_inclusive:
                lt_v = float(row_item["lineTotal"] or row_item["taxable"])
                tx_v = round2(lt_v / (1.0 + row_item["gstRate"] / 100.0))
                row_item["taxable"] = tx_v
                row_item["lineTotal"] = round2(lt_v)
                if igst_total > 0 and cgst_total == 0 and sgst_total == 0:
                    row_item["igst"] = round2(lt_v - tx_v)
                else:
                    half = _equal_local_tax_half(tx_v, row_item["gstRate"], round2(lt_v - tx_v))
                    row_item["cgst"] = half
                    row_item["sgst"] = half
            elif igst_total > 0 and cgst_total == 0 and sgst_total == 0:
                tax_amt = round2(row_item["taxable"] * row_item["gstRate"] / 100.0)
                row_item["igst"] = tax_amt
                row_item["lineTotal"] = round2(row_item["taxable"] + tax_amt)
            else:
                half = round2(row_item["taxable"] * row_item["gstRate"] / 200.0)
                row_item["cgst"] = half
                row_item["sgst"] = half
                row_item["lineTotal"] = round2(row_item["taxable"] + 2.0 * half)

    # Reconcile partial/overprinted Tax Summary on tax-inclusive invoices (e.g. METRO stamped footer "Scan for 14749.04")
    if table_is_inclusive and rows and not inclusive_slab_partitioned:
        uncovered = [r for r in rows if r["gstRate"] == 0.0 and (r["cgst"] + r["sgst"] + r["igst"]) == 0.0 and r["lineTotal"] > 0]
        if uncovered and summary_taxable > 0 and summary_taxable < row_lt_sum - 10.0:
            cov_tx = round2(sum(r["taxable"] for r in rows if r not in uncovered))
            m_ftx = re.findall(r"(?:Scan\s+for|Total(?:\s+Taxable)?)\s*[:\|]?\s*([0-9,]+\.\d{2})", rev_plain_clean, re.IGNORECASE)
            printed_ftx = 0.0
            for raw_ftx in m_ftx:
                cand_ftx = clean_num(raw_ftx)
                if summary_taxable < cand_ftx < row_lt_sum:
                    printed_ftx = cand_ftx
                    break
            if printed_ftx > cov_tx + 1.0:
                target_uncov_tx = round2(printed_ftx - cov_tx)
                for cand_r in (5.0, 12.0, 18.0, 3.0, 28.0):
                    calc_uncov_tx = round2(sum(round2(r["lineTotal"] / (1.0 + cand_r / 100.0)) for r in uncovered))
                    if abs(calc_uncov_tx - target_uncov_tx) <= max(0.50, 0.05 * len(uncovered)):
                        is_ig_doc = igst_total > 0 and cgst_total == 0 and sgst_total == 0
                        for r in uncovered:
                            lt_u = float(r["lineTotal"])
                            tx_u = round2(lt_u / (1.0 + cand_r / 100.0))
                            r["gstRate"] = cand_r
                            r["taxable"] = tx_u
                            if is_ig_doc:
                                r["igst"] = round2(lt_u - tx_u)
                            else:
                                h_u = _equal_local_tax_half(tx_u, cand_r, round2(lt_u - tx_u))
                                r["cgst"] = h_u
                                r["sgst"] = h_u
                        break
        taxable_total = round2(sum(r["taxable"] for r in rows))
        row_cg_now = round2(sum(r["cgst"] for r in rows))
        row_sg_now = round2(sum(r["sgst"] for r in rows))
        row_ig_now = round2(sum(r["igst"] for r in rows))
        if (row_cg_now + row_sg_now + row_ig_now) > (cgst_total + sgst_total + igst_total):
            cgst_total, sgst_total, igst_total = row_cg_now, row_sg_now, row_ig_now
    elif table_is_inclusive and rows:
        taxable_total = round2(sum(r["taxable"] for r in rows))

    if credit_note == 0.0 and summary_discount_kv > 0 and taxable_total > 0:
        _tgt_tot = inv_total if inv_total > 0 else summary_net_payable
        if _tgt_tot > 0:
            _row_cg_f = round2(sum(r["cgst"] for r in rows)) or cgst_total
            _row_sg_f = round2(sum(r["sgst"] for r in rows)) or sgst_total
            _row_ig_f = round2(sum(r["igst"] for r in rows)) or igst_total
            _row_cs_f = round2(sum(r["cess"] for r in rows)) or cess_total
            _base_sum = round2(taxable_total + _row_cg_f + _row_sg_f + _row_ig_f + _row_cs_f + round_off)
            if abs((_base_sum - summary_discount_kv) - _tgt_tot) <= 1.50 and abs((_base_sum - summary_discount_kv) - _tgt_tot) + 1.0 < abs(_base_sum - _tgt_tot):
                credit_note = round2(summary_discount_kv)

    printed_total_found = inv_total > 0.0 or summary_net_payable > 0.0 or (qr_einvoice is not None and clean_num((qr_einvoice or {}).get("TotInvVal")) > 0.0)
    expected_grand = round2(taxable_total + cgst_total + sgst_total + igst_total + cess_total - credit_note) if taxable_total > 0 else 0.0
    if expected_grand > 10.0 and (inv_total == 0.0 or inv_total < expected_grand * 0.25):
        if summary_net_payable > 0 and abs(summary_net_payable - expected_grand) <= 2.0:
            inv_total = round2(summary_net_payable)
        elif footer_hints.get("table_total_last", 0.0) > 0 and abs(footer_hints["table_total_last"] - expected_grand) <= 2.0:
            inv_total = round2(footer_hints["table_total_last"])

    if inv_total == 0.0 and taxable_total > 0:
        inv_total = round2(taxable_total + cgst_total + sgst_total + igst_total + cess_total - credit_note + round_off)
    elif inv_total > 0 and taxable_total > 0:
        computed_no_ro = round2(taxable_total + cgst_total + sgst_total + igst_total + cess_total - credit_note)
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
        "cessTotal": cess_total,
        "creditNoteTotal": credit_note,
        "roundOff": round_off,
        "invoiceTotal": inv_total,
        "rows": rows,
        "rawTablesHtml": extract_html_tables(raw_text),
        "_meta": {
            "raw_text": raw_text,
            "amount_in_words": amount_in_words,
            "printed_total_found": printed_total_found,
            "summary_slabs_detail": summary_slabs_detail,
        },
    }
    return normalize_canonical_dict(raw_dict, raw_text, qr_einvoice, qr_upi_meta=qr_upi_meta)


def normalize_canonical_dict(
    obj: Dict[str, Any],
    raw_text: str = "",
    qr_einvoice: Optional[Dict[str, Any]] = None,
    qr_upi_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
        if unit.lower() == "packel":
            unit = "Packet"
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
        qty = _repair_single_digit_qty_slip(qty, rate_price, disc, taxable)
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

    # Single-row 1-digit OCR slip repair on lineTotal after CGST/SGST mirroring & header reconciliation (e.g. 832.54 -> 837.54)
    if norm_rows:
        _sum_tx_all = round2(sum(r["taxable"] for r in norm_rows))
        _sum_tax_all = round2(sum(r["cgst"] + r["sgst"] + r["igst"] + r["cess"] for r in norm_rows))
        _mismatched = [
            r for r in norm_rows
            if r["lineTotal"] > 0 and abs((r["taxable"] + r["cgst"] + r["sgst"] + r["igst"] + r["cess"]) - r["lineTotal"]) > 0.25
        ]
        if len(_mismatched) == 1:
            r0 = _mismatched[0]
            _calc_lt = round2(r0["taxable"] + r0["cgst"] + r0["sgst"] + r0["igst"] + r0["cess"])
            _row_tax0 = round2(r0["cgst"] + r0["sgst"] + r0["igst"])
            _rate_ok0 = r0["gstRate"] == 0.0 or (r0["taxable"] > 0 and abs(r0["taxable"] * (r0["gstRate"] / 100.0) - _row_tax0) <= max(0.35, r0["taxable"] * 0.005))
            _s_cur, _s_exp = f"{r0['lineTotal']:.2f}", f"{_calc_lt:.2f}"
            _ham = sum(1 for a, b in zip(_s_cur, _s_exp) if a != b) if len(_s_cur) == len(_s_exp) else 99
            _hdr_ok = (taxable_total <= 0 or abs(_sum_tx_all - taxable_total) <= 0.50) and (
                inv_total <= 0 or abs(round2(_sum_tx_all + _sum_tax_all + round_off - credit_note) - inv_total) <= 1.05
            )
            if _rate_ok0 and _ham == 1 and _hdr_ok:
                r0["lineTotal"] = _calc_lt

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

    seller_name_val = str(seller_obj.get("name") or obj.get("sellerName") or "").strip()
    if qr_upi_meta:
        upi_g = str(qr_upi_meta.get("sellerGstin") or "").strip().upper()
        if upi_g and is_valid_gstin(upi_g) and not is_valid_gstin(s_gstin) and upi_g != b_gstin:
            s_gstin = upi_g
        if not seller_name_val or not _clean_party_name(seller_name_val):
            upi_payee = str(qr_upi_meta.get("payeeName") or "").strip()
            if upi_payee:
                seller_name_val = upi_payee

    raw_meta = obj.get("_meta") if isinstance(obj.get("_meta"), dict) else {}
    canon = {
        "seller": {"name": seller_name_val, "gstin": s_gstin},
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
    if raw_meta:
        canon["_meta"] = raw_meta
    canon["_audit"] = audit_invoice_math(
        canon,
        raw_text=raw_text or str(raw_meta.get("raw_text") or ""),
        amount_in_words=raw_meta.get("amount_in_words"),
        qr_einvoice=qr_einvoice,
        printed_total_found=raw_meta.get("printed_total_found"),
    )
    return canon
