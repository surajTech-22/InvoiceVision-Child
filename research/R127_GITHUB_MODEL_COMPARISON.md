# R127 — GitHub advanced recognition benchmark (2026-10-20)

**Decision: Do not replace the existing InvoiceVision Child OCR and zone systems. No application update was made.** This research does not certify full invoice comprehension, printed-box geometry, accounting correctness, or 52-page generalization.

## Evidence

- [Advanced model matrix](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/39385748115) — job overall FAILURE due to UIE; other jobs have independent outputs.
- [UIE final compatibility retry](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/39386387137) — FAILURE despite pinned dependency APIs.
- [RapidOCR baseline synthetic inference](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/39382871665) — 3/3 synthetic samples, not source-image field accuracy on original customer invoices.

| Candidate | Actual GitHub result | Selection |
|---|---|---|
| Docling / TableFormer | Inference succeeded: one table per generated layout (3/3) and all five checked printed cues per sample; ~29.96, 6.42, 6.13 sec/sample. Prior R126 actual photographs: 0 tables Sri Rama, 0 Nandi, 2 Metro. | **Not retained as sole table engine.** May be an offline optional comparator only. |
| LayoutLMv3 FUNSD | Inference succeeded on three generated layouts (~0.5 sec each after model loading); output generic form roles (QUESTION/ANSWER/HEADER), not trained invoice semantic classes. Approximate word boxes. | **Research/training only** pending approved labels and real source-based evaluation. |
| PaddleOCR-VL CPU | Inference completed on one 1260x620 generated page; ~308.19 sec inference; ~426.29 sec including load; recognized invoice header fields and one HTML table. Visual comparison found **TOTAL 500 merged into the item table** and a table polygon reaching y=597 past source frame at y=595. | **Do not use as default or zone authority.** Cost and geometry gates fail. |
| PaddleNLP UIE English | Original run failed on Hugging Face Hub API; retries pinned `huggingface_hub==0.35.3`, `aistudio_sdk==0.2.6`, and `datasets==2.21.0`. Import then advanced, but inference failed: missing `uie-base-en/static/inference.pdmodel`. | **Not retained.** No successful model inference output. |
| Qwen3-VL 2B | Standard GitHub CPU runner had no NVIDIA GPU. Explicit skip before weights download, no inference. | **Not evaluated**; needs suitable GPU runner and resource budget. |
| PP-ChatOCRv4 | No authorized/configured local LLM service. Explicit skip; no end-to-end inference. | **Not evaluated**; no external invoice upload authorized. |

## Retained verified baseline

- **RapidOCR** as fast recognition evidence source.
- **PaddleOCR** as independently verified alternative/second read.
- Keep both OCR readings, original text/coordinates/source hashes, and uncertain conflicts for review.
- Use original printed contours *only when truly visible*; OCR-alignment geometry is optional. Logical zones must work with absent OCR geometry or printed frames.
- **No advanced candidate may overwrite the installed Child or become automatic AAH posting authority without proof from new approved invoices.**

## Acceptance gates for future promotion

1. Use independent, visually approved invoice text and field/zoning ground truth, with held-out unfamiliar layouts.
2. Measure field-level precision/recall, label-to-value links, item/tax/totals segmentation, boundary IoU and zero overlapping interiors; preserve uncertain snippets.
3. Measure Windows CPU/GPU memory, first-run download, warm-run latency and cold start per page.
4. Verify performance and geometry on the 3 original invoices plus the wider Library benchmark, not only 3 synthetic documents.
5. Recheck Child Windows compilation/startup, installed user data safety and updater rollback before any production release.

**Status:** Best production combination remains PaddleOCR + RapidOCR with unchanged current Child. Synthetic model output is not trustworthy training data unless user approved.
