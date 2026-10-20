# R153 unreleased source-linked label/value research (2026-10-20)

This branch is isolated from main and the installed Child/AAH application.

Self-contained, source-hash-verified continuation checkpoint saved to persistent Library:
`/InvoiceVision/Checkpoints/IV_R153_LABEL_VALUE_ASSOCIATIONS_UNRELEASED.zip`
ZIP SHA256 `2ace5320ec9aba87a97087a5ddf48994871af4910219b56293d141014397857c`.
Contains 15 exact original JPEG bytes, original Windows Child PaddleOCR UTF-8 report, scripts, 17 deterministic safety tests, 15 side-by-side originals + OCR association overlays, full JSON report and checkpoint notes.

## Actual local source replay
- 15 real original invoice sources rehashed 15/15; all match original model provenance.
- All 2361 original OCR text tokens retained, zero source-membership loss.
- 17 field-oriented R152 anchors, 11 proposed raw value mentions on 8/15 images. **No accepted values or printed physical boxes**.
- Source examples: sideways Sri Rama GRAND TOTAL -> 1140.00 OCR, Nandi Bill NO -> :E55409 and Bill Date -> raw :04/09/202514:37:09 (known to conflict with user's confirmed printed year 2026); 1000258309 Net Payable -> :5181.00; 1000258314 GRAND TOTAL -> 1431; Metro Net Amount -> 3813.75. These are unverified source text-neighbor hypotheses.
- Refuses alpha-only invoice IDs (old false detection DISTRIBUTOROFPAO), phone-like buyer strings (PHNO9i), discounts as grand totals, remote/unmatched data, geometry-invalid text and arbitrary date rewriting.
- No new source pixels, physical contours, data posting, implied invoice geometry or Child installation.

## Independent CI
R153 research-only safety regression passed on both Windows and Linux, workflow run 39471097430, with 17 controls. **CI does not perform the full 15-photograph replay**; original source-hash replay and visual contact sheet are in the checksummed persistent checkpoint.

## Remaining release gates
9 real unknown-only semantic zones are not resolved by isolated OCR associations; physical printed cells and structure, all 51 unique/52 logical cases, OCR value accuracy and 68 inherited association errors, held-out invoice generalization, full native WPF Child integration, CPU offline & optional GPU, AAH posting protections, installer-update/backup/rollback and data preservation are not certified.
Setup.exe and Update.exe are withheld until truly 100% accepted.
