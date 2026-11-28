#!/usr/bin/env python3
"""Offline 1-shot self-learning SQLite supplier memory for InvoiceVisionChild v2.

Stores verified supplier identities, OCR name aliases, preferred Purchase/Sales
direction & Accounting/Item invoice mode, HSN->GST rate mappings, and compact
few-shot examples keyed by 15-character Indian GSTIN (with fuzzy alias fallback).
Pure stdlib (sqlite3) - zero external dependencies, fast (<10ms) CPU lookup.
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gst_math import audit_invoice_math, is_valid_gstin  # noqa: E402

VALID_GST_RATES = (0.0, 0.1, 0.25, 1.0, 1.5, 3.0, 5.0, 6.0, 7.5, 12.0, 18.0, 28.0, 40.0)


def normalize_gstin(gstin: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", gstin or "").upper()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_name_tokens(name: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9\s]", " ", (name or "").upper())
    return re.sub(r"\s+", " ", cleaned).strip()


_GENERIC_TRADE_WORDS = {
    "MARKETING", "ENTERPRISES", "TRADERS", "TRADING", "AGENCIES",
    "PRIVATE", "LIMITED", "PVT", "LTD", "CO", "COMPANY", "INDIA",
    "STORES", "DISTRIBUTORS", "CORPORATION", "INDUSTRIES", "PRODUCTS",
    "SOLUTIONS", "SERVICES", "AND",
}


def _distinctive_name_tokens(name: str) -> str:
    tokens = [t for t in _norm_name_tokens(name).split() if t not in _GENERIC_TRADE_WORDS]
    return " ".join(tokens)


def _norm_hsn(hsn: str) -> str:
    digits = re.sub(r"\D", "", hsn or "")
    return digits[:8] if len(digits) >= 4 else ""


def _is_valid_gst_rate(rate: float) -> bool:
    return any(abs(rate - r) <= 0.01 for r in VALID_GST_RATES)


def _connect(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def ensure_memory_db(db_path: str) -> None:
    if not db_path:
        return
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS supplier_profiles (
                gstin TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                preferred_direction TEXT NOT NULL DEFAULT '',
                preferred_recognition_mode TEXT NOT NULL DEFAULT '',
                tax_inclusive_hint INTEGER NOT NULL DEFAULT 0,
                confirmed_count INTEGER NOT NULL DEFAULT 0,
                last_confirmed_utc TEXT NOT NULL DEFAULT '',
                best_example_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS supplier_hsn_rates (
                gstin TEXT NOT NULL,
                hsn_code TEXT NOT NULL,
                gst_rate REAL NOT NULL,
                sample_description TEXT NOT NULL DEFAULT '',
                hit_count INTEGER NOT NULL DEFAULT 1,
                updated_utc TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (gstin, hsn_code)
            );
            CREATE TABLE IF NOT EXISTS supplier_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gstin TEXT NOT NULL,
                invoice_number TEXT NOT NULL DEFAULT '',
                field_diffs_json TEXT NOT NULL DEFAULT '{}',
                learned_utc TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS agent_memory (
                agent_name TEXT NOT NULL,
                gstin TEXT NOT NULL,
                rules_json TEXT NOT NULL DEFAULT '{}',
                hit_count INTEGER NOT NULL DEFAULT 1,
                updated_utc TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (agent_name, gstin)
            );
            """
        )
        try:
            from ai_self_learning import ensure_self_learning_schema

            ensure_self_learning_schema(conn)
        except Exception:
            pass


def load_agent_memory(db_path: str, agent_name: str, gstin: str) -> Dict[str, Any]:
    g = normalize_gstin(gstin)
    if not db_path or not agent_name or not g or not Path(db_path).is_file():
        return {}
    ensure_memory_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT rules_json FROM agent_memory WHERE agent_name = ? AND gstin = ?",
            (agent_name, g),
        ).fetchone()
    if row is None:
        return {}
    try:
        obj = json.loads(row["rules_json"] or "{}")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def load_all_agent_memories(db_path: str, gstin: str) -> Dict[str, Dict[str, Any]]:
    g = normalize_gstin(gstin)
    if not db_path or not g or not Path(db_path).is_file():
        return {}
    ensure_memory_db(db_path)
    out: Dict[str, Dict[str, Any]] = {}
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT agent_name, rules_json, hit_count FROM agent_memory WHERE gstin = ?",
            (g,),
        ).fetchall()
    for r in rows:
        try:
            obj = json.loads(r["rules_json"] or "{}")
            if isinstance(obj, dict):
                obj["_hitCount"] = int(r["hit_count"] or 1)
                out[str(r["agent_name"])] = obj
        except Exception:
            pass
    return out


def save_agent_memory(db_path: str, agent_name: str, gstin: str, rules: Dict[str, Any]) -> bool:
    g = normalize_gstin(gstin)
    if not db_path or not agent_name or not is_valid_gstin(g) or not rules:
        return False
    ensure_memory_db(db_path)
    now = _utc_now()
    clean_rules = {k: v for k, v in rules.items() if not str(k).startswith("_") and v is not None}
    if not clean_rules:
        return False
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT rules_json, hit_count FROM agent_memory WHERE agent_name = ? AND gstin = ?",
            (agent_name, g),
        ).fetchone()
        merged: Dict[str, Any] = {}
        hits = 1
        if existing is not None:
            try:
                old = json.loads(existing["rules_json"] or "{}")
                if isinstance(old, dict):
                    merged.update(old)
            except Exception:
                pass
            hits = int(existing["hit_count"] or 1) + 1
        merged.update(clean_rules)
        conn.execute(
            """
            INSERT INTO agent_memory (agent_name, gstin, rules_json, hit_count, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(agent_name, gstin) DO UPDATE SET
                rules_json = excluded.rules_json,
                hit_count = excluded.hit_count,
                updated_utc = excluded.updated_utc
            """,
            (agent_name, g, json.dumps(merged, ensure_ascii=False), hits, now),
        )
        conn.commit()
    return True


def _load_hsn_map(conn: sqlite3.Connection, gstin: str) -> Dict[str, float]:
    rows = conn.execute(
        "SELECT hsn_code, gst_rate FROM supplier_hsn_rates WHERE gstin = ? ORDER BY hit_count DESC, updated_utc DESC",
        (gstin,),
    ).fetchall()
    return {str(r["hsn_code"]): float(r["gst_rate"]) for r in rows}


def _row_to_profile(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    try:
        aliases = json.loads(row["aliases_json"] or "[]")
        if not isinstance(aliases, list):
            aliases = []
    except Exception:
        aliases = []
    try:
        best_example = json.loads(row["best_example_json"] or "{}")
        if not isinstance(best_example, dict):
            best_example = {}
    except Exception:
        best_example = {}
    gstin = str(row["gstin"])
    return {
        "gstin": gstin,
        "canonicalName": str(row["canonical_name"] or ""),
        "aliases": [str(a) for a in aliases if str(a).strip()],
        "preferredDirection": str(row["preferred_direction"] or ""),
        "preferredRecognitionMode": str(row["preferred_recognition_mode"] or ""),
        "taxInclusiveHint": bool(row["tax_inclusive_hint"]),
        "confirmedCount": int(row["confirmed_count"] or 0),
        "lastConfirmedUtc": str(row["last_confirmed_utc"] or ""),
        "bestExample": best_example,
        "hsnRates": _load_hsn_map(conn, gstin),
    }


def lookup_supplier_profile(db_path: str, seller_gstin: str, seller_name: str = "", client_gstin: str = "") -> Optional[Dict[str, Any]]:
    if not db_path or not Path(db_path).is_file():
        return None
    ensure_memory_db(db_path)
    norm_gstin = normalize_gstin(seller_gstin)
    client_norm = normalize_gstin(client_gstin)
    if client_norm and norm_gstin == client_norm:
        return None
    with _connect(db_path) as conn:
        if is_valid_gstin(norm_gstin):
            row = conn.execute(
                "SELECT * FROM supplier_profiles WHERE gstin = ?",
                (norm_gstin,),
            ).fetchone()
            return _row_to_profile(conn, row) if row is not None else None

        target_name = _norm_name_tokens(seller_name)
        target_distinct = _distinctive_name_tokens(seller_name)
        if len(target_name) < 4:
            return None

        best_row = None
        best_score = 0.0
        for cand in conn.execute("SELECT * FROM supplier_profiles").fetchall():
            if client_norm and normalize_gstin(cand["gstin"]) == client_norm:
                continue
            names = [str(cand["canonical_name"] or "")]
            try:
                names.extend(str(a) for a in json.loads(cand["aliases_json"] or "[]"))
            except Exception:
                pass
            for n in names:
                nn = _norm_name_tokens(n)
                if len(nn) < 4:
                    continue
                score = difflib.SequenceMatcher(None, target_name, nn).ratio()
                nn_distinct = _distinctive_name_tokens(n)
                if len(target_distinct) >= 3 and len(nn_distinct) >= 3:
                    d_score = difflib.SequenceMatcher(None, target_distinct, nn_distinct).ratio()
                    if d_score < 0.88:
                        continue
                if score > best_score:
                    best_score = score
                    best_row = cand
        if best_row is not None and best_score >= 0.88:
            return _row_to_profile(conn, best_row)
    return None


def record_supplier_learning(
    db_path: str,
    gstin: str,
    canonical_name: str,
    original_ocr_name: str = "",
    preferred_direction: str = "",
    preferred_recognition_mode: str = "",
    tax_inclusive_hint: bool = False,
    hsn_rates: Optional[List[Dict[str, Any]]] = None,
    example_canonical: Optional[Dict[str, Any]] = None,
    invoice_number: str = "",
    field_diffs: Optional[Dict[str, Any]] = None,
    client_gstin: str = "",
) -> Dict[str, Any]:
    if not db_path:
        return {"saved": False, "reason": "No memoryDbPath provided."}
    norm_gstin = normalize_gstin(gstin)
    client_norm = normalize_gstin(client_gstin)
    if client_norm and norm_gstin == client_norm:
        return {"saved": False, "reason": "Skipped: client's own GSTIN cannot be saved as a supplier profile."}
    if not is_valid_gstin(norm_gstin):
        return {"saved": False, "reason": f"Valid 15-char GSTIN required (got '{gstin}')."}

    ensure_memory_db(db_path)
    now = _utc_now()
    clean_canon = re.sub(r"\s+", " ", (canonical_name or "").strip())
    clean_orig = re.sub(r"\s+", " ", (original_ocr_name or "").strip())

    with _connect(db_path) as conn:
        existing = conn.execute("SELECT * FROM supplier_profiles WHERE gstin = ?", (norm_gstin,)).fetchone()
        aliases: List[str] = []
        prev_count = 0
        prev_dir = ""
        prev_mode = ""
        prev_incl = 0
        prev_example: Dict[str, Any] = {}
        if existing is not None:
            prev_count = int(existing["confirmed_count"] or 0)
            prev_dir = str(existing["preferred_direction"] or "")
            prev_mode = str(existing["preferred_recognition_mode"] or "")
            prev_incl = int(existing["tax_inclusive_hint"] or 0)
            if not clean_canon:
                clean_canon = str(existing["canonical_name"] or "")
            try:
                aliases = [str(a) for a in json.loads(existing["aliases_json"] or "[]") if str(a).strip()]
            except Exception:
                aliases = []
            try:
                prev_example = json.loads(existing["best_example_json"] or "{}")
            except Exception:
                prev_example = {}

        for candidate_alias in (clean_orig, clean_canon):
            if candidate_alias and not any(a.casefold() == candidate_alias.casefold() for a in aliases):
                aliases.append(candidate_alias)
        aliases = aliases[-20:]

        final_dir = preferred_direction.strip() or prev_dir
        final_mode = preferred_recognition_mode.strip() or prev_mode
        final_incl = 1 if (tax_inclusive_hint or prev_incl) else 0

        compact_example = prev_example
        if isinstance(example_canonical, dict) and example_canonical:
            sample_rows = []
            for r in (example_canonical.get("rows") or [])[:3]:
                sample_rows.append(
                    {
                        "description": str(r.get("description") or "")[:60],
                        "hsnSac": str(r.get("hsnSac") or ""),
                        "taxable": round(float(r.get("taxable") or 0.0), 2),
                        "gstRate": round(float(r.get("gstRate") or 0.0), 2),
                        "cgst": round(float(r.get("cgst") or 0.0), 2),
                        "sgst": round(float(r.get("sgst") or 0.0), 2),
                        "igst": round(float(r.get("igst") or 0.0), 2),
                    }
                )
            compact_example = {
                "invoiceNumber": str(example_canonical.get("invoiceNumber") or invoice_number),
                "taxableTotal": round(float(example_canonical.get("taxableTotal") or 0.0), 2),
                "invoiceTotal": round(float(example_canonical.get("invoiceTotal") or 0.0), 2),
                "rows": sample_rows,
            }

        conn.execute(
            """
            INSERT INTO supplier_profiles(
                gstin, canonical_name, aliases_json, preferred_direction,
                preferred_recognition_mode, tax_inclusive_hint, confirmed_count,
                last_confirmed_utc, best_example_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(gstin) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                aliases_json = excluded.aliases_json,
                preferred_direction = excluded.preferred_direction,
                preferred_recognition_mode = excluded.preferred_recognition_mode,
                tax_inclusive_hint = excluded.tax_inclusive_hint,
                confirmed_count = excluded.confirmed_count,
                last_confirmed_utc = excluded.last_confirmed_utc,
                best_example_json = excluded.best_example_json
            """,
            (
                norm_gstin,
                clean_canon,
                json.dumps(aliases, ensure_ascii=False),
                final_dir,
                final_mode,
                final_incl,
                prev_count + 1,
                now,
                json.dumps(compact_example, ensure_ascii=False),
            ),
        )

        learned_hsn = 0
        for item in hsn_rates or []:
            hsn = _norm_hsn(str(item.get("hsnSac") or item.get("hsn") or ""))
            try:
                rate = float(item.get("gstRate") or item.get("rate") or 0.0)
            except Exception:
                continue
            if not hsn or not _is_valid_gst_rate(rate):
                continue
            desc = str(item.get("description") or "")[:80]
            conn.execute(
                """
                INSERT INTO supplier_hsn_rates(gstin, hsn_code, gst_rate, sample_description, hit_count, updated_utc)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(gstin, hsn_code) DO UPDATE SET
                    gst_rate = excluded.gst_rate,
                    sample_description = CASE WHEN excluded.sample_description <> '' THEN excluded.sample_description ELSE supplier_hsn_rates.sample_description END,
                    hit_count = supplier_hsn_rates.hit_count + 1,
                    updated_utc = excluded.updated_utc
                """,
                (norm_gstin, hsn, rate, desc, now),
            )
            learned_hsn += 1

        if field_diffs or invoice_number:
            conn.execute(
                "INSERT INTO supplier_corrections(gstin, invoice_number, field_diffs_json, learned_utc) VALUES (?, ?, ?, ?)",
                (norm_gstin, str(invoice_number or ""), json.dumps(field_diffs or {}, ensure_ascii=False), now),
            )
        conn.commit()
    return {
        "saved": True,
        "gstin": norm_gstin,
        "canonicalName": clean_canon,
        "confirmedCount": prev_count + 1,
        "learnedHsnCount": learned_hsn,
    }


def _find_learned_hsn_rate(hsn_map: Dict[str, float], raw_hsn: str) -> Optional[float]:
    hsn = _norm_hsn(raw_hsn)
    if not hsn or not hsn_map:
        return None
    if hsn in hsn_map:
        return hsn_map[hsn]
    prefix4 = hsn[:4]
    matches = [rate for code, rate in hsn_map.items() if code.startswith(prefix4)]
    if matches and len(set(round(m, 2) for m in matches)) == 1:
        return matches[0]
    return None


def apply_supplier_memory(canon: Dict[str, Any], db_path: str, client_gstin: str = "") -> Dict[str, Any]:
    seller = canon.get("seller") or {}
    buyer = canon.get("buyer") or {}
    seller_gstin = normalize_gstin(str(seller.get("gstin") or ""))
    client_norm = normalize_gstin(client_gstin)
    seller_name = str(seller.get("name") or "").strip()

    meta: Dict[str, Any] = {
        "profileFound": False,
        "gstin": seller_gstin,
        "canonicalName": "",
        "confirmedCount": 0,
        "preferredDirection": "",
        "preferredRecognitionMode": "",
        "appliedRules": [],
    }
    if not db_path or (client_norm and seller_gstin == client_norm):
        return meta

    profile = lookup_supplier_profile(db_path, seller_gstin, seller_name, client_gstin=client_norm)
    if profile is None:
        return meta
    if is_valid_gstin(seller_gstin) and normalize_gstin(profile.get("gstin")) != seller_gstin:
        return meta

    meta["profileFound"] = True
    meta["gstin"] = profile["gstin"]
    meta["canonicalName"] = profile["canonicalName"]
    meta["confirmedCount"] = profile["confirmedCount"]
    meta["preferredDirection"] = profile["preferredDirection"]
    meta["preferredRecognitionMode"] = profile["preferredRecognitionMode"]

    changed = False
    if not is_valid_gstin(seller_gstin) and is_valid_gstin(profile["gstin"]):
        seller["gstin"] = profile["gstin"]
        canon["seller"] = seller
        seller_gstin = profile["gstin"]
        meta["appliedRules"].append(f"Restored verified seller GSTIN {seller_gstin} from alias memory")
        changed = True

    canon_name = profile["canonicalName"]
    if canon_name and _norm_name_tokens(seller_name) != _norm_name_tokens(canon_name):
        seller["name"] = canon_name
        canon["seller"] = seller
        meta["appliedRules"].append(f"Applied learned seller name '{canon_name}'")
        changed = True

    buyer_gstin = normalize_gstin(str(buyer.get("gstin") or ""))
    is_interstate = (
        float(canon.get("igstTotal") or 0.0) > 0.0
        and float(canon.get("cgstTotal") or 0.0) == 0.0
        and float(canon.get("sgstTotal") or 0.0) == 0.0
    ) or (
        len(seller_gstin) >= 2 and len(buyer_gstin) >= 2 and seller_gstin[:2] != buyer_gstin[:2]
    )

    hsn_map = profile.get("hsnRates") or {}
    inv_total_v = float(canon.get("invoiceTotal") or 0.0)
    lt_sum_v = sum(float(r.get("lineTotal") or 0.0) for r in (canon.get("rows") or []))
    is_incl_doc = bool(profile.get("taxInclusiveHint")) or (
        inv_total_v > 0.0 and abs(lt_sum_v - inv_total_v) <= max(2.0, inv_total_v * 0.015)
    )
    hsn_hits = 0
    for row in canon.get("rows") or []:
        tx = float(row.get("taxable") or 0.0)
        cur_rate = float(row.get("gstRate") or 0.0)
        if tx <= 0.0 or (cur_rate > 0.0 and _is_valid_gst_rate(cur_rate)):
            continue
        learned_rate = _find_learned_hsn_rate(hsn_map, str(row.get("hsnSac") or ""))
        if learned_rate is None:
            continue
        row["gstRate"] = learned_rate
        hsn_hits += 1
        changed = True
        if learned_rate > 0.0 and float(row.get("cgst") or 0.0) == 0.0 and float(row.get("sgst") or 0.0) == 0.0 and float(row.get("igst") or 0.0) == 0.0:
            if is_incl_doc:
                lt_v = float(row.get("lineTotal") or tx)
                tx_new = round(lt_v / (1.0 + learned_rate / 100.0), 2)
                row["taxable"] = tx_new
                if is_interstate:
                    row["igst"] = round(lt_v - tx_new, 2)
                else:
                    half = round(tx_new * learned_rate / 200.0, 2)
                    row["cgst"] = half
                    row["sgst"] = half
                row["lineTotal"] = round(lt_v, 2)
            elif is_interstate:
                igst = round(tx * learned_rate / 100.0, 2)
                row["igst"] = igst
                row["lineTotal"] = round(tx + igst, 2)
            else:
                half = round(tx * learned_rate / 200.0, 2)
                row["cgst"] = half
                row["sgst"] = half
                row["lineTotal"] = round(tx + 2.0 * half, 2)

    if hsn_hits > 0:
        meta["appliedRules"].append(f"Applied learned HSN->GST rate on {hsn_hits} row(s)")

    if changed:
        from gst_parser import normalize_canonical_dict  # local import avoids circular startup

        raw_text = str(canon.pop("_rawText", "") or "")
        canon.pop("_audit", None)
        refreshed = normalize_canonical_dict(canon, raw_text=raw_text)
        canon.clear()
        canon.update(refreshed)
        canon["_audit"] = audit_invoice_math(canon)
    return meta


def build_few_shot_prompt_hint(
    db_path: str,
    seller_gstin: str,
    seller_name: str = "",
    client_gstin: str = "",
    raw_text: str = "",
) -> str:
    lines: List[str] = []
    profile = lookup_supplier_profile(db_path, seller_gstin, seller_name, client_gstin=client_gstin)
    if profile is not None:
        lines.append("\nLearned Supplier Memory (apply only when consistent with the printed bill):")
        lines.append(f"- Verified Seller: {profile['canonicalName']} (GSTIN: {profile['gstin']}, confirmed {profile['confirmedCount']}x)")
        if profile.get("taxInclusiveHint"):
            lines.append("- Note: supplier prices are often printed inclusive of GST; back-calculate Taxable before GST.")
        hsn_rates = profile.get("hsnRates") or {}
        if hsn_rates:
            pairs = ", ".join(f"{k}->{v:g}%" for k, v in list(hsn_rates.items())[:8])
            lines.append(f"- Verified HSN GST rates: {pairs}")
        ex = profile.get("bestExample") or {}
        if ex.get("rows"):
            ex_json = json.dumps(ex, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"- Prior verified JSON pattern: {ex_json[:380]}")

    try:
        from ai_self_learning import lookup_layout_rules

        layout_ctx = lookup_layout_rules(
            db_path,
            raw_text or "",
            supplier_gstin=(profile["gstin"] if profile else seller_gstin),
            supplier_name=seller_name,
            client_gstin=client_gstin,
        )
        if layout_ctx.get("rules"):
            if not lines:
                lines.append("\nLearned Layout & Corrections Memory:")
            lines.append(f"- Learned layout rules ({layout_ctx.get('matchType')}): {json.dumps(layout_ctx['rules'], ensure_ascii=False)[:320]}")
        for corr in (layout_ctx.get("recentCorrections") or [])[:3]:
            if not lines:
                lines.append("\nLearned Layout & Corrections Memory:")
            lines.append(f"- Prior user correction ({corr.get('field', '')}): {corr.get('from', '')} -> {corr.get('to', '')}")
        for sim in (layout_ctx.get("similarExamples") or [])[:2]:
            if not lines:
                lines.append("\nLearned Layout & Corrections Memory:")
            lines.append(
                f"- Similar resolved invoice ({sim.get('supplierGstin')} inv={sim.get('invoiceNumber')} sim={sim.get('similarity')}): "
                + json.dumps(sim.get("resolvedSummary") or {}, ensure_ascii=False)[:240]
            )
    except Exception:
        pass

    text = "\n".join(lines)
    return text[:1600]


def get_memory_stats(db_path: str) -> Dict[str, Any]:
    if not db_path or not Path(db_path).is_file():
        return {"exists": False, "profiles": 0, "hsnRates": 0, "corrections": 0, "layoutRules": 0, "layoutExamples": 0}
    ensure_memory_db(db_path)
    with _connect(db_path) as conn:
        p = int(conn.execute("SELECT COUNT(*) FROM supplier_profiles").fetchone()[0])
        h = int(conn.execute("SELECT COUNT(*) FROM supplier_hsn_rates").fetchone()[0])
        c = int(conn.execute("SELECT COUNT(*) FROM supplier_corrections").fetchone()[0])
        try:
            from ai_self_learning import ensure_self_learning_schema

            ensure_self_learning_schema(conn)
            lr = int(conn.execute("SELECT COUNT(*) FROM supplier_layout_rules").fetchone()[0])
            le = int(conn.execute("SELECT COUNT(*) FROM layout_memory_examples").fetchone()[0])
        except Exception:
            lr, le = 0, 0
    return {"exists": True, "profiles": p, "hsnRates": h, "corrections": c, "layoutRules": lr, "layoutExamples": le}


def main() -> int:
    parser = argparse.ArgumentParser(description="InvoiceVisionChild Supplier Self-Learning Memory CLI")
    parser.add_argument("--db", required=True, help="Path to supplier_memory.db")
    parser.add_argument("--stats", action="store_true", help="Print DB statistics JSON")
    parser.add_argument("--learn-json", help="Path to JSON payload for learning a supplier record")
    args = parser.parse_args()

    if args.learn_json:
        data = json.loads(Path(args.learn_json).read_text(encoding="utf-8-sig"))
        res = record_supplier_learning(
            db_path=args.db,
            gstin=str(data.get("gstin") or ""),
            canonical_name=str(data.get("canonicalName") or ""),
            original_ocr_name=str(data.get("originalOcrName") or ""),
            preferred_direction=str(data.get("preferredDirection") or ""),
            preferred_recognition_mode=str(data.get("preferredRecognitionMode") or ""),
            tax_inclusive_hint=bool(data.get("taxInclusiveHint")),
            hsn_rates=data.get("hsnRates") or [],
            example_canonical=data.get("exampleCanonical"),
            invoice_number=str(data.get("invoiceNumber") or ""),
            field_diffs=data.get("fieldDiffs") or {},
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(json.dumps(get_memory_stats(args.db), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
