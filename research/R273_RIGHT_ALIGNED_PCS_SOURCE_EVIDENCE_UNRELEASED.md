# InvoiceVision R273 — source Pcs handwritten-overlaid printed quantity crops (UNRELEASED)

Date: 2026-10-28. **Research-only draft.** No production installer, app data mutation, mobile voucher posting, or public original photographs.

## Problem proved on unchanged genuine original photo

The seven-row source B invoice contains printed piece quantities alongside separate CS and Total Units columns, with handwritten checkmarks crossing some Pcs cells. Earlier numeric-only R272 source rereads included annotation marks and/or trimmed digits. Some original-source HSN crops also included adjacent printed serial numbers. A syntactically clean number is therefore not the same as the printed source value.

## Actual staged Child implementation

- R273 adds an additional **right-aligned Pcs source alternative** in `integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py`, called only on a uniquely source-printed Pcs header and independently detected original printed local row rulings with a callable verified local numeric-only Tesseract reader.
- The temporary crop retains the rightmost roughly 45% of its original source numeric cell and ±2 original-pixel vertical context. It is specifically tagged `TEMP_SOURCE_PCS_RIGHT_ALIGNMENT_R273`, retains original source rectangle and SHA-256, and exposes both `may_exclude_leading_quantity_digits=true` and `may_contain_adjacent_source_ink=true`. This can help read a printed right-aligned digit when a pen mark crosses the left of the cell but can also accidentally trim true multi-digit quantities.
- It is *another competing OCR observation*, never selected as financial truth and NEVER substituted for R261/R272 original source readings. Row certification and accounting writes remain blocked.

## Private source-photo experimental numbers

On all seven Pcs source cells of original photo B, with the original decoded pixel SHA-256 unchanged, compared against a **draft visual transcript only**:

| Source crop OCR variant | Draft-exact source quantity readings |
|---|---:|
| Buffered complete source cell, PSM7 numeric whitelist | 5 of 7 |
| Right-side cropped source cell, PSM7 numeric whitelist | 5 of 7 |
| At least one of the two distinct alternate views | **7 of 7** |

This is **NOT** 100% OCR precision or verified financial accuracy, nor does it provide a reliable automatic method to choose the correct competing reading. All seven quantity values and all 28 sampled money/HSN/quantity source values remain **unverified**. The private replay includes full original source OCR candidate strings and source hashes only in the private user-owned evidence ZIP `InvoiceVision_R273_Private_PCS_Crop_Source_Review_UNRELEASED.zip` (SHA-256 `07c8d6455d7f1395a52a03b03b448fe14f70c7d333454ae9aa649c30bcce8a85`). It deliberately excludes all customer photographs.

## Windows verification

- [Actual Windows .NET 10 Child compilation, startup and source integration tests](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40646487325): **PASS**.
- [R273 source quantity read-only Windows regression plus all previous R261 cell tests](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40646589308): **PASS**.
- [R273 source-witness safety](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40646596923): **PASS**.
- The Windows synthetic offline CPU test on the changed source and the relocatable Windows runtime acceptance are independently checked; neither automatically proves financial-field correctness on the user's installed Windows workstation.

## Remaining gating failures

- Photo B requires **independently confirmed exact printed** HSN, Pcs, Base Rate, Taxable Amount, seven full descriptions, invoice metadata and taxes. Right-crop alternatives have no safe automatic winner-selection rule. Sources A and C still contain incomplete/contradictory original OCR.
- Actual installed Windows Child/AAH/mobile integration, true CPU/GPU/alternate model parity, offline update/rollback and user-data preservation remain unaccepted.
- Historical public Git history exposing customer photos has not been removed by the R266 newly-added-media guard. Requires administrator-managed privacy remediation and prior access review.

**Keep draft PR unmerged. No Setup.exe or Update.exe, no source OCR overwrite, no AAH/Tally accounting posting.**
