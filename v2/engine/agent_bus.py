#!/usr/bin/env python3
"""Thread-safe PeerBus & Stage/Agent tracker for InvoiceVisionChild batch multi-agent OCR.

Allows dynamically dispatched category sub-agents and the continuous AuditorAgent to
exchange typed messages peer-to-peer without routing every intermediate detail through
ManagerAgent.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class AgentMessage:
    msg_id: str
    sender: str
    recipient: str  # specific agent name or "broadcast"
    topic: str      # e.g. "gstins_found", "summary_slabs", "correction_directive", "audit_verdict"
    invoice_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    pass_no: int = 1
    ts: float = field(default_factory=time.time)

    def to_trace(self) -> Dict[str, Any]:
        return {
            "msgId": self.msg_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "passNo": self.pass_no,
            "keys": sorted(list(self.payload.keys())),
            "ts": round(self.ts, 3),
        }


class PeerBus:
    """Per-invoice + global message bus supporting direct sub-agent peer communication."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._messages: Dict[str, List[AgentMessage]] = {}
        self._subscribers: List[Callable[[AgentMessage], None]] = []

    def subscribe(self, cb: Callable[[AgentMessage], None]) -> None:
        with self._lock:
            self._subscribers.append(cb)

    def publish(
        self,
        sender: str,
        recipient: str,
        topic: str,
        invoice_id: str,
        payload: Optional[Dict[str, Any]] = None,
        pass_no: int = 1,
    ) -> AgentMessage:
        msg = AgentMessage(
            msg_id=uuid.uuid4().hex[:10],
            sender=sender,
            recipient=recipient,
            topic=topic,
            invoice_id=invoice_id,
            payload=dict(payload or {}),
            pass_no=pass_no,
        )
        with self._lock:
            self._messages.setdefault(invoice_id, []).append(msg)
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(msg)
            except Exception:
                pass
        return msg

    def read_for(
        self,
        recipient: str,
        invoice_id: str,
        topic: Optional[str] = None,
    ) -> List[AgentMessage]:
        with self._lock:
            msgs = list(self._messages.get(invoice_id, ()))
        out: List[AgentMessage] = []
        for m in msgs:
            if m.recipient in (recipient, "broadcast") or recipient == "*":
                if topic is None or m.topic == topic:
                    out.append(m)
        return out

    def latest_payload(self, recipient: str, invoice_id: str, topic: str) -> Dict[str, Any]:
        hits = self.read_for(recipient, invoice_id, topic=topic)
        return dict(hits[-1].payload) if hits else {}

    def trace_for_invoice(self, invoice_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            msgs = list(self._messages.get(invoice_id, ()))
        return [m.to_trace() for m in msgs]

    def clear_invoice(self, invoice_id: str) -> None:
        with self._lock:
            self._messages.pop(invoice_id, None)


class InvoiceStageTracker:
    """Thread-safe state board updated continuously so ManagerAgent knows every bill's stage & active agents."""

    STAGES = (
        "QUEUED",
        "PREP_QR",
        "VISUAL_OCR",
        "CATEGORY_DISPATCH",
        "PEER_SUBAGENTS",
        "AUDIT",
        "SELF_CORRECT",
        "FINAL_HANDOFF",
        "DONE",
        "FAILED",
    )

    def __init__(self, progress_cb: Optional[Callable[[str, str, Dict[str, Any]], None]] = None) -> None:
        self._lock = threading.RLock()
        self._states: Dict[str, Dict[str, Any]] = {}
        self._progress_cb = progress_cb

    def register(self, invoice_id: str, label: str, source_paths: List[str]) -> None:
        with self._lock:
            self._states[invoice_id] = {
                "invoiceId": invoice_id,
                "label": label,
                "sourcePaths": list(source_paths),
                "stage": "QUEUED",
                "activeAgents": [],
                "completedAgents": [],
                "dispatchedCategories": [],
                "stageChildAgents": {},
                "auditChildAgents": [],
                "passCount": 1,
                "cacheHit": False,
                "startedAt": time.perf_counter(),
                "stageHistory": [{"stage": "QUEUED", "ts": round(time.time(), 3)}],
                "error": "",
            }

    def transition(self, invoice_id: str, stage: str, detail: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            st = self._states.get(invoice_id)
            if not st:
                return
            st["stage"] = stage
            entry: Dict[str, Any] = {"stage": stage, "ts": round(time.time(), 3)}
            if detail:
                entry.update(detail)
                if "dispatchedCategories" in detail:
                    st["dispatchedCategories"] = list(detail["dispatchedCategories"])
                if "cacheHit" in detail:
                    st["cacheHit"] = bool(detail["cacheHit"])
                if "passCount" in detail:
                    st["passCount"] = int(detail["passCount"])
                if "error" in detail:
                    st["error"] = str(detail["error"])
            st["stageHistory"].append(entry)
            snap = dict(st)
        if self._progress_cb:
            try:
                self._progress_cb(invoice_id, stage, snap)
            except Exception:
                pass

    def agent_started(self, invoice_id: str, agent_name: str) -> None:
        with self._lock:
            st = self._states.get(invoice_id)
            if st and agent_name not in st["activeAgents"]:
                st["activeAgents"].append(agent_name)

    def agent_finished(self, invoice_id: str, agent_name: str) -> None:
        with self._lock:
            st = self._states.get(invoice_id)
            if st:
                if agent_name in st["activeAgents"]:
                    st["activeAgents"].remove(agent_name)
                if agent_name not in st["completedAgents"]:
                    st["completedAgents"].append(agent_name)

    def record_child_agent(
        self,
        invoice_id: str,
        stage: str,
        child_name: str,
        elapsed_ms: float,
        status: str = "ok",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            st = self._states.get(invoice_id)
            if not st:
                return
            rec = {
                "agentName": child_name,
                "elapsedMs": round(float(elapsed_ms), 2),
                "status": status,
                "ts": round(time.time(), 3),
            }
            if detail:
                rec["detail"] = dict(detail)
            st.setdefault("stageChildAgents", {}).setdefault(stage, []).append(rec)

    def record_audit_children(self, invoice_id: str, records: List[Dict[str, Any]]) -> None:
        with self._lock:
            st = self._states.get(invoice_id)
            if not st:
                return
            st["auditChildAgents"] = list(records)
            st.setdefault("stageChildAgents", {})["AUDIT"] = [
                {"agentName": r.get("agentName"), "category": r.get("category"), "passed": r.get("passed"), "elapsedMs": r.get("elapsedMs")}
                for r in records
            ]

    def snapshot(self, invoice_id: str) -> Dict[str, Any]:
        with self._lock:
            st = self._states.get(invoice_id)
            return dict(st) if st else {}

    def all_snapshots(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._states.items()}
