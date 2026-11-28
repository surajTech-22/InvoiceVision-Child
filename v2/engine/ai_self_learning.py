#!/usr/bin/env python3
"""Offline Self-Learning Layout, Rule & Vector Memory Engine (SQLite + FTS5 + sqlite-vec).

Gives InvoiceVisionChild v2 persistent long-term learning across invoices without
cloud calls or heavy model fine-tuning:
1. Computes deterministic HTML/text layout fingerprints (`layout_hash`, `header_signature`)
   and pure-Python 384-d L2-normalized feature-hashing embeddings (<2ms on CPU).
2. Stores & indexes learned layout rules (`supplier_layout_rules`) and resolved examples
   (`layout_memory_examples`, FTS5 `layout_examples_fts`, and `sqlite-vec` `layout_examples_vec`
   with pure-Python cosine fallback if `sqlite_vec` is unavailable).
3. Applies learned column aliases, party role anchors, overwide row alignment, and
   tax-inclusive/discount hints BEFORE parsing, and automatically synthesizes new rules
   whenever Text-AI, Vision, or user confirmation fixes a difficult invoice layout.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import math
import re
import sqlite3
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import sqlite_vec  # type: ignore
except Exception:
    sqlite_vec = None  # type: ignore

EMBED_DIM = 384

_CLEAN_GSTIN_RE = re.compile(r"[^A-Z0-9]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_gstin(val: Any) -> str:
    return _CLEAN_GSTIN_RE.sub("", str(val or "").strip().upper())[:15]


def _norm_name(val: Any) -> str:
    txt = str(val or "").upper()
    txt = re.sub(r"^(?:M/S\.?|MESSRS\.?|SRI|SHRI)\s+", "", txt)
    return re.sub(r"[^A-Z0-9]+", "", txt)


def _strip_tags(cell_html: str) -> str:
    txt = re.sub(r"<br\s*/?>", " ", cell_html or "", flags=re.IGNORECASE)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = html_lib.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def compute_header_fingerprint(raw_text: str) -> Dict[str, Any]:
    """Extract normalized table header signature, markers, and SHA-1 layout_hash."""
    text = str(raw_text or "")
    table_matches = re.findall(r"<table\b[^>]*>(.*?)</table>", text, flags=re.IGNORECASE | re.DOTALL)
    raw_headers: List[str] = []
    table_sigs: List[str] = []
    overwide_table = False

    for tbl in table_matches:
        row_matches = re.findall(r"<tr\b[^>]*>(.*?)</tr>", tbl, flags=re.IGNORECASE | re.DOTALL)
        if not row_matches:
            continue
        first_ths = re.findall(r"<th\b[^>]*>(.*?)</th>", row_matches[0], flags=re.IGNORECASE | re.DOTALL)
        if not first_ths and len(row_matches) > 1:
            first_ths = re.findall(r"<td\b[^>]*>(.*?)</td>", row_matches[0], flags=re.IGNORECASE | re.DOTALL)
        hdrs = [re.sub(r"\s+", " ", _strip_tags(h).lower()).strip() for h in first_ths if _strip_tags(h)]
        if hdrs:
            raw_headers.extend(hdrs)
            norm_h = "|".join(re.sub(r"[^a-z0-9%/.\-]+", "_", h).strip("_") for h in hdrs[:18])
            table_sigs.append(norm_h)
            if len(row_matches) >= 2:
                max_tds = max(
                    (len(re.findall(r"<t[dh]\b[^>]*>.*?</t[dh]>", r, flags=re.IGNORECASE | re.DOTALL)) for r in row_matches[1:4]),
                    default=0,
                )
                if len(hdrs) >= 5 and max_tds > len(hdrs):
                    overwide_table = True

    low = text.lower()
    markers: List[str] = []
    for key, pat in (
        ("c_dash_gst", r"\bc\-gst\b|\bs\-gst\b|\bi\-gst\b"),
        ("ci_sut_gst", r"c\s*/\s*i\s*gst|s\s*/\s*ut\s*gst"),
        ("company_gstin", r"company['\u2019]?s\s+gstin"),
        ("party_colon", r"\bparty\s*:"),
        ("discount_allowed", r"less\s*:\s*discount\s*allowed|trade\s*sch\s*disc|pri\.?\s*sch"),
        ("incl_of_tax", r"incl\.?\s*of\s*tax|inclusive\s+of\s+tax|mrp\s*incl"),
        ("marg_erp", r"marg\s*erp|cgst\s*payble|sgst\s*payble"),
        ("component_tax_tbl", r"tax\s*desc\s+tax\s*%\s+taxable|tax\s*type\s+taxable"),
        ("two_col_kv_tot", r"sub\s*total\s*.*\bsgst\b.*\bcgst\b.*\bgrand\s*total\b"),
    ):
        if re.search(pat, low, flags=re.IGNORECASE | re.DOTALL):
            markers.append(key)
    if overwide_table:
        markers.append("overwide_rows")

    # Use first substantial line-item header table + summary signatures + markers
    header_signature = " || ".join(table_sigs[:3])
    if markers:
        header_signature = (header_signature + " :: " if header_signature else "") + ",".join(markers)
    if not header_signature:
        lines = [re.sub(r"\s+", " ", ln.strip().lower()) for ln in text.splitlines() if ln.strip()][:8]
        header_signature = " | ".join(lines)[:240]

    layout_hash = hashlib.sha1(header_signature.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return {
        "layoutHash": layout_hash,
        "headerSignature": header_signature[:600],
        "rawHeaders": raw_headers[:48],
        "markers": markers,
        "overwideTable": overwide_table,
    }


def embed_layout_text(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Compute a fast deterministic L2-normalized signed feature-hashing vector (384-d)."""
    vec = [0.0] * dim
    norm = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not norm:
        return vec
    tokens = re.findall(r"[a-z0-9%./\-]{2,}", norm)
    features: List[Tuple[str, float]] = []
    for tok in tokens[:160]:
        features.append(("w:" + tok, 2.0))
    for i in range(max(0, len(tokens) - 1)):
        if i >= 120:
            break
        features.append(("b:" + tokens[i] + "_" + tokens[i + 1], 1.5))
    compact = norm[:420]
    for i in range(max(0, len(compact) - 2)):
        tri = compact[i:i + 3]
        if tri.strip():
            features.append(("c:" + tri, 0.5))

    for feat, weight in features:
        digest = hashlib.blake2b(feat.encode("utf-8", errors="ignore"), digest_size=8).digest()
        idx_raw, sign_byte = struct.unpack("<IB", digest[:5])
        idx = idx_raw % dim
        sign = 1.0 if (sign_byte & 1) == 0 else -1.0
        vec[idx] += sign * weight

    norm_sq = sum(v * v for v in vec)
    if norm_sq > 1e-12:
        inv = 1.0 / math.sqrt(norm_sq)
        vec = [v * inv for v in vec]
    return vec


def pack_f32(vec: List[float]) -> bytes:
    if len(vec) != EMBED_DIM:
        padded = (list(vec) + [0.0] * EMBED_DIM)[:EMBED_DIM]
        return struct.pack(f"<{EMBED_DIM}f", *padded)
    return struct.pack(f"<{EMBED_DIM}f", *vec)


def unpack_f32(blob: Optional[bytes]) -> List[float]:
    if not blob or len(blob) != EMBED_DIM * 4:
        return []
    return list(struct.unpack(f"<{EMBED_DIM}f", blob))


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def ensure_self_learning_schema(conn: sqlite3.Connection) -> bool:
    """Create self-learning layout/vector/FTS5 tables safely. Returns True if sqlite-vec loaded."""
    vec_ready = False
    if sqlite_vec is not None:
        try:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            vec_ready = True
        except Exception:
            vec_ready = False

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS supplier_layout_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_gstin TEXT NOT NULL DEFAULT '',
            supplier_name_norm TEXT NOT NULL DEFAULT '',
            layout_hash TEXT NOT NULL DEFAULT '',
            header_signature TEXT NOT NULL DEFAULT '',
            rule_json TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user_confirmed',
            confidence REAL NOT NULL DEFAULT 0.85,
            hit_count INTEGER NOT NULL DEFAULT 1,
            success_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(supplier_gstin, layout_hash)
        );
        CREATE INDEX IF NOT EXISTS idx_slr_hash ON supplier_layout_rules(layout_hash);
        CREATE INDEX IF NOT EXISTS idx_slr_gstin ON supplier_layout_rules(supplier_gstin);

        CREATE TABLE IF NOT EXISTS layout_memory_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_gstin TEXT NOT NULL DEFAULT '',
            supplier_name TEXT NOT NULL DEFAULT '',
            layout_hash TEXT NOT NULL DEFAULT '',
            header_signature TEXT NOT NULL DEFAULT '',
            invoice_number TEXT NOT NULL DEFAULT '',
            ocr_excerpt TEXT NOT NULL DEFAULT '',
            resolved_summary_json TEXT NOT NULL DEFAULT '{}',
            rule_json TEXT NOT NULL DEFAULT '{}',
            embedding BLOB,
            quality_score REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_lme_hash ON layout_memory_examples(layout_hash);
        CREATE INDEX IF NOT EXISTS idx_lme_gstin ON layout_memory_examples(supplier_gstin);
        """
    )
    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS layout_examples_fts USING fts5(
                example_id UNINDEXED,
                supplier_gstin,
                supplier_name,
                header_signature,
                ocr_excerpt
            )
            """
        )
    except Exception:
        pass

    if vec_ready:
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS layout_examples_vec USING vec0(embedding float[{EMBED_DIM}])"
            )
        except Exception:
            vec_ready = False
    conn.commit()
    return vec_ready


def _open_db(db_path: str) -> Optional[Tuple[sqlite3.Connection, bool]]:
    if not db_path:
        return None
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    vec_ready = ensure_self_learning_schema(conn)
    return conn, vec_ready


def _merge_rules(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base or {})
    for k, v in (patch or {}).items():
        if v is None:
            continue
        if k == "columnAliases" and isinstance(v, dict):
            cur = dict(out.get("columnAliases") or {})
            for hk, role in v.items():
                if str(hk).strip() and str(role).strip():
                    cur[str(hk).strip().lower()] = str(role).strip()
            out["columnAliases"] = cur
        elif k == "partyRoleHints" and isinstance(v, dict):
            cur = dict(out.get("partyRoleHints") or {})
            for pk in ("sellerAnchors", "buyerAnchors"):
                vals = list(dict.fromkeys([*(cur.get(pk) or []), *(v.get(pk) or [])]))
                if vals:
                    cur[pk] = vals[:8]
            out["partyRoleHints"] = cur
        elif isinstance(v, bool):
            if v or k not in out:
                out[k] = v
        elif str(v).strip():
            out[k] = v
    return out


def retrieve_similar_layout_examples(
    db_path: str,
    raw_text: str,
    supplier_gstin: str = "",
    client_gstin: str = "",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Retrieve closest historical invoice layouts using sqlite-vec + FTS5/cosine fallback."""
    if not db_path or not Path(db_path).exists():
        return []
    opened = _open_db(db_path)
    if not opened:
        return []
    conn, vec_ready = opened
    try:
        fp = compute_header_fingerprint(raw_text)
        q_text = f"{_norm_gstin(supplier_gstin)} {fp['headerSignature']} {' '.join(fp['rawHeaders'][:24])}"
        q_vec = embed_layout_text(q_text)
        cg = _norm_gstin(client_gstin)
        sg = _norm_gstin(supplier_gstin)
        results: List[Tuple[float, sqlite3.Row]] = []

        if vec_ready:
            try:
                knn_rows = conn.execute(
                    """
                    SELECT e.*, v.distance
                    FROM layout_examples_vec v
                    JOIN layout_memory_examples e ON e.id = v.rowid
                    WHERE v.embedding MATCH ? AND k = ?
                    ORDER BY v.distance ASC
                    """,
                    (pack_f32(q_vec), max(1, int(top_k) * 2)),
                ).fetchall()
                for row in knn_rows:
                    if cg and _norm_gstin(row["supplier_gstin"]) == cg:
                        continue
                    dist = float(row["distance"]) if row["distance"] is not None else 1.0
                    sim = max(0.0, 1.0 - 0.5 * dist * dist)
                    if sg and _norm_gstin(row["supplier_gstin"]) == sg:
                        sim = min(1.0, sim + 0.12)
                    if row["layout_hash"] == fp["layoutHash"]:
                        sim = min(1.0, sim + 0.15)
                    results.append((sim, row))
            except Exception:
                results = []

        if not results:
            cand_rows = conn.execute(
                "SELECT * FROM layout_memory_examples ORDER BY id DESC LIMIT 120"
            ).fetchall()
            for row in cand_rows:
                if cg and _norm_gstin(row["supplier_gstin"]) == cg:
                    continue
                r_vec = unpack_f32(row["embedding"])
                if not r_vec:
                    r_vec = embed_layout_text(f"{row['supplier_gstin']} {row['header_signature']}")
                sim = cosine_similarity(q_vec, r_vec)
                if sg and _norm_gstin(row["supplier_gstin"]) == sg:
                    sim = min(1.0, sim + 0.12)
                if row["layout_hash"] == fp["layoutHash"]:
                    sim = min(1.0, sim + 0.15)
                results.append((sim, row))

        results.sort(key=lambda item: item[0], reverse=True)
        out: List[Dict[str, Any]] = []
        seen_hashes = set()
        for sim, row in results:
            key = (row["supplier_gstin"], row["layout_hash"], row["invoice_number"])
            if key in seen_hashes:
                continue
            seen_hashes.add(key)
            try:
                summary = json.loads(row["resolved_summary_json"] or "{}")
            except Exception:
                summary = {}
            try:
                rule = json.loads(row["rule_json"] or "{}")
            except Exception:
                rule = {}
            out.append({
                "id": int(row["id"]),
                "similarity": round(float(sim), 3),
                "supplierGstin": row["supplier_gstin"],
                "supplierName": row["supplier_name"],
                "layoutHash": row["layout_hash"],
                "headerSignature": row["header_signature"],
                "invoiceNumber": row["invoice_number"],
                "ocrExcerpt": row["ocr_excerpt"],
                "resolvedSummary": summary,
                "rule": rule,
            })
            if len(out) >= top_k:
                break
        return out
    finally:
        conn.close()


def lookup_layout_rules(
    db_path: str,
    raw_text: str,
    supplier_gstin: str = "",
    supplier_name: str = "",
    client_gstin: str = "",
) -> Dict[str, Any]:
    """Look up learned layout rules + corrections to guide parsing before extraction."""
    fp = compute_header_fingerprint(raw_text)
    empty = {
        "matched": False,
        "matchType": "none",
        "layoutHash": fp["layoutHash"],
        "headerSignature": fp["headerSignature"],
        "rules": {},
        "recentCorrections": [],
        "similarExamples": [],
    }
    if not db_path or not Path(db_path).exists():
        return empty

    opened = _open_db(db_path)
    if not opened:
        return empty
    conn, _ = opened
    try:
        sg = _norm_gstin(supplier_gstin)
        cg = _norm_gstin(client_gstin)
        if cg and sg == cg:
            sg = ""
        sname = _norm_name(supplier_name)
        lhash = fp["layoutHash"]

        matched_row = None
        match_type = "none"

        # 1. Exact (supplier_gstin, layout_hash)
        if sg:
            matched_row = conn.execute(
                "SELECT * FROM supplier_layout_rules WHERE supplier_gstin = ? AND layout_hash = ? LIMIT 1",
                (sg, lhash),
            ).fetchone()
            if matched_row is not None:
                match_type = "supplier_and_layout"

        # 2. Exact layout_hash template across suppliers (e.g. TallyPrime / Marg ERP shared template)
        if matched_row is None and lhash:
            rows = conn.execute(
                "SELECT * FROM supplier_layout_rules WHERE layout_hash = ? ORDER BY success_count DESC, updated_at DESC LIMIT 5",
                (lhash,),
            ).fetchall()
            for row in rows:
                if cg and _norm_gstin(row["supplier_gstin"]) == cg:
                    continue
                matched_row = row
                match_type = "template_layout_hash"
                break

        # 3. Same supplier latest rule
        if matched_row is None and sg:
            matched_row = conn.execute(
                "SELECT * FROM supplier_layout_rules WHERE supplier_gstin = ? ORDER BY success_count DESC, updated_at DESC LIMIT 1",
                (sg,),
            ).fetchone()
            if matched_row is not None:
                match_type = "supplier_gstin"

        # 4. Same supplier by normalized name (when GSTIN OCR missed)
        if matched_row is None and sname:
            matched_row = conn.execute(
                "SELECT * FROM supplier_layout_rules WHERE supplier_name_norm = ? ORDER BY success_count DESC, updated_at DESC LIMIT 1",
                (sname,),
            ).fetchone()
            if matched_row is not None and (not cg or _norm_gstin(matched_row["supplier_gstin"]) != cg):
                match_type = "supplier_name"
            else:
                matched_row = None

        rules: Dict[str, Any] = {}
        if matched_row is not None:
            try:
                rules = json.loads(matched_row["rule_json"] or "{}")
            except Exception:
                rules = {}
            try:
                conn.execute(
                    "UPDATE supplier_layout_rules SET hit_count = hit_count + 1 WHERE id = ?",
                    (matched_row["id"],),
                )
                conn.commit()
            except Exception:
                pass

        # Attach recent supplier_corrections (now actively read during extraction!)
        corrections: List[Dict[str, Any]] = []
        if sg:
            try:
                c_rows = conn.execute(
                    """
                    SELECT field_name, original_value, corrected_value, created_at
                    FROM supplier_corrections
                    WHERE supplier_gstin = ?
                    ORDER BY id DESC LIMIT 10
                    """,
                    (sg,),
                ).fetchall()
                corrections = [
                    {
                        "field": str(r["field_name"]),
                        "from": str(r["original_value"]),
                        "to": str(r["corrected_value"]),
                    }
                    for r in c_rows
                ]
            except Exception:
                corrections = []

        conn.close()
        similar = retrieve_similar_layout_examples(db_path, raw_text, sg, cg, top_k=2)

        # If no direct rule matched, borrow safe generic rules from high-similarity (>=0.82) layout exemplar
        if not rules and similar and float(similar[0].get("similarity") or 0.0) >= 0.82:
            top_rule = dict(similar[0].get("rule") or {})
            safe_rule: Dict[str, Any] = {}
            for safe_key in ("columnAliases", "partyRoleHints", "discountMode", "summaryTableMode", "rightAlignOverwideRows"):
                if safe_key in top_rule:
                    safe_rule[safe_key] = top_rule[safe_key]
            if safe_rule:
                rules = safe_rule
                match_type = "vector_similar_layout"

        return {
            "matched": bool(rules),
            "matchType": match_type,
            "layoutHash": lhash,
            "headerSignature": fp["headerSignature"],
            "rules": rules,
            "recentCorrections": corrections,
            "similarExamples": similar,
        }
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return empty


def save_layout_rule(
    db_path: str,
    raw_text: str,
    supplier_gstin: str,
    supplier_name: str,
    rule_dict: Dict[str, Any],
    *,
    source: str = "user_confirmed",
    invoice_number: str = "",
    resolved_summary: Optional[Dict[str, Any]] = None,
    client_gstin: str = "",
    quality_score: float = 1.0,
) -> Dict[str, Any]:
    """Persist or merge a layout rule and index an embedding + FTS5 exemplar."""
    if not db_path:
        return {"saved": False, "reason": "no_db_path"}
    sg = _norm_gstin(supplier_gstin)
    cg = _norm_gstin(client_gstin)
    if cg and sg == cg:
        return {"saved": False, "reason": "client_gstin_guard"}

    fp = compute_header_fingerprint(raw_text)
    lhash = fp["layoutHash"]
    hsig = fp["headerSignature"]
    sname_norm = _norm_name(supplier_name)
    now = _utc_now()

    opened = _open_db(db_path)
    if not opened:
        return {"saved": False, "reason": "open_failed"}
    conn, vec_ready = opened
    try:
        saved_rule = False
        if rule_dict:
            existing = conn.execute(
                "SELECT id, rule_json FROM supplier_layout_rules WHERE supplier_gstin = ? AND layout_hash = ? LIMIT 1",
                (sg, lhash),
            ).fetchone()
            if existing is not None:
                try:
                    prev = json.loads(existing["rule_json"] or "{}")
                except Exception:
                    prev = {}
                merged = _merge_rules(prev, rule_dict)
                conn.execute(
                    """
                    UPDATE supplier_layout_rules
                    SET supplier_name_norm = COALESCE(NULLIF(?, ''), supplier_name_norm),
                        header_signature = ?,
                        rule_json = ?,
                        source = ?,
                        confidence = MAX(confidence, ?),
                        success_count = success_count + 1,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (sname_norm, hsig, json.dumps(merged, ensure_ascii=False), source, float(quality_score), now, existing["id"]),
                )
            else:
                merged = dict(rule_dict)
                conn.execute(
                    """
                    INSERT INTO supplier_layout_rules (
                        supplier_gstin, supplier_name_norm, layout_hash, header_signature,
                        rule_json, source, confidence, hit_count, success_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
                    """,
                    (sg, sname_norm, lhash, hsig, json.dumps(merged, ensure_ascii=False), source, float(quality_score), now, now),
                )
            saved_rule = True

        excerpt = re.sub(r"\s+", " ", (raw_text or "").strip())[:1400]
        embed_input = f"{sg} {hsig} {' '.join(fp['rawHeaders'][:24])}"
        vec = embed_layout_text(embed_input)
        vec_blob = pack_f32(vec)
        summary_json = json.dumps(resolved_summary or {}, ensure_ascii=False)
        rule_json_str = json.dumps(rule_dict or {}, ensure_ascii=False)

        # Deduplicate same (supplier_gstin, layout_hash, invoice_number)
        if invoice_number:
            old_ids = [
                int(r["id"])
                for r in conn.execute(
                    "SELECT id FROM layout_memory_examples WHERE supplier_gstin = ? AND layout_hash = ? AND invoice_number = ?",
                    (sg, lhash, invoice_number.strip()),
                ).fetchall()
            ]
            for oid in old_ids:
                conn.execute("DELETE FROM layout_memory_examples WHERE id = ?", (oid,))
                if vec_ready:
                    try:
                        conn.execute("DELETE FROM layout_examples_vec WHERE rowid = ?", (oid,))
                    except Exception:
                        pass
                try:
                    conn.execute("DELETE FROM layout_examples_fts WHERE example_id = ?", (oid,))
                except Exception:
                    pass

        cur = conn.execute(
            """
            INSERT INTO layout_memory_examples (
                supplier_gstin, supplier_name, layout_hash, header_signature, invoice_number,
                ocr_excerpt, resolved_summary_json, rule_json, embedding, quality_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (sg, str(supplier_name or "").strip(), lhash, hsig, str(invoice_number or "").strip(), excerpt, summary_json, rule_json_str, sqlite3.Binary(vec_blob), float(quality_score), now),
        )
        ex_id = int(cur.lastrowid)
        try:
            conn.execute(
                "INSERT INTO layout_examples_fts (example_id, supplier_gstin, supplier_name, header_signature, ocr_excerpt) VALUES (?, ?, ?, ?, ?)",
                (ex_id, sg, str(supplier_name or "").strip(), hsig, excerpt),
            )
        except Exception:
            pass
        if vec_ready:
            try:
                conn.execute(
                    "INSERT INTO layout_examples_vec (rowid, embedding) VALUES (?, ?)",
                    (ex_id, vec_blob),
                )
            except Exception:
                pass

        # Cap per-(supplier, layout) exemplars to 5 most recent
        stale = conn.execute(
            """
            SELECT id FROM layout_memory_examples
            WHERE supplier_gstin = ? AND layout_hash = ?
            ORDER BY id DESC LIMIT -1 OFFSET 5
            """,
            (sg, lhash),
        ).fetchall()
        for sr in stale:
            sid = int(sr["id"])
            conn.execute("DELETE FROM layout_memory_examples WHERE id = ?", (sid,))
            if vec_ready:
                try:
                    conn.execute("DELETE FROM layout_examples_vec WHERE rowid = ?", (sid,))
                except Exception:
                    pass
            try:
                conn.execute("DELETE FROM layout_examples_fts WHERE example_id = ?", (sid,))
            except Exception:
                pass

        conn.commit()
        return {"saved": True, "savedRule": saved_rule, "layoutHash": lhash, "exampleId": ex_id}
    finally:
        conn.close()


def synthesize_and_save_layout_rule(
    db_path: str,
    raw_text: str,
    base_canon: Optional[Dict[str, Any]],
    resolved_canon: Dict[str, Any],
    *,
    source: str = "ai_self_learned",
    client_gstin: str = "",
) -> Dict[str, Any]:
    """Derive reusable layout rules from a resolved invoice and persist to SQLite."""
    if not db_path or not isinstance(resolved_canon, dict):
        return {"saved": False, "reason": "invalid_input"}

    audit = resolved_canon.get("_audit") or {}
    if not audit.get("fully_balanced"):
        return {"saved": False, "reason": "not_fully_balanced"}

    cg = _norm_gstin(client_gstin)
    s_gstin = _norm_gstin((resolved_canon.get("seller") or {}).get("gstin"))
    b_gstin = _norm_gstin((resolved_canon.get("buyer") or {}).get("gstin"))
    if cg and s_gstin == cg and b_gstin and b_gstin != cg:
        opposite_gstin = b_gstin
        opposite_name = str((resolved_canon.get("buyer") or {}).get("name") or "").strip()
        direction = "Sales"
    else:
        opposite_gstin = s_gstin
        opposite_name = str((resolved_canon.get("seller") or {}).get("name") or "").strip()
        direction = "Purchase"

    if cg and opposite_gstin == cg:
        return {"saved": False, "reason": "client_gstin_guard"}

    fp = compute_header_fingerprint(raw_text)
    rule: Dict[str, Any] = {}
    aliases: Dict[str, str] = {}
    for hdr in fp["rawHeaders"]:
        hl = hdr.lower().strip()
        if re.search(r"c\s*/\s*i\s*gst", hl):
            aliases[hl] = "half_gstrate" if ("%" in hl or "rate" in hl) else "cgst"
        elif re.search(r"s\s*/\s*ut\s*gst", hl):
            aliases[hl] = "half_gstrate" if ("%" in hl or "rate" in hl) else "sgst"
        elif hl in ("dis%", "dis %") and "disc_pct" not in aliases.values():
            aliases[hl] = "disc_pct"
    if aliases:
        rule["columnAliases"] = aliases

    if fp.get("overwideTable"):
        rule["rightAlignOverwideRows"] = True

    # Detect party anchor swap repair
    if isinstance(base_canon, dict):
        base_s = _norm_gstin((base_canon.get("seller") or {}).get("gstin"))
        if base_s == cg and s_gstin != cg:
            low = (raw_text or "").lower()
            hints: Dict[str, List[str]] = {}
            if re.search(r"company['\u2019]?s\s+gstin", low):
                hints["sellerAnchors"] = ["company's gstin", "company’s gstin"]
            if re.search(r"\bparty\s*:", low):
                hints["buyerAnchors"] = ["party :", "party:"]
            if hints:
                rule["partyRoleHints"] = hints

    rows = resolved_canon.get("rows") or []
    inv_total = float(resolved_canon.get("invoiceTotal") or 0.0)
    tax_total = float(resolved_canon.get("cgstTotal") or 0.0) + float(resolved_canon.get("sgstTotal") or 0.0) + float(resolved_canon.get("igstTotal") or 0.0)
    row_lt_sum = sum(float(r.get("lineTotal") or 0.0) for r in rows)
    if rows and inv_total > 0 and tax_total > 0 and abs(row_lt_sum - inv_total) <= max(2.0, inv_total * 0.015):
        rule["taxInclusive"] = True

    if float(resolved_canon.get("creditNoteTotal") or 0.0) > 0:
        rule["discountMode"] = "pre_tax_footer"

    rule["preferredDirection"] = direction
    summary = {
        "invoiceNumber": resolved_canon.get("invoiceNumber", ""),
        "sellerGstin": s_gstin,
        "buyerGstin": b_gstin,
        "taxableTotal": round(float(resolved_canon.get("taxableTotal") or 0.0), 2),
        "cgstTotal": round(float(resolved_canon.get("cgstTotal") or 0.0), 2),
        "sgstTotal": round(float(resolved_canon.get("sgstTotal") or 0.0), 2),
        "igstTotal": round(float(resolved_canon.get("igstTotal") or 0.0), 2),
        "invoiceTotal": round(inv_total, 2),
        "rowCount": len(rows),
    }

    return save_layout_rule(
        db_path=db_path,
        raw_text=raw_text,
        supplier_gstin=opposite_gstin,
        supplier_name=opposite_name,
        rule_dict=rule,
        source=source,
        invoice_number=str(resolved_canon.get("invoiceNumber") or ""),
        resolved_summary=summary,
        client_gstin=cg,
        quality_score=1.0,
    )
