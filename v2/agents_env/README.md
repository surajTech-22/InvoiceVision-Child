# InvoiceVisionChild v2 — Isolated Agent Environment (`agents_env`)

This package prepares a dedicated, isolated environment for InvoiceVisionChild multi-agent extensions and future **Visual Agent Handlers**, separate from the core OCR environment (`Runtime/venv`).

## Layout
- `Runtime/agent_venv`: Isolated Python 3.11 virtual environment (`pillow`, `numpy`, `requests`, `jsonschema`). Core OCR models (`LightOnOCR-2-1B`, `Qwen3-VL-4B`, `PaddleX`) stay untouched inside `Runtime/venv`.
- `visual_agent_handler.py`: Base `VisualAgentHandler` contract (`VisualRegionRequest`, `VisualAgentResult`, `VisualAgentRegistry`, `DefaultVisualAgentHost`).
- `agent_environment.py`: Resolves `Runtime/agent_venv`, crop sandbox (`%LOCALAPPDATA%\InvoiceVisionChild\AgentCrops`), and auto-loads plugins inside `handlers/`.
- `handlers/`: Drop future visual handler modules here exporting `register_handlers(registry)` to intercept low-confidence line items, table crops, stamps, or handwritten totals.

## Setup
```powershell
python setup_agent_env.py --venv-dir "C:\AccountingAutomationHub\InvoiceVisionChild\Runtime\agent_venv"
```
