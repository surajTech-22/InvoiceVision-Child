#!/usr/bin/env python3
"""VisualAgentHandler interface, registry, and host bridge for InvoiceVisionChild v2.

Future visual agents (e.g. cropped table row verifier, stamp/signature detector,
handwriting/QTLS reader, or region-level VLM inspector) implement `VisualAgentHandler`
and drop into `agents_env/handlers/` so `ManagerAgent` / `CategoryDispatcher` can invoke
them without touching `gst_parser.py` or core OCR runtime dependencies.
"""
from __future__ import annotations

import importlib.util
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VisualRegionRequest:
    invoice_id: str
    image_path: str
    page_index: int = 0
    category: str = "general"
    prompt: str = ""
    bbox_norm: Optional[Tuple[float, float, float, float]] = None  # (x1, y1, x2, y2) in 0..1
    context: Dict[str, Any] = field(default_factory=dict)
    max_tokens: Optional[int] = None


@dataclass
class VisualAgentResult:
    handled: bool
    category: str
    confidence: float = 0.0
    patch: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""
    elapsed_sec: float = 0.0
    notes: List[str] = field(default_factory=list)


class VisualAgentHandler(ABC):
    """Base contract for custom visual agent handlers hosted in `agents_env`."""

    name: str = "base_visual_handler"
    categories: Tuple[str, ...] = ()

    @abstractmethod
    def can_handle(self, req: VisualRegionRequest) -> bool:
        """Return True if this handler supports the requested category or visual trigger."""

    @abstractmethod
    def handle(self, req: VisualRegionRequest, endpoint_url: Optional[str] = None) -> VisualAgentResult:
        """Process the image or normalized crop and return structured field patches."""


class VisualAgentRegistry:
    """Extensible registry holding built-in and dynamically discovered visual agent handlers."""

    def __init__(self) -> None:
        self._handlers: Dict[str, VisualAgentHandler] = {}

    def register(self, handler: VisualAgentHandler) -> None:
        if not handler.name:
            raise ValueError("VisualAgentHandler.name must be non-empty")
        self._handlers[handler.name] = handler

    def unregister(self, name: str) -> None:
        self._handlers.pop(name, None)

    def get(self, name: str) -> Optional[VisualAgentHandler]:
        return self._handlers.get(name)

    def list_handlers(self) -> List[str]:
        return sorted(self._handlers.keys())

    def matching_handlers(self, req: VisualRegionRequest) -> List[VisualAgentHandler]:
        out: List[VisualAgentHandler] = []
        for h in self._handlers.values():
            try:
                if (not h.categories or req.category in h.categories) and h.can_handle(req):
                    out.append(h)
            except Exception:
                continue
        return out

    def load_plugins_from_dir(self, handlers_dir: Path) -> List[str]:
        """Discover `.py` modules inside `handlers/` exporting `register_handlers(registry)`."""
        loaded: List[str] = []
        if not handlers_dir.is_dir():
            return loaded
        for mod_file in sorted(handlers_dir.glob("*.py")):
            if mod_file.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(f"ivc_visual_{mod_file.stem}", mod_file)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                hook = getattr(mod, "register_handlers", None)
                if callable(hook):
                    hook(self)
                    loaded.append(mod_file.name)
        return loaded


class DefaultVisualAgentHost:
    """Bridges pipeline requests to matching handlers in `VisualAgentRegistry`."""

    def __init__(self, registry: Optional[VisualAgentRegistry] = None, endpoint_url: Optional[str] = None) -> None:
        self.registry = registry or VISUAL_REGISTRY
        self.endpoint_url = endpoint_url

    def dispatch(self, req: VisualRegionRequest) -> VisualAgentResult:
        t0 = time.perf_counter()
        matches = self.registry.matching_handlers(req)
        if not matches:
            return VisualAgentResult(
                handled=False,
                category=req.category,
                elapsed_sec=round(time.perf_counter() - t0, 4),
                notes=["no_visual_handler_registered"],
            )
        notes: List[str] = []
        merged_patch: Dict[str, Any] = {}
        best_conf = 0.0
        raw_parts: List[str] = []
        for handler in matches:
            res = handler.handle(req, endpoint_url=self.endpoint_url)
            if res.handled:
                merged_patch.update(res.patch)
                best_conf = max(best_conf, float(res.confidence))
                if res.raw_response:
                    raw_parts.append(res.raw_response)
                notes.extend(res.notes)
        return VisualAgentResult(
            handled=bool(merged_patch or raw_parts),
            category=req.category,
            confidence=best_conf,
            patch=merged_patch,
            raw_response="\n".join(raw_parts),
            elapsed_sec=round(time.perf_counter() - t0, 4),
            notes=notes,
        )


VISUAL_REGISTRY = VisualAgentRegistry()
