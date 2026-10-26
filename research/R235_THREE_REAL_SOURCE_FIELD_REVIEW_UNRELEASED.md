# R235 — original-photo-anchored field OCR error detection (research / UNRELEASED)

26 October 2026. **User customer invoices and their raw OCR/printed values are intentionally not committed to this public repository.** The complete, private printed-source report and photographs are returned only as a user-owned conversation artifact.

## Verified work

- Manually inspected three original source photos, checked their exact original JPEG SHA-256, and compared **56 selected printed fields**, **9 printed item rows**, and **432 saved actual Child OCR source observations**. This is source verification of *selected fields*, **not complete document field accuracy**.
- Confirmed the Child previously missed a zero in a printed product quantity; unrelated financial summary and item-line values must never be modified to conceal this.
- Confirmed one original bill visibly contains distinct **bill-date** and **e-invoice date** values with different years. This is a *printed source distinction*, not license to rewrite or align their years.
- Confirmed a printed item-table taxable amount and summary taxable amount differ by 0.01 on one original. Both original printed fields must remain separately associated with their source boxes.
- Confirmed some eight-digit HSN observations were glued to an extraneous leading serial digit; other printed two-column tax values were concatenated into one OCR token. The original OCR and source boxes must be kept intact.
- Created `integration/Engine/INVOICE_OCR_FIELD_CONSISTENCY_R235.py` to emit **review-only** flags for invalid dates, differing-year source dates, suspected serial-prefixed nine-digit HSNs and merged decimal cells. Arithmetic proposals require *explicit* mapped quantity/rate/amount, never arbitrary nearby numbers; no original field is auto-replaced.
- Staged the source-consistency module into actual isolated Windows Child Engine and surfaced warnings in the existing native WPF review UI. Native smoke test proves a synthetic warning is displayed and cleared on changing invoices. All installer/AAH/Tally release gates remain intact.
- Real Windows build and startup / source hash / runtime engine hash / privacy and regression tests passed: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40331151811.
- Recovered the exact R235 source module from that Windows build artifact and privately reran it on the three exact original photos' saved Child OCR output: **3/3 source hashes and all 432 original observations preserved**. The module flagged suspicious serial-prefixed HSN text, a joined tax value and a printed date-year difference for manual review; no values accepted for posting.
- This is **saved actual Child OCR replay**, **not new full-model inference on Windows**; a passing source replay does not prove all text recognized.

## Release and privacy blockers

- Complete independent character-level and all-field, every-row accuracy certification is still missing, including an illegible source invoice identifier.
- Actual offline OCR runtime/model packaging, fresh end-to-end Windows CPU processing, representative install/update/rollback and existing data preservation have not met acceptance gates.
- The repository itself is still **public** with an original-photo benchmark archive in its earlier source history. The compiled executable now excludes that benchmark, but only a repository administrator can change visibility through GitHub settings and assess historical disclosure/forks/downloaded copies.
- No production Setup.exe or Update.exe and no accounting/Tally exports may be authorized.

**STATUS: RESEARCH BUILD VERIFIED; COMPLETE INVOICE OCR ACCEPTANCE FAILED / NOT YET CERTIFIED.**
