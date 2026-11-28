#!/usr/bin/env python3
"""Create or verify the isolated Python virtual environment for InvoiceVisionChild agents_env."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def resolve_base_python() -> str:
    """Locate CPython 3.11 base executable from uv or current sys.base_prefix without chaining nested venvs."""
    uv_py = Path.home() / "AppData" / "Roaming" / "uv" / "python"
    if uv_py.is_dir():
        for exe in sorted(uv_py.glob("cpython-3.11*/python.exe"), reverse=True):
            return str(exe)
    base_py = Path(sys.base_prefix) / "python.exe"
    if base_py.is_file():
        return str(base_py)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup isolated InvoiceVisionChild agent_venv")
    parser.add_argument("--venv-dir", default=r"C:\AccountingAutomationHub\InvoiceVisionChild\Runtime\agent_venv")
    parser.add_argument("--skip-pip", action="store_true")
    args = parser.parse_args()

    venv_dir = Path(args.venv_dir).resolve()
    venv_py = venv_dir / "Scripts" / "python.exe"
    env_dir = Path(__file__).resolve().parent
    req_file = env_dir / "requirements.txt"

    if not venv_py.is_file():
        base_py = resolve_base_python()
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([base_py, "-m", "venv", str(venv_dir)], check=True)

    if not args.skip_pip and req_file.is_file():
        subprocess.run([str(venv_py), "-m", "pip", "install", "--upgrade", "pip", "-q"], check=True)
        subprocess.run([str(venv_py), "-m", "pip", "install", "-r", str(req_file), "-q"], check=True)

    probe = (
        f"import sys, PIL, numpy, requests, jsonschema; "
        f"sys.path.insert(0, r'{env_dir.parent}'); "
        f"from agents_env import resolve_agent_environment; "
        f"print(resolve_agent_environment().to_dict())"
    )
    res = subprocess.run([str(venv_py), "-c", probe], capture_output=True, text=True, check=True)
    print(json.dumps({"ok": True, "venv": str(venv_dir), "python": str(venv_py), "probe": res.stdout.strip()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
