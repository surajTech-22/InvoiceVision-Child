from __future__ import annotations

import base64
import ctypes
import difflib
import json
import os
import re
import socket
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def _attach_kill_on_close_job(pid: int) -> Optional[int]:
    """Attach a Windows Job Object with KILL_ON_JOB_CLOSE so child llama-server dies if parent exits/crashes."""
    if os.name != "nt" or not pid:
        return None
    try:
        k32 = ctypes.windll.kernel32
        h_job = k32.CreateJobObjectW(None, None)
        if not h_job:
            return None

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(h_job, 9, ctypes.byref(info), ctypes.sizeof(info))
        h_proc = k32.OpenProcess(0x1F0FFF, False, int(pid))
        if h_proc:
            k32.AssignProcessToJobObject(h_job, h_proc)
            k32.CloseHandle(h_proc)
        return int(h_job)
    except Exception:
        return None

import requests
import cv2
from gst_math import (
    audit_invoice_math,
    clean_party_name_candidate,
    independent_cross_verify_invoice,
    is_suspicious_party_name,
    is_valid_gstin,
    repair_gstin,
    round2,
)
from gst_parser import _clean_party_name, normalize_canonical_dict, parse_document_text_to_canonical
from preprocess import resize_max_side
from supplier_memory import apply_supplier_memory, build_few_shot_prompt_hint

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
        ctx: int = 16384,
        repeat_penalty: float = 1.05,
        parallel: int = 1,
    ):
        self.llama_server_exe = llama_server_exe
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.threads = max(2, min(threads, os.cpu_count() or 8))
        self.ctx = ctx
        self.repeat_penalty = repeat_penalty
        self.parallel = max(1, int(parallel))
        self.port = free_port()
        self.proc: Optional[subprocess.Popen] = None
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"llama_{Path(model_path).stem}.log"
        self._log_file = None
        self._job_handle: Optional[int] = None

    def __enter__(self):
        cmd = [
            self.llama_server_exe,
            "-m", self.model_path,
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-t", str(self.threads),
            "-np", str(self.parallel),
            "-c", str(self.ctx),
            "--temp", "0",
            "--repeat-penalty", str(self.repeat_penalty),
        ]
        if self.mmproj_path:
            cmd.extend(["--mmproj", self.mmproj_path])

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        self._log_file = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        self._job_handle = _attach_kill_on_close_job(self.proc.pid)

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
        if self._job_handle is not None and os.name == "nt":
            try:
                ctypes.windll.kernel32.CloseHandle(self._job_handle)
            except Exception:
                pass
            self._job_handle = None

    @staticmethod
    def _detect_repetition_loop(text: str) -> Optional[int]:
        """Detect stuck decoding loops: trailing identical blocks (16..200 chars), repeated lines, or runaway blank lines."""
        n = len(text)
        if n < 800:
            return None
        # Catch runaway blank/whitespace-only loops (e.g. 60+ trailing whitespace chars or 15+ blank lines)
        m_ws = re.search(r"([ \t]*\n){15,}$", text)
        if m_ws and len(m_ws.group(0)) >= 40:
            return m_ws.start() + 2
        for win, reps in ((16, 10), (24, 8), (32, 7), (40, 6), (64, 6), (96, 6), (140, 5), (200, 5)):
            need = win * reps
            if n < need:
                continue
            unit = text[n - win:]
            if not unit.strip():
                continue
            matched = True
            for k in range(2, reps + 1):
                if text[n - k * win:n - (k - 1) * win] != unit:
                    matched = False
                    break
            if matched:
                return n - ((reps - 1) * win)
        # Catch 8+ repeated trailing lines (e.g. "<td></td>" or similar short variations)
        tail_lines = [ln.strip() for ln in text[-2000:].splitlines() if ln.strip()]
        if len(tail_lines) >= 10 and len(set(tail_lines[-8:])) == 1 and len(tail_lines[-1]) >= 4:
            marker = tail_lines[-1]
            idx = text.rfind(marker)
            for _ in range(6):
                prev = text.rfind(marker, 0, idx)
                if prev == -1:
                    break
                idx = prev
            return idx
        return None

    def chat_image_stream(
        self,
        data_url: str,
        prompt: str,
        timeout_s: int = 600,
        max_tokens: Optional[int] = None,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Stream vision-language output to natural EOS without arbitrary token cutoffs, with repetition-loop guard."""
        content: List[Dict[str, Any]] = [{"type": "image_url", "image_url": {"url": data_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        payload: Dict[str, Any] = {
            "model": "local",
            "temperature": 0.0,
            "stream": True,
            "messages": [{"role": "user", "content": content}],
        }
        if max_tokens is not None and int(max_tokens) > 0:
            payload["max_tokens"] = int(max_tokens)
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "gst_invoice", "strict": True, "schema": json_schema},
            }

        def _do_post(pl: Dict[str, Any]):
            return requests.post(
                f"http://127.0.0.1:{self.port}/v1/chat/completions",
                json=pl,
                timeout=(15, timeout_s),
                stream=True,
            )

        r = _do_post(payload)
        if r.status_code in (400, 422) and "response_format" in payload:
            r.close()
            payload.pop("response_format", None)
            r = _do_post(payload)
        r.raise_for_status()
        r.encoding = "utf-8"

        chunks: List[str] = []
        total_len = 0
        next_loop_check = 800
        finish_reason = ""
        truncated_by_loop = False
        timed_out = False
        stream_start = time.monotonic()
        try:
            for raw_bytes in r.iter_lines(decode_unicode=False):
                if time.monotonic() - stream_start > timeout_s:
                    timed_out = True
                    break
                if not raw_bytes:
                    continue
                line = (raw_bytes.decode("utf-8", errors="replace") if isinstance(raw_bytes, bytes) else str(raw_bytes)).strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    ev = json.loads(data_str)
                except Exception:
                    continue
                choices = ev.get("choices") or []
                if not choices:
                    continue
                c0 = choices[0]
                if c0.get("finish_reason"):
                    finish_reason = str(c0["finish_reason"])
                delta = (c0.get("delta") or {}).get("content") or ""
                if delta:
                    chunks.append(delta)
                    total_len += len(delta)
                    if total_len >= next_loop_check:
                        next_loop_check = total_len + 150
                        joined_so_far = "".join(chunks)
                        trim_at = self._detect_repetition_loop(joined_so_far)
                        if trim_at is not None:
                            truncated_by_loop = True
                            chunks = [joined_so_far[:trim_at]]
                            break
        finally:
            r.close()

        full_text = "".join(chunks)
        eff_reason = finish_reason or ("repetition_loop" if truncated_by_loop else ("wall_timeout" if timed_out else "stop"))
        return {
            "text": full_text,
            "finish_reason": eff_reason,
            "truncated": (finish_reason == "length") or truncated_by_loop or timed_out,
            "truncated_by_loop": truncated_by_loop,
        }

    def chat_image(
        self,
        data_url: str,
        prompt: str,
        max_tokens: Optional[int] = None,
        timeout_s: int = 600,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        if max_tokens is None or int(max_tokens) <= 0:
            return str(self.chat_image_stream(data_url, prompt, timeout_s=timeout_s, max_tokens=None, json_schema=json_schema)["text"])
        content: List[Dict[str, Any]] = [{"type": "image_url", "image_url": {"url": data_url}}]
        if prompt:
            content.append({"type": "text", "text": prompt})
        payload: Dict[str, Any] = {
            "model": "local",
            "temperature": 0.0,
            "max_tokens": int(max_tokens),
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
        json_schema: Optional[Dict[str, Any]] = None,
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
        raw_reply = str(r.json()["choices"][0]["message"]["content"] or "")
        return re.sub(r"<think>.*?</think>", "", raw_reply, flags=re.DOTALL).strip()


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
        if best_tax_sum <= 0.0 and cand_tax_sum > 0.0 and (
            float(best.get("invoiceTotal") or 0.0) > float(best.get("taxableTotal") or 0.0)
            or float(c.get("invoiceTotal") or 0.0) > float(best.get("taxableTotal") or 0.0)
        ):
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


def escalate_with_qwen(
    *,
    llama_server: Path,
    qwen_model: Path,
    qwen_mmproj: Path,
    p2_paths: List[Path],
    work_dir: Path,
    qr_info: Dict[str, Any],
    canon_lighton: Optional[Dict[str, Any]],
    combined_lighton: str,
    client_gstin: str = "",
    direction: str = "Auto",
    memory_db: str = "",
    threads: int = 10,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run Qwen3-VL-4B escalation ONCE over already-preprocessed images and merge with LightOnOCR canonical."""
    qr_einv = (qr_info or {}).get("einvoice")
    qr_upi_meta = (qr_info or {}).get("upi_meta")
    seller_obj = (canon_lighton or {}).get("seller") or {}
    few_shot_hint = build_few_shot_prompt_hint(
        memory_db,
        str(seller_obj.get("gstin") or ""),
        str(seller_obj.get("name") or ""),
        client_gstin=client_gstin,
    )
    qwen_prompt = QWEN_INVOICE_JSON_PROMPT + few_shot_hint

    qwen_dir = work_dir / "qwen_scaled"
    qwen_dir.mkdir(parents=True, exist_ok=True)
    log_dir = work_dir / "logs"
    qwen_replies: List[str] = []
    with LlamaServerSession(str(llama_server), str(qwen_model), str(qwen_mmproj), log_dir, threads=threads) as srv:
        for idx, p2_img in enumerate(p2_paths, 1):
            if progress_cb:
                progress_cb(70 + int(22 * idx / max(1, len(p2_paths))), f"Qwen3-VL-4B verifying page {idx}/{len(p2_paths)}...")
            bgr = cv2.imread(str(p2_img))
            q_img = p2_img
            if bgr is not None and max(bgr.shape[:2]) > 1280:
                q_img = qwen_dir / p2_img.name
                cv2.imwrite(str(q_img), resize_max_side(bgr, 1280))
            reply = srv.chat_image(
                img_to_data_url(str(q_img)),
                qwen_prompt,
                max_tokens=2400,
                timeout_s=600,
                json_schema=QWEN_INVOICE_JSON_SCHEMA,
            )
            qwen_replies.append(reply)

    page_canons = [
        parse_document_text_to_canonical(
            r,
            qr_einvoice=qr_einv,
            known_client_gstin=client_gstin,
            direction_hint=direction,
            qr_upi_meta=qr_upi_meta,
        )
        for r in qwen_replies
    ]
    if len(page_canons) == 1:
        canon_qwen = page_canons[0]
    else:
        merged_obj = dict(page_canons[0])
        all_rows = []
        for pc in page_canons:
            all_rows.extend(pc.get("rows") or [])
        merged_obj["rows"] = all_rows
        for fld in ("taxableTotal", "discountTotal", "cgstTotal", "sgstTotal", "igstTotal", "cessTotal"):
            merged_obj[fld] = 0.0
        for pc in reversed(page_canons):
            if float(pc.get("invoiceTotal") or 0.0) > 0:
                merged_obj["invoiceTotal"] = pc["invoiceTotal"]
                merged_obj["roundOff"] = pc.get("roundOff", 0.0)
                merged_obj["creditNoteTotal"] = pc.get("creditNoteTotal", 0.0)
                break
        canon_qwen = normalize_canonical_dict(merged_obj, "\n\n".join(qwen_replies), qr_einv, qr_upi_meta=qr_upi_meta)

    if canon_lighton is not None:
        c_lo = dict(canon_lighton)
        c_lo["_source"] = "lighton"
        canon_qwen["_source"] = "qwen"
        final_canon = merge_consensus([c_lo, canon_qwen], qr_einv=qr_einv, qr_upi_meta=qr_upi_meta)
        engine_used = "Hybrid(LightOnOCR-2-1B+Qwen3-VL-4B)"
        final_raw = combined_lighton + "\n\n===== QWEN3-VL-4B VERIFICATION =====\n" + "\n\n".join(qwen_replies)
    else:
        final_canon = canon_qwen
        engine_used = "Qwen3-VL-4B-P2"
        final_raw = "\n\n".join(qwen_replies)

    memory_meta = apply_supplier_memory(final_canon, memory_db, client_gstin=client_gstin)
    audit = final_canon.pop("_audit", None) or audit_invoice_math(final_canon, raw_text=final_raw, qr_einvoice=qr_einv)
    if audit.get("fully_balanced") and memory_db and combined_lighton:
        try:
            from ai_self_learning import synthesize_and_save_layout_rule

            synthesize_and_save_layout_rule(
                memory_db,
                combined_lighton,
                canon_lighton,
                {**final_canon, "_audit": audit},
                source="vision_self_learned",
                client_gstin=client_gstin,
            )
        except Exception:
            pass
    return {
        "canonical": final_canon,
        "audit": audit,
        "engineUsed": engine_used,
        "rawOcrText": final_raw,
        "supplierMemory": memory_meta,
    }


def apply_qwen_escalation_to_worker_payload(
    wo: Dict[str, Any],
    *,
    llama_server: Path,
    qwen_model: Path,
    qwen_mmproj: Path,
    work_dir: Path,
    client_gstin: str = "",
    direction: str = "Auto",
    memory_db: str = "",
    threads: int = 10,
    progress_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Upgrade an existing worker_output payload via Qwen3-VL-4B without re-running LightOnOCR."""
    p2_paths = [Path(p) for p in (wo.get("preprocessedImages") or []) if Path(p).is_file()]
    if not p2_paths:
        p2_paths = [Path(p) for p in (wo.get("renderedPageImages") or []) if Path(p).is_file()]
    esc = escalate_with_qwen(
        llama_server=llama_server,
        qwen_model=qwen_model,
        qwen_mmproj=qwen_mmproj,
        p2_paths=p2_paths,
        work_dir=work_dir,
        qr_info=wo.get("qrInfo") or {},
        canon_lighton=wo.get("canonical"),
        combined_lighton=str(wo.get("rawOcrText") or ""),
        client_gstin=client_gstin,
        direction=direction,
        memory_db=memory_db,
        threads=threads,
        progress_cb=progress_cb,
    )
    wo["canonical"] = esc["canonical"]
    wo["audit"] = esc["audit"]
    wo["engineUsed"] = esc["engineUsed"]
    wo["rawOcrText"] = esc["rawOcrText"]
    wo["supplierMemory"] = esc["supplierMemory"]
    raw_tbls = esc["canonical"].pop("rawTablesHtml", None) if isinstance(esc["canonical"], dict) else None
    if raw_tbls:
        wo["rawTablesHtml"] = list(raw_tbls)
    if isinstance(wo.get("agentPipelineTrace"), dict):
        wo["agentPipelineTrace"]["qwenEscalated"] = True
    return wo


TEXT_ANALYZER_SYSTEM_PROMPT = (
    "You are an offline GST invoice HTML-to-JSON structure repair engine. "
    "You receive OCR-extracted Markdown/HTML tables plus exact audit errors from a deterministic parser. "
    "Fix swapped Seller vs Buyer GSTINs, shifted/misnamed tax columns (like C/I GST, S/UT GST, C-GST/S-GST, split Qty/Free), "
    "pre-tax discounts, or missing totals ONLY using numbers present in the OCR text. "
    "Return strict valid JSON matching the schema. Keep names & invoice numbers exact. /no_think"
)


def _compact_ocr_for_text_ai(raw_text: str, limit: int = 7500) -> str:
    txt = str(raw_text or "").strip()
    if len(txt) <= limit:
        return txt
    head_len = int(limit * 0.58)
    tail_len = limit - head_len - 32
    return txt[:head_len] + "\n\n... [MIDDLE TRIMMED] ...\n\n" + txt[-tail_len:]


def analyze_html_with_text_ai(
    *,
    llama_server: Path,
    text_model: Path,
    raw_html: str,
    base_canon: Optional[Dict[str, Any]],
    audit: Dict[str, Any],
    work_dir: Path,
    qr_info: Dict[str, Any],
    client_gstin: str = "",
    direction: str = "Auto",
    memory_db: str = "",
    threads: int = 10,
) -> Dict[str, Any]:
    """Stage 2.5 fast CPU text-only AI repair on LightOn HTML + automatic self-learning rule synthesis."""
    qr_einv = (qr_info or {}).get("einvoice")
    qr_upi_meta = (qr_info or {}).get("upi_meta")
    seller_obj = (base_canon or {}).get("seller") or {}
    few_shot_hint = build_few_shot_prompt_hint(
        memory_db,
        str(seller_obj.get("gstin") or ""),
        str(seller_obj.get("name") or ""),
        client_gstin=client_gstin,
        raw_text=raw_html,
    )
    blocking = "; ".join(str(x) for x in (audit.get("blocking_issues") or [])[:6])
    cur_summary = {
        "sellerGstin": seller_obj.get("gstin", ""),
        "buyerGstin": ((base_canon or {}).get("buyer") or {}).get("gstin", ""),
        "invoiceNumber": (base_canon or {}).get("invoiceNumber", ""),
        "taxableTotal": (base_canon or {}).get("taxableTotal", 0.0),
        "cgstTotal": (base_canon or {}).get("cgstTotal", 0.0),
        "sgstTotal": (base_canon or {}).get("sgstTotal", 0.0),
        "igstTotal": (base_canon or {}).get("igstTotal", 0.0),
        "invoiceTotal": (base_canon or {}).get("invoiceTotal", 0.0),
        "rowCount": len((base_canon or {}).get("rows") or []),
    }
    user_prompt = (
        f"Known client GSTIN (our firm): {client_gstin or 'Unknown'} | Direction hint: {direction}\n"
        f"Audit blocking errors: {blocking or 'none'}\n"
        f"Current parse summary: {json.dumps(cur_summary, ensure_ascii=False)}\n"
        f"{few_shot_hint}\n\n"
        f"OCR Extracted Document (Markdown + HTML Tables):\n{_compact_ocr_for_text_ai(raw_html)}\n/no_think"
    )

    log_dir = work_dir / "logs"
    with LlamaServerSession(str(llama_server), str(text_model), None, log_dir, threads=threads, ctx=8192) as srv:
        reply = srv.chat_text(
            TEXT_ANALYZER_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=2000,
            timeout_s=150,
            json_schema=QWEN_INVOICE_JSON_SCHEMA,
        )

    canon_ai = parse_document_text_to_canonical(
        reply,
        qr_einvoice=qr_einv,
        known_client_gstin=client_gstin,
        direction_hint=direction,
        qr_upi_meta=qr_upi_meta,
    )
    if base_canon is not None:
        c_base = dict(base_canon)
        c_base["_source"] = "lighton"
        canon_ai["_source"] = "text_ai"
        merged_canon = merge_consensus([c_base, canon_ai], qr_einv=qr_einv, qr_upi_meta=qr_upi_meta)
    else:
        merged_canon = canon_ai

    memory_meta = apply_supplier_memory(merged_canon, memory_db, client_gstin=client_gstin)
    merged_audit = merged_canon.pop("_audit", None) or audit_invoice_math(merged_canon, raw_text=raw_html, qr_einvoice=qr_einv)

    cross_info = merged_audit.get("cross_verification") or {}
    merged_audit["two_stage_verification"] = {
        "enabled": True,
        "stage1AuditCrossVerified": True,
        "stage1Passed": bool(cross_info.get("stage1Passed", True)),
        "stage2AiCrossChecked": True,
        "stage2Model": text_model.name,
        "stage2Method": "full_text_ai_repair",
        "agreed": not bool(merged_audit.get("needs_ai_crosscheck")),
        "correctionsApplied": [],
        "suspectFieldsRemaining": list(cross_info.get("suspectFields") or []),
    }

    base_audit = audit if (isinstance(audit, dict) and "fully_balanced" in audit) else audit_invoice_math(base_canon or {}, raw_text=raw_html, qr_einvoice=qr_einv)
    improved = math_fitness({**merged_canon, "_audit": merged_audit}) > math_fitness({**(base_canon or {}), "_audit": base_audit})
    rule_saved: Dict[str, Any] = {"saved": False}
    if merged_audit.get("fully_balanced") and memory_db:
        try:
            from ai_self_learning import synthesize_and_save_layout_rule

            rule_saved = synthesize_and_save_layout_rule(
                memory_db,
                raw_html,
                base_canon,
                {**merged_canon, "_audit": merged_audit},
                source="ai_self_learned",
                client_gstin=client_gstin,
            )
        except Exception:
            pass

    return {
        "improved": improved,
        "fullyBalanced": bool(merged_audit.get("fully_balanced")),
        "canonical": merged_canon,
        "audit": merged_audit,
        "engineUsed": "Hybrid(LightOnOCR-2-1B+Qwen3-1.7B-TextAI)",
        "rawReply": reply,
        "supplierMemory": memory_meta,
        "ruleSaved": rule_saved,
    }


CROSS_VERIFY_SYSTEM_PROMPT = (
    "You are Stage-2 Offline AI Cross-Verifier for Indian GST tax invoices. "
    "Independently read ONLY the OCR header, Bill-To/Buyer block, and footer totals/signature below. "
    "Verify Seller Name, Seller GSTIN, Buyer Name, Buyer GSTIN, Invoice Number, Invoice Date, and Grand Total. "
    "NEVER return field labels, vehicle numbers, UDYAM/MSME/PAN/FSSAI numbers, GST prefixes, table column names, "
    "or city/address fragments (like TUMAKUR, APMC YARD) as a Seller or Buyer Name. "
    "Return exact legal firm names visible on the invoice and return strict valid JSON matching the schema. /no_think"
)

QWEN_CROSS_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "sellerName": {"type": "string"},
        "sellerGstin": {"type": "string"},
        "buyerName": {"type": "string"},
        "buyerGstin": {"type": "string"},
        "invoiceNumber": {"type": "string"},
        "invoiceDate": {"type": "string"},
        "invoiceTotal": {"type": "number"},
        "stage3Accurate": {"type": "boolean"},
        "issueNotes": {"type": "string"},
    },
    "required": [
        "sellerName",
        "sellerGstin",
        "buyerName",
        "buyerGstin",
        "invoiceNumber",
        "invoiceDate",
        "invoiceTotal",
        "stage3Accurate",
        "issueNotes",
    ],
}


def _compact_ocr_for_cross_verify(raw_text: str, head_limit: int = 2800, tail_limit: int = 1400) -> str:
    txt = str(raw_text or "").strip()
    if len(txt) <= head_limit + tail_limit + 64:
        return txt
    return txt[:head_limit] + "\n\n... [LINE ITEMS TRIMMED FOR HEADER/FOOTER CROSS-CHECK] ...\n\n" + txt[-tail_limit:]


def _norm_tokens(s: str) -> set:
    clean = re.sub(r"\b(?:m/s|pvt|private|ltd|limited|co|llp|and)\b", " ", (s or "").lower())
    return {t for t in re.findall(r"[a-z0-9]+", clean) if len(t) >= 2}


def _token_sim(a: str, b: str) -> float:
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def _pick_verified_party_name(
    current_name: str,
    independent_name: str,
    ai_name: str,
    suspect_flag: bool,
    raw_flat_lower: str,
    role_label: str,
    corrections: List[str],
) -> str:
    """Reconcile Stage-3 extracted party name against Stage-1 Audit & Stage-2 AI consensus."""
    cur = str(current_name or "").strip()
    ind_clean = clean_party_name_candidate(independent_name)
    ai_clean = clean_party_name_candidate(ai_name)
    cur_bad, _ = is_suspicious_party_name(cur) if cur else (True, "empty")

    def _is_grounded(cand: str) -> bool:
        toks = _norm_tokens(cand)
        return bool(toks and sum(1 for t in toks if t in raw_flat_lower) >= max(1, len(toks) // 2))

    # 1. If current value is empty or suspicious noise/city/prefix, pick grounded clean AI or Audit name
    if cur_bad:
        for cand, src in ((ai_clean, "Qwen3-1.7B AI"), (ind_clean, "Audit Agent")):
            if cand and (not raw_flat_lower or _is_grounded(cand) or src == "Audit Agent"):
                if cand.lower() != cur.lower():
                    corrections.append(f"{role_label}: '{cur or '<empty>'}' -> '{cand}' ({src})")
                return cand
        return cur

    # 2. If Stage-1 Audit flagged current name as suspect AND AI agrees closely with Stage-1 Audit (2-of-3 consensus)
    if suspect_flag and ai_clean and ind_clean:
        if _token_sim(ai_clean, ind_clean) >= 0.45 and _token_sim(ai_clean, cur) < 0.45:
            corrections.append(f"{role_label}: '{cur}' -> '{ai_clean}' (2-of-3 Audit+AI consensus)")
            return ai_clean

    # 3. If Stage-3 name is not grounded in raw OCR while AI found a cleanly grounded legal name
    if raw_flat_lower and not _is_grounded(cur) and ai_clean and _is_grounded(ai_clean):
        corrections.append(f"{role_label}: '{cur}' -> '{ai_clean}' (grounded AI verification)")
        return ai_clean

    return cur


def cross_verify_with_text_ai(
    *,
    llama_server: Path,
    text_model: Path,
    raw_html: str,
    canonical: Dict[str, Any],
    audit: Optional[Dict[str, Any]],
    work_dir: Path,
    qr_info: Optional[Dict[str, Any]] = None,
    client_gstin: str = "",
    direction: str = "Auto",
    memory_db: str = "",
    threads: int = 10,
) -> Dict[str, Any]:
    """
    Stage-2 Verification Pass: Run compact Qwen3-1.7B header/party/totals cross-check
    and reconcile Stage-3 extraction, Stage-1 Audit independent extraction, and Stage-2 AI.
    """
    t0 = time.perf_counter()
    qr_einv = (qr_info or {}).get("einvoice")
    qr_upi_meta = (qr_info or {}).get("upi_meta")
    canon = json.loads(json.dumps(canonical or {}))
    seller_obj = dict(canon.get("seller") or {})
    buyer_obj = dict(canon.get("buyer") or {})

    cross_s1 = (audit or {}).get("cross_verification") if isinstance(audit, dict) else None
    if not cross_s1:
        cross_s1 = independent_cross_verify_invoice(canon, raw_text=raw_html, qr_einvoice=qr_einv)

    few_shot_hint = ""
    if memory_db:
        try:
            few_shot_hint = build_few_shot_prompt_hint(
                memory_db,
                str(seller_obj.get("gstin") or ""),
                str(seller_obj.get("name") or ""),
                client_gstin=client_gstin,
                raw_text=raw_html,
            )
        except Exception:
            few_shot_hint = ""

    stage3_snap = {
        "sellerName": seller_obj.get("name", ""),
        "sellerGstin": seller_obj.get("gstin", ""),
        "buyerName": buyer_obj.get("name", ""),
        "buyerGstin": buyer_obj.get("gstin", ""),
        "invoiceNumber": canon.get("invoiceNumber", ""),
        "invoiceDate": canon.get("invoiceDate", ""),
        "invoiceTotal": canon.get("invoiceTotal", 0.0),
    }
    stage1_snap = {
        "stage1Passed": bool(cross_s1.get("stage1Passed", True)),
        "independentSellerName": cross_s1.get("independentSellerName", ""),
        "independentBuyerName": cross_s1.get("independentBuyerName", ""),
        "independentInvoiceNumber": cross_s1.get("independentInvoiceNumber", ""),
        "independentInvoiceTotal": cross_s1.get("independentInvoiceTotal", 0.0),
        "suspectFields": list(cross_s1.get("suspectFields") or []),
        "mismatches": list(cross_s1.get("mismatches") or []),
    }

    user_prompt = (
        f"Known client GSTIN (our firm): {client_gstin or 'Unknown'} | Direction hint: {direction}\n"
        f"Stage-3 Extraction: {json.dumps(stage3_snap, ensure_ascii=False)}\n"
        f"Stage-1 Audit Agent Independent Findings: {json.dumps(stage1_snap, ensure_ascii=False)}\n"
        f"{few_shot_hint}\n\n"
        f"OCR Header & Footer Excerpt:\n{_compact_ocr_for_cross_verify(raw_html)}\n/no_think"
    )

    log_dir = work_dir / "logs"
    with LlamaServerSession(str(llama_server), str(text_model), None, log_dir, threads=threads, ctx=4096) as srv:
        reply = srv.chat_text(
            CROSS_VERIFY_SYSTEM_PROMPT,
            user_prompt,
            max_tokens=260,
            timeout_s=90,
            json_schema=QWEN_CROSS_VERIFY_SCHEMA,
        )

    m_json = re.search(r"\{.*\}", reply, re.DOTALL)
    ai_obj = json.loads(m_json.group(0) if m_json else reply)
    if not isinstance(ai_obj, dict):
        ai_obj = {}

    raw_flat_lower = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_html or "")).lower()
    suspect_set = set(cross_s1.get("suspectFields") or [])
    corrections: List[str] = []

    new_seller_name = _pick_verified_party_name(
        str(seller_obj.get("name") or ""),
        str(cross_s1.get("independentSellerName") or ""),
        str(ai_obj.get("sellerName") or ""),
        "seller.name" in suspect_set,
        raw_flat_lower,
        "seller.name",
        corrections,
    )
    new_buyer_name = _pick_verified_party_name(
        str(buyer_obj.get("name") or ""),
        str(cross_s1.get("independentBuyerName") or ""),
        str(ai_obj.get("buyerName") or ""),
        "buyer.name" in suspect_set,
        raw_flat_lower,
        "buyer.name",
        corrections,
    )

    if new_seller_name and new_seller_name != seller_obj.get("name"):
        seller_obj["name"] = new_seller_name
    if new_buyer_name and (not new_buyer_name.lower() == (seller_obj.get("name") or "").lower()):
        if new_buyer_name != buyer_obj.get("name"):
            buyer_obj["name"] = new_buyer_name

    # Repair invalid/missing GSTINs from AI only if Mod-36 checksum validates cleanly
    ai_s_gst = re.sub(r"[^A-Za-z0-9]", "", str(ai_obj.get("sellerGstin") or "").upper())
    cur_s_gst = str(seller_obj.get("gstin") or "").upper()
    if not is_valid_gstin(cur_s_gst) and len(ai_s_gst) >= 14:
        rep_s, ok_s, _ = repair_gstin(ai_s_gst)
        if ok_s and rep_s in raw_flat_lower.upper():
            corrections.append(f"seller.gstin: '{cur_s_gst or '<empty>'}' -> '{rep_s}' (Qwen3-1.7B AI)")
            seller_obj["gstin"] = rep_s

    ai_b_gst = re.sub(r"[^A-Za-z0-9]", "", str(ai_obj.get("buyerGstin") or "").upper())
    cur_b_gst = str(buyer_obj.get("gstin") or "").upper()
    if not is_valid_gstin(cur_b_gst) and len(ai_b_gst) >= 14:
        rep_b, ok_b, _ = repair_gstin(ai_b_gst)
        if ok_b and rep_b != seller_obj.get("gstin") and rep_b in raw_flat_lower.upper():
            corrections.append(f"buyer.gstin: '{cur_b_gst or '<empty>'}' -> '{rep_b}' (Qwen3-1.7B AI)")
            buyer_obj["gstin"] = rep_b

    canon["seller"] = seller_obj
    canon["buyer"] = buyer_obj

    ai_inv_no = str(ai_obj.get("invoiceNumber") or "").strip()
    cur_inv_no = str(canon.get("invoiceNumber") or "").strip()
    if ai_inv_no and (not cur_inv_no or ("invoiceNumber" in suspect_set and str(cross_s1.get("independentInvoiceNumber") or "").upper() == ai_inv_no.upper())):
        if len(ai_inv_no) >= 2 and ai_inv_no != cur_inv_no:
            corrections.append(f"invoiceNumber: '{cur_inv_no or '<empty>'}' -> '{ai_inv_no}' (AI cross-check)")
            canon["invoiceNumber"] = ai_inv_no

    ai_inv_dt = str(ai_obj.get("invoiceDate") or "").strip()
    if ai_inv_dt and not str(canon.get("invoiceDate") or "").strip():
        canon["invoiceDate"] = ai_inv_dt

    canon = normalize_canonical_dict(canon, raw_html, qr_einv, qr_upi_meta=qr_upi_meta)
    memory_meta = apply_supplier_memory(canon, memory_db, client_gstin=client_gstin) if memory_db else {
        "profileFound": False,
        "gstin": str((canon.get("seller") or {}).get("gstin") or ""),
        "canonicalName": str((canon.get("seller") or {}).get("name") or ""),
        "confirmedCount": 0,
        "preferredDirection": "",
        "preferredRecognitionMode": "",
        "appliedRules": [],
    }
    updated_audit = canon.pop("_audit", None) or audit_invoice_math(canon, raw_text=raw_html, qr_einvoice=qr_einv)
    post_cross = updated_audit.get("cross_verification") or {}

    rule_saved: Dict[str, Any] = {"saved": False}
    if updated_audit.get("fully_balanced") and memory_db:
        try:
            from ai_self_learning import synthesize_and_save_layout_rule

            rule_saved = synthesize_and_save_layout_rule(
                memory_db,
                raw_html,
                canonical,
                {**canon, "_audit": updated_audit},
                source="ai_two_stage_verified",
                client_gstin=client_gstin,
            )
        except Exception:
            pass

    stage2_meta = {
        "enabled": True,
        "stage1AuditCrossVerified": True,
        "stage1Passed": bool(cross_s1.get("stage1Passed", True)),
        "stage2AiCrossChecked": True,
        "stage2Model": text_model.name,
        "stage2Method": "compact_header_footer_crosscheck",
        "agreed": bool(post_cross.get("stage1Passed", True)) and bool(ai_obj.get("stage3Accurate", True) or corrections),
        "correctionsApplied": corrections,
        "aiNotes": str(ai_obj.get("issueNotes") or "").strip()[:240],
        "suspectFieldsRemaining": list(post_cross.get("suspectFields") or []),
        "elapsedSec": round(time.perf_counter() - t0, 2),
    }
    updated_audit["two_stage_verification"] = stage2_meta
    if not post_cross.get("suspectFields"):
        updated_audit["needs_ai_crosscheck"] = not bool(updated_audit.get("fully_balanced"))

    return {
        "verified": bool(updated_audit.get("fully_balanced")),
        "agreed": stage2_meta["agreed"],
        "correctionsApplied": corrections,
        "stage1Passed": stage2_meta["stage1Passed"],
        "canonical": canon,
        "audit": updated_audit,
        "engineUsed": "Hybrid(LightOnOCR-2-1B+2Stage-Audit+Qwen3-1.7B)",
        "supplierMemory": memory_meta,
        "ruleSaved": rule_saved,
        "twoStageVerification": stage2_meta,
    }


def apply_two_stage_cross_verify_to_worker_payload(
    wo: Dict[str, Any],
    *,
    llama_server: Path,
    text_model: Path,
    work_dir: Path,
    client_gstin: str = "",
    direction: str = "Auto",
    memory_db: str = "",
    threads: int = 10,
) -> Dict[str, Any]:
    """Run compact Stage-2 Qwen3-1.7B AI cross-check on a worker output payload in-place."""
    xv = cross_verify_with_text_ai(
        llama_server=llama_server,
        text_model=text_model,
        raw_html=str(wo.get("rawOcrText") or ""),
        canonical=wo.get("canonical") or {},
        audit=wo.get("audit") or {},
        work_dir=work_dir,
        qr_info=wo.get("qrInfo") or {},
        client_gstin=client_gstin,
        direction=direction,
        memory_db=memory_db,
        threads=threads,
    )
    wo["canonical"] = xv["canonical"]
    wo["audit"] = xv["audit"]
    wo["supplierMemory"] = xv["supplierMemory"]
    cur_eng = str(wo.get("engineUsed") or "")
    if xv["correctionsApplied"] or "2Stage-Audit" not in cur_eng:
        wo["engineUsed"] = xv["engineUsed"]
    raw_tbls = xv["canonical"].pop("rawTablesHtml", None) if isinstance(xv["canonical"], dict) else None
    if raw_tbls:
        wo["rawTablesHtml"] = list(raw_tbls)
    trace = wo.get("agentPipelineTrace")
    if isinstance(trace, dict):
        trace["twoStageVerification"] = xv["twoStageVerification"]
        trace["selfLearnedRuleSaved"] = bool((xv.get("ruleSaved") or {}).get("saved")) or bool(trace.get("selfLearnedRuleSaved"))
    return wo
