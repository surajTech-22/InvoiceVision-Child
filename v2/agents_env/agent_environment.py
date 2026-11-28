#!/usr/bin/env python3
"""Environment resolver and sandbox layout helper for InvoiceVisionChild agents_env."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .visual_agent_handler import VISUAL_REGISTRY, VisualAgentRegistry


@dataclass
class AgentEnvironmentInfo:
    agents_env_dir: Path
    runtime_dir: Path
    agent_python_exe: Path
    isolated_venv_active: bool
    handlers_dir: Path
    crop_cache_dir: Path
    loaded_plugins: List[str]
    registered_handlers: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "agentsEnvDir": str(self.agents_env_dir),
            "runtimeDir": str(self.runtime_dir),
            "agentPythonExe": str(self.agent_python_exe),
            "isolatedVenvActive": self.isolated_venv_active,
            "handlersDir": str(self.handlers_dir),
            "cropCacheDir": str(self.crop_cache_dir),
            "loadedPlugins": list(self.loaded_plugins),
            "registeredHandlers": list(self.registered_handlers),
        }


def resolve_agent_environment(
    app_root: Optional[Path] = None,
    registry: Optional[VisualAgentRegistry] = None,
) -> AgentEnvironmentInfo:
    """Resolve the dedicated agent venv, plugin handlers folder, and visual crop sandbox."""
    env_dir = Path(__file__).resolve().parent
    root_candidates: List[Path] = []
    if app_root:
        root_candidates.append(Path(app_root))
    env_override = os.environ.get("AAH_INVOICEVISION_AGENT_ROOT", "").strip()
    if env_override:
        root_candidates.append(Path(env_override))
    root_candidates.extend(
        [
            env_dir.parent,
            Path(r"C:\AccountingAutomationHub\InvoiceVisionChild"),
        ]
    )

    runtime_dir = env_dir.parent / "Runtime"
    agent_py = Path(sys.executable)
    isolated = False

    for cand in root_candidates:
        rt = cand / "Runtime" if (cand / "Runtime").is_dir() else cand
        venv_py = rt / "agent_venv" / "Scripts" / "python.exe"
        if venv_py.is_file():
            runtime_dir = rt
            agent_py = venv_py
            isolated = True
            break
    if not isolated:
        local_venv_py = env_dir / ".venv" / "Scripts" / "python.exe"
        if local_venv_py.is_file():
            agent_py = local_venv_py
            isolated = True

    handlers_dir = env_dir / "handlers"
    handlers_dir.mkdir(parents=True, exist_ok=True)
    crop_cache_dir = Path(os.environ.get("LOCALAPPDATA", str(env_dir))) / "InvoiceVisionChild" / "AgentCrops"
    crop_cache_dir.mkdir(parents=True, exist_ok=True)

    reg = registry or VISUAL_REGISTRY
    plugins = reg.load_plugins_from_dir(handlers_dir)
    return AgentEnvironmentInfo(
        agents_env_dir=env_dir,
        runtime_dir=runtime_dir,
        agent_python_exe=agent_py,
        isolated_venv_active=isolated,
        handlers_dir=handlers_dir,
        crop_cache_dir=crop_cache_dir,
        loaded_plugins=plugins,
        registered_handlers=reg.list_handlers(),
    )
