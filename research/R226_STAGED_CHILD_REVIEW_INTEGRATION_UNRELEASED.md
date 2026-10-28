# R226 — opt-in source-linked review inside staged Child (UNRELEASED)

Date: 26 October 2026. Source revision: `d5f84ac93f529f4d6bb95a87fc4ef94f0ed2b6cf`.

## What changed

R226 adds a read-only review hook to the **existing Child recursive-zone engine** rather than changing original invoice recognition. It is staged inside an isolated Windows WPF Child build, with the original source archive and 73-file SHA manifest validated before any overlays are used.

- `integration/Engine/INVOICE_OCR_SOURCE_REVIEW_R226.py` translates real Child source-coordinate OCR TSV to exact source indices, rectangles and text. It proposes date anomaly flags (invalid calendar date and joined date/time) and invokes the unchanged R223 item-row geometry logic.
- The recursive engine `INVOICE_OCR_RECURSIVE_ZONES_R109.py` attaches `metadata.source_row_and_date_review` **only** when `INVOICEVISION_SOURCE_REVIEW_R226=1`. With this flag unset (the default), existing zone results remain unchanged.
- `scripts/stage-r144-integration.py` copies exactly two additive Python modules into `integration-build/InvoiceVisionChild/Engine`. No files from an installed Child, AAH, Tally or user accounting data are modified.
- The Windows build verifies that both added modules plus the existing Paddle/recursive engine files appear **byte-identically** in the real published Child `Engine` folder.
- Every proposal stays in the review metadata. No OCR text/coordinates, recognized zone boundaries, accounting entries, invoice amount or posting flags are rewritten. On malformed OCR TSV or missing optional module, the review field returns `REVIEW_UNAVAILABLE` with no posting authority.

## Provenance limitation

`decoded_frame_sha256` refers explicitly to decoded **image frame bytes** received by the Child. It is NOT the SHA-256 of the original JPEG/PDF bytes; raw uploaded-photo identity cannot be reconstructed by hashing a decoded image. Original source JPEG identity must be separately verified from the archived bytes.

R226's current date flags do not perform the second-pass Tesseract OCR of R222 or silently correct even calendar-valid misread years. The R223 row output is only an OCR-token geometry proposal, not certified cell boundaries/amounts. This opt-in JSON metadata does **not** mean the WPF interface renders a new review panel.

## Verified Windows CI

- Real Child .NET 10 self-contained WPF compilation and startup smoke: pass.
- Original 73/73 Child source-file SHA verification: pass.
- Published engine files (Paddle, recursive zone engine, and two added review files) exact hash readback: pass.
- 26 existing R220/R221/R223 source-geometry tests, 9 R222 date-safety tests, **6 new R226 tests in the actual isolated Child Engine**: 41/41 pass.
- Installer gate still intentionally refuses unsupported Setup.exe/Update.exe production packages; six safety rejection checks pass.
- GitHub run: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40304085487 (earlier successful R226 hook run). Latest post-hash-readback run should also pass before closing this work.

## Outstanding before user release

Fully evaluate all original photos and held-out invoices with ground-truth characters, party/date/item/HSN/tax fields and real printed cell boundaries. Recheck original OCR wrong-year dates with independent source crops. Integrate the metadata into a visible, editable review UI; validate the offline OCR runtime, CPU/GPU fallback, updates and rollback on Windows. Keep automatic accounting/Tally posting disabled and avoid installing any new Child build until production acceptance passes.
