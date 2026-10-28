# R261 — original-printed numeric-column witnesses (UNRELEASED)

**27 October 2026 — research only.** This branch is draft. No installer, AAH voucher, invoice field or original source image has been modified.

## Problem and algorithm

R259–R260 isolated seven physical Nandi product bands but did not bind their monetary or quantity columns. Photographed invoice tables are skewed: the rightmost horizontal ruling positions are **not** safely interchangeable with the ruling positions at Pcs, Base Rate or Taxable Amount.

R261 adds `integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py`, called solely from the existing read-only R246 source-grid review.

- Require **actual source OCR heading evidence** for each field: HSN, Pcs/QTY, Base plus independently printed Rate, and Taxable. Missing and multiply located heading observations remain missing/ambiguous, not guessed.
- Use original-source heading positions and physically nearby printed labels to bound the numeric column. Conservative width caps prevent a printed GST amount or Total Units from being silently promoted to Taxable Amount or Pcs.
- Detect **eight separate local printed horizontal row dividers** for a seven-item table **at each numeric column** from unmodified source pixels. Refuse association when the independently detected line grid is incomplete or geometrically ambiguous.
- Emit only literal original OCR word observations, with source view name, original source token index and source pixel rectangle, in each physical row and column. Preserve competing OCR strings from separate views without choosing a numerical winner or computing missing values.
- `certified_financial_fields=0`, `certified_item_rows=0`, `posting_eligible=false`, `accounting_write_permitted=false` and `release_approved=false` in every successful output. Exceptions produce an unavailable read-only metadata result, not trusted fields.
- The isolated Windows Child staging manifest and publish-copy hash gates now include R261. Original 73-file source baseline is still protected.

## Genuine Windows checks

All passed on Windows:

- [R261 genuine Child .NET 10 WPF compile/startup, seven source geometry regressions and blocked installer](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40479681407)
- [Research source-witness safety](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40479685845)

## Private original-photo replay

A separate local research prototype was replayed with Tesseract against all **three SHA-256-verified private original JPEGs**. The prototype implements the same printed-source constraints but is **not represented as a byte-identical download** of the GitHub source. The private evidence archive is `InvoiceVision_R261_Private_Original_Column_Row_Verification_UNRELEASED.zip`.

- Source A: no additional repeating ruled grid; previous one provisional fragment-based row remains separate and unverified.
- Source B: **seven original physical row bands**. Local photo OCR produces independent row/column candidates for some printed HSN, Pcs, Base Rate and Taxable values. Actual source OCR varies between passes; headers missing or competing observations are explicitly unresolved. The columns and printed values are **not fully verified**.
- Source C: no additional repeating ruled grid. Preserve the previously conflicting row amount and exclude the blurred identifier.
- Originals have unchanged source-pixel SHA-256. **Zero accepted financial fields, zero certified rows, zero accounting writes.** No originals or raw customer numbers were committed here.

## Next acceptance barriers

1. Targeted original-pixel rereads of ambiguous printed HSN and Pcs headers, independently constrained by source line geometry.
2. Numeric cell text completeness (including edge strokes), distinct CS / Pcs / Total Units / discounts, and reconciled source-level conflicts **without arithmetic corrections**.
3. Independently verified product descriptions, supplier and buyer fields, dates, tax rates/values and complete seven-row truth, plus all other original invoice cases.
4. Real installed Windows offline runtime and AAH/mobile rollback acceptance; fix historical customer invoice photographs in public repository history through suitable administrator-managed privacy remediation.

Draft PR stays **unmerged and unreleased**. No Setup.exe/Update.exe.
