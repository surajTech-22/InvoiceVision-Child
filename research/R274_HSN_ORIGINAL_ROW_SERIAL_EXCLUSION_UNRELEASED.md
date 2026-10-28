# R274 — Original HSN source crop excludes adjacent row serial (UNRELEASED)

**28 October 2026. Source-only research; no installer and no accounting writes.**

## Source-photo problem

The original seven-row Nandi table's HSN column has a printed item serial number immediately to the left of the HSN. R272's numeric-only Tesseract frequently joined that serial glyph with the HSN characters. The source photo was read directly from the existing private original JPEG archive, rotated 90° counterclockwise in memory. The original JPEG SHA-256 was checked against `e9b2e78a212c8dbe045c8595c9a9e240e6447e3d9b5962b24efa4233e6a9b3a7`, and the actual oriented decoded image pixel SHA-256 matched `f0357d8770298832b860e8c0e463c55899d090db6aa6dc6797726122fdf7f49d`. All original pixels remained unchanged.

## R274 implementation in the genuine staged Child review

- The actual `integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py` now creates **one additional temporary original-source HSN crop only when** an independently detected printed HSN heading, source-local row rulings, and verified local numeric-only OCR reader are all present.
- The new crop excludes **12% of the left side** of the actual originally bounded HSN cell. It is based on *source pixels*, preserves the right-hand source boundary, uses an in-memory 5× enlarged grayscale view with minimal Gaussian smoothing, and records the exact crop rectangle and source-crop SHA-256.
- It is separately tagged `TEMP_SOURCE_HSN_LEFT_SERIAL_EXCLUSION_R274`, `may_exclude_true_leading_hsn_digit=true`, `may_contain_adjacent_source_ink=true`, `source_text_verified=false`, `posting_eligible=false`; the original untrimmed OCR source crop and its competing alternatives remain intact. It never guesses, normalizes, or posts an HSN.
- Windows `experiments/test_r274_hsn_source.py` verifies the source-only crop is present only with a printed HSN column, and never creates an accepted financial field or item row. Integrated into real .NET WPF Child build workflow.

## Original JPEG numerical comparison: independent truth **not** yet approved

Seven printed HSN rows, checked against only a **DRAFT** source-photo visual transcription:

| Reread | Draft-exact HSN strings |
|---|---:|
| Original full source HSN cell numeric-only PSM7 | **2 / 7** |
| Original source HSN cell with 12% left excluded | **6 / 7** |

The remaining first-row code differs in its **last character**, even after additional right-boundary and page segmentation trials. This is an OCR ambiguity, not a correction. The DRAFT source transcription itself is **not independently certified**, so **zero HSN values are approved**, **zero line items are certified**, and **zero accounting writes are permitted**. Literal HSN codes with leading zeroes are retained as source text, never converted to numbers.

Private detailed replay: `InvoiceVision_R274_Private_HSN_Source_Verification_UNRELEASED.zip` (SHA-256 `57baa2ca8970277e8cc0573339aea2300b5571e1867f1b050f56a83aeb77bf7a`); it contains source private alternatives, a private replay script, a summary and hash manifest **without the original customer photograph**. Do not publish the private ZIP or original source images to GitHub.

## Safety and release status

R274 Windows Child .NET 10 WPF build, startup, original-source OCR regressions, synthetic no-posting acceptance gate and blocked Setup.exe/Update.exe path: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40652376193.

The experiment improves source observation coverage but **not** certified OCR accuracy. Complete actual all-character HSN/quantity/rate/taxable/tax/metadata acceptance on all three private originals, installed Windows+AAH/mobile integration and rollback, and remediation of historical publicly exposed invoice photographs remain unsatisfied. PR remains draft and unmerged.
