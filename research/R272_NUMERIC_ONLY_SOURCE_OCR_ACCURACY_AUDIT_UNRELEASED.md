# R272 original-pixel numeric-only OCR: measured improvement, NOT certified (UNRELEASED)

**2026-10-28. Research branch only; do not release or post to accounting.**

## Implemented in actual isolated Windows Child

- `integration/Engine/INVOICE_OCR_NUMERIC_ONLY_R272.py` validates an explicit **existing, local, absolute** Tesseract executable path. It sends a bounded in-memory PNG to `tesseract stdin stdout --psm 7 -c tessedit_char_whitelist=0123456789.,- tsv`, with a 15-second timeout, maximum image dimensions, maximum input/output sizes and UTF-8 validation. No private customer crop files are persisted on disk, no shell or network, no automatic invoice corrections.
- `INVOICE_OCR_COLUMN_BANDS_R261.py` now optionally retains the independent numeric-only result as `TEMP_NUMERIC_WHITELIST_PSM7_R272` with its original-pixel rectangle, image crop SHA-256, unmodified OCR literal and explicit `cannot_resolve_decimal_or_digit_conflicts=true`. It remains a **nonposting, noncertified** source witness. Original OCR views and all other alternatives are retained.
- `INVOICE_OCR_GRID_TABLE_R246.py` and isolated Windows `scripts/stage-r144-integration.py` connect this optional reader only when a verified installed Tesseract executable exists. Otherwise the existing grid-review path runs as before.
- New Windows unit tests validate no private temporary files, PNG over stdin, strict numeric argument list, local executable only, malformed TSV/output rejection, original-pixel invariants and no financial-field or row acceptance. An initial Windows-only `Path` type-check mistake was caught by the CI regression and fixed before verification.

## Genuine Windows status

All **passed after the path-type fix** on commit `83e73da67140f1844c20d1c58b2417c70c30e765`:
- [Windows .NET 10 WPF Child compile/startup, R272 source integration and all source safety regressions](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40645032557)
- [Actual Windows synthetic offline CPU OCR integration](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40645032527)
- [Offline relocatable Windows runtime and rollback verification](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40645032695)
- [Reject newly added private customer media](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40645032540)

These are CI validations of staged research code, **not** tests of the user's installed app and **not** original-invoice financial accuracy acceptance.

## Private original-photo evidence and limits

The original seven-row source B photograph was read only. Its oriented decoded pixel SHA-256 and all 28 original numeric source-cell crop rectangles were preserved. An independent local Python replay used the exact **same in-memory Tesseract CLI** and the same user-private R265 cell crop rectangles.

- Of 28 source numeric-cell OCR results, **22 were syntactically well-formed numeric strings** after the numeric whitelist (R265 initial unfiltered crop had 1).
- Compared with a **DRAFT visual reading** of the printed table (not independently certified), only **12 of 28** numeric strings exactly matched. The 22/28 figure is formatting, *not* correctness. The draft comparison cannot be used as the source-of-truth acceptance itself.
- Five other local image preprocessing variants each produced only 3–11 provisional exact matches against the same draft visual transcription, with at most 15 distinct matching cells across the set. None was added as an automatic invoice correction.
- Source image pixels were unchanged, original OCR words preserved, **zero** certified financial fields, **zero** certified item rows, no AAH/Tally writes.
- Private ZIP: `InvoiceVision_R272_Private_Numeric_Source_Replay_UNRELEASED.zip`, SHA-256 `8ec37cc92edbdce4e3e2479d71876e3c1e6c5428962fdd8bea9267c667695a9e`. It contains source OCR candidates and a draft comparison, **not the original customer photo**. Do not put its contents in public GitHub.

## Remaining release blockers

1. Exact character/box agreement against independently verified source transcriptions for **all three original invoices**, including Nandi's seven physical rows, tax components, supplier/buyer labels and date variants. At least 16 of Nandi's 28 sampled numeric cells are **not even an exact match to the provisional visual reading** under R272.
2. Actual installed Windows Child + AAH/mobile JSON `AAH-MOBILE-INVOICE-V3` end-to-end acceptance and rollback with user-data preservation; complete CPU/GPU/Paddle fallback parity.
3. Existing customer photographs exposed in historical public GitHub archive remain unremediated. A new-file privacy gate does **not** remove existing history. Repository administrator remediation and prior-access review remain mandatory.

PR stays draft, no Setup.exe, no Update.exe, no Tally posting or customer data mutation.
