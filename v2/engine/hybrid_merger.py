from __future__ import annotations

import base64
import difflib
import json
import os
import socket
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from gst_math import audit_invoice_math, is_valid_gstin, round2
from gst_parser import _clean_party_name, normalize_canonical_dict

QWEN_INVOICE_JSON_PROMPT = """Extract all fields from this Indian GST Tax Invoice accurately as a single valid JSON object ONLY (no markdown explanation).
Use exact numbers printed on the bill (do not guess). If Taxable per line is omitted, capture gross/discount/cgst/sgst/lineTotal accurately.
Schema:
{
  "seller": {"name": "...", "gstin": "15-char GSTIN"},
  "buyer": {"name": "...", "gstin": "15-char GSTIN"},
  "documentType": "Tax Invoice",
  "placeOfSupply": "...",
  "invoiceNumber": "...",
  "invoiceDate": "YYYY-MM-DD",
  "taxableTotal": 0.0,
  "cgstTotal": 0.0,
  "sgstTotal": 0.0,
  "igstTotal": 0.0,
  "creditNoteTotal": 0.0,
  "roundOff": 0.0,
  "invoiceTotal": 0.0,
  "rows": [
    {
      "description": "...",
      "hsnSac": "...",
      "quantity": 0.0,
      "unit": "",
      "rate": 0.0,
      "discount": 0.0,
      "taxable": 0.0,
      "gstRate": 0.0,
      "cgst": 0.0,
      "sgst": 0.0,
      "igst": 0.0,
      "lineTotal": 0.0
    }
  ]
}"""


QWEN_INVOICE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "seller", "buyer", "documentType", "placeOfSupply", "invoiceNumber", "invoiceDate",
        "taxableTotal", "cgstTotal", "sgstTotal", "igstTotal", "creditNoteTotal", "roundOff", "invoiceTotal", "rows"
    ],
    "properties": {
        "seller": {
            "type": "object",
            "required": ["name", "gstin"],
            "properties": {"name": {"type": "string"}, "gstin": {"type": "string"}},
        },
        "buyer": {
            "type": "object",
            "required": ["name", "gstin"],
            "properties": {"name": {"type": "string"}, "gstin": {"type": "string"}},
        },
        "documentType": {"type": "string"},
        "placeOfSupply": {"type": "string"},
        "invoiceNumber": {"type": "string"},
        "invoiceDate": {"type": "string"},
        "taxableTotal": {"type": "number"},
        "cgstTotal": {"type": "number"},
        "sgstTotal": {"type": "number"},
        "igstTotal": {"type": "number"},
        "creditNoteTotal": {"type": "number"},
        "roundOff": {"type": "number"},
        "invoiceTotal": {"type": "number"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["description", "hsnSac", "quantity", "unit", "rate", "discount", "taxable", "gstRate", "cgst", "sgst", "igst", "lineTotal"],
                "properties": {
                    "description": {"type": "string"},
                    "hsnSac": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "rate": {"type": "number"},
                    "discount": {"type": "number"},
                    "taxable": {"type": "number"},
                    "gstRate": {"type": "number"},
                    "cgst": {"type": "number"},
                    "sgst": {"type": "number"},
                    "igst": {"type": "number"},
                    "lineTotal": {"type": "number"},
                },
            },
        },
    },
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def img_to_data_url(image_path: str) -> str:
    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = "image/png" if ext == "png" else "image/jpeg"
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class LlamaServerSession:
    def __init__(
        self,
        llama_server_exe: str,
        model_path: str,
        mmproj_path: Optional[str],
        log_dir: Path,
        threads: int = 10,
        ctx: int = 8192,
        repeat_penalty: float = 1.05,
    ):
        self.llama_server_exe = llama_server_exe
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.threads = max(2, min(threads, os.cpu_count() or 8))
        self.ctx = ctx
        self.repeat_penalty = repeat_penalty
        self.port = free_port()
        self.proc: Optional[subprocess.Popen] = None
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"llama_{Path(model_path).stem}.log"
        self._log_file = None

    def __enter__(self):
        cmd = [
            self.llama_server_exe,
            "-m", self.model_path,
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-t", str(self.threads),
            "-c", str(self.ctx),
            "--temp", "0",
            "--repeat-penalty", str(self.repeat_penalty),
        ]
        if self.mmproj_path:
            cmd.extend(["--mmproj", self.mmproj_path])

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._log_file = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            cmd,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

        deadline = time.time() + 120
        url = f"http://127.0.0.1:{self.port}/health"
        while time.time() < deadline:
            if self.proc.poll() is not None:
                tail = self.log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
                raise RuntimeError(f"llama-server exited early ({self.proc.returncode}):\n{tail}")
            try:
                r = requests.get(url, timeout=2)
                if r.status_code == 200:
                    return self
            except Exception:
                pass
            time.sleep(0.4)
        raise TimeoutError(f"llama-server health timeout on port {self.port}")

    def __exit__(self, exc_type, exc, tb):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=4)
                except Exception:
                    pass
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass

    def chat_image(
        self,
        data_url: str,
        prompt: str,
        max_tokens: int = 3200,
        timeout_s: int = 240,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        content: List[Dict[str, Any]] = [{"type": "image_url", "image_url": {"url": data_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        payload: Dict[str, Any] = {
            "model": "local",
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "gst_invoice", "strict": True, "schema": json_schema},
            }
        r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=payload, timeout=timeout_s)
        if r.status_code in (400, 422) and "response_format" in payload:
            payload.pop("response_format", None)
            r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=payload, timeout=timeout_s)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 380,
        timeout_s: int = 90,
    ) -> str:
        payload: Dict[str, Any] = {
            "model": "local",
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        r = requests.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", json=payload, timeout=timeout_s)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def math_fitness(canon: Dict[str, Any]) -> tuple:
    a = canon.get("_audit") or audit_invoice_math(canon)
    has_header_tx = float(canon.get("invoiceTotal") or 0.0) <= 0.0 or float(canon.get("taxableTotal") or 0.0) > 0.0
    return (
        1 if a["fully_balanced"] else 0,
        1 if a["row_count"] > 0 else 0,
        1 if has_header_tx else 0,
        1 if (a["row_count"] > 0 and len(a["bad_rows"]) == 0 and a["grand_balanced"] and a["taxable_match"] and a["tax_match"]) else 0,
        1 if (a["row_count"] > 0 and len(a["bad_rows"]) == 0) else 0,
        1 if a["grand_balanced"] else 0,
        1 if a["taxable_match"] else 0,
        1 if a["tax_match"] else 0,
        -len(a["bad_rows"]),
        1 if a["seller_gstin_valid"] else 0,
        1 if a["buyer_gstin_valid"] else 0,
        a["row_count"],
        -min(a["grand_diff"], 9999.0),
    )


def merge_consensus(
    candidates: List[Dict[str, Any]],
    qr_einv: Optional[Dict[str, Any]] = None,
    qr_upi_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Math-aware consensus reconciliation across primary LightOnOCR-2-1B and escalated Qwen3-VL-4B."""
    if not candidates:
        return {}
    if len(candidates) == 1:
        return normalize_canonical_dict(candidates[0], qr_einvoice=qr_einv, qr_upi_meta=qr_upi_meta)

    ranked = sorted(candidates, key=math_fitness, reverse=True)
    best = json.loads(json.dumps(ranked[0]))

    s_cands = [(c.get("seller") or {}).get("gstin", "") for c in candidates if is_valid_gstin((c.get("seller") or {}).get("gstin"))]
    if s_cands:
        best["seller"]["gstin"] = Counter(s_cands).most_common(1)[0][0]
    best_seller_name = ((best.get("seller") or {}).get("name") or "").strip()
    if not best_seller_name or not _clean_party_name(best_seller_name):
        for c in candidates:
            nm = ((c.get("seller") or {}).get("name") or "").strip()
            if nm and _clean_party_name(nm):
                best["seller"]["name"] = nm
                break

    b_cands = [(c.get("buyer") or {}).get("gstin", "") for c in candidates if is_valid_gstin((c.get("buyer") or {}).get("gstin"))]
    if b_cands:
        best["buyer"]["gstin"] = Counter(b_cands).most_common(1)[0][0]
    best_buyer_name = ((best.get("buyer") or {}).get("name") or "").strip()
    if not best_buyer_name or not _clean_party_name(best_buyer_name):
        for c in candidates:
            nm = ((c.get("buyer") or {}).get("name") or "").strip()
            if nm and _clean_party_name(nm):
                best["buyer"]["name"] = nm
                break

    best_expected = round2(
        float(best.get("taxableTotal") or 0.0)
        + float(best.get("cgstTotal") or 0.0)
        + float(best.get("sgstTotal") or 0.0)
        + float(best.get("igstTotal") or 0.0)
        + float(best.get("cessTotal") or 0.0)
        - float(best.get("creditNoteTotal") or 0.0)
    )
    for c in candidates:
        if float(best.get("invoiceTotal") or 0.0) <= 0.0 and float(c.get("invoiceTotal") or 0.0) > 0.0:
            best["invoiceTotal"] = c["invoiceTotal"]
            best["roundOff"] = c.get("roundOff", best.get("roundOff", 0.0))
            best["creditNoteTotal"] = c.get("creditNoteTotal", best.get("creditNoteTotal", 0.0))
        elif (
            best_expected > 10.0
            and abs((best_expected + float(best.get("roundOff") or 0.0)) - float(best.get("invoiceTotal") or 0.0)) > 2.0
            and float(c.get("invoiceTotal") or 0.0) > 0.0
            and abs(float(c["invoiceTotal"]) - best_expected) <= 1.0
        ):
            best["invoiceTotal"] = c["invoiceTotal"]
            best["roundOff"] = round2(float(c["invoiceTotal"]) - best_expected)
        best_tax_sum = float(best.get("cgstTotal") or 0.0) + float(best.get("sgstTotal") or 0.0) + float(best.get("igstTotal") or 0.0)
        cand_tax_sum = float(c.get("cgstTotal") or 0.0) + float(c.get("sgstTotal") or 0.0) + float(c.get("igstTotal") or 0.0)
        if best_tax_sum <= 0.0 and cand_tax_sum > 0.0 and float(best.get("invoiceTotal") or 0.0) > float(best.get("taxableTotal") or 0.0):
            best["cgstTotal"] = c.get("cgstTotal", 0.0)
            best["sgstTotal"] = c.get("sgstTotal", 0.0)
            best["igstTotal"] = c.get("igstTotal", 0.0)

    inv_votes: Counter = Counter()
    dt_votes: Counter = Counter()
    inv_sources: Dict[str, str] = {}
    for c in candidates:
        w = 2 if math_fitness(c)[0] == 1 else 1
        ino = (c.get("invoiceNumber") or "").strip()
        idt = (c.get("invoiceDate") or "").strip()
        if ino:
            inv_votes[ino] += w
            src = str(c.get("_source") or "")
            if src:
                inv_sources[src] = ino
        if len(idt) == 10 and idt[4] == "-":
            dt_votes[idt] += w
    if inv_votes:
        top_inv = inv_votes.most_common(2)
        if (
            len(top_inv) == 2
            and top_inv[0][1] == top_inv[1][1]
            and "qwen" in inv_sources
            and "lighton" in inv_sources
            and inv_sources["qwen"] != inv_sources["lighton"]
        ):
            q_inv = inv_sources["qwen"]
            l_inv = inv_sources["lighton"]
            if abs(len(q_inv) - len(l_inv)) <= 1 and difflib.SequenceMatcher(None, q_inv.upper(), l_inv.upper()).ratio() >= 0.75:
                best["invoiceNumber"] = q_inv
            else:
                best["invoiceNumber"] = top_inv[0][0]
        else:
            best["invoiceNumber"] = top_inv[0][0]
    if dt_votes:
        best["invoiceDate"] = dt_votes.most_common(1)[0][0]

    for c in candidates:
        if not best.get("placeOfSupply") and c.get("placeOfSupply"):
            best["placeOfSupply"] = c["placeOfSupply"]
        if (best.get("documentType") in ("", "Tax Invoice")) and c.get("documentType") not in ("", "Tax Invoice"):
            best["documentType"] = c["documentType"]
        if not best.get("rawTablesHtml") and c.get("rawTablesHtml"):
            best["rawTablesHtml"] = c["rawTablesHtml"]

    return normalize_canonical_dict(best, qr_einvoice=qr_einv, qr_upi_meta=qr_upi_meta)
