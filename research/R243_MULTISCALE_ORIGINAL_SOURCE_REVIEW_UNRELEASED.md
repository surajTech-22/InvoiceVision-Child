# R243 — source-coordinate 2x alternative OCR with actual Windows Child integration (UNRELEASED)

Date: 2026-10-26. Never treat extra OCR observations as verified invoice fields.

## Implemented

- `INVOICE_OCR_MULTISCALE_REVIEW_R243.py` provides two **independent-source-view readings** (2x grayscale and 2x CLAHE enhancement) on the original **oriented** decoded invoice frame. All 2x word rectangles are converted back to original **oriented-frame coordinates**, bounds-checked and labelled as provisional evidence. Original pixels, the Child's first OCR TSV, all existing zone leaves and accounting data are unchanged.
- Handles Tesseract LF and Windows CRLF TSV hierarchy correctly; rejects bad TSV geometry, oversized source observations, malformed words or unsupported image bounds.
- Integrated into the actual Child category-first `analyze` execution, not only detached unit tests. A missing OCR backend or parser error fails closed and does not authorize accounting/posting.
- The native WPF source review panel displays the two views' original-coordinate observation counts and clears all alternative view metadata when a different invoice is loaded.
- Added synthetic original-frame geometry, Tesseract TSV, source-immutability and no-posting unit tests. Reviewed fields remain unverified and all installer safety gates remain active.

## Successful genuine Windows verification

- **Windows Child build/startup with native R243 panel and safe installer gates:** [40356498334](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40356498334) — success.
- **Actual Windows Child Analyze and approved-region OCR:** [40356721984](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40356721984) — success. R243 returned 29 bounded original-source words from 2x grayscale and 34 from 2x CLAHE on the wholly synthetic printed invoice. No field approvals.
- **Relocated published CPU OCR runtime, actual WPF Child startup, live OCR and isolated rollback rehearsal:** [40356721993](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40356721993) — success. This validates **Tesseract CPU** model/runtime, not bundled Paddle models.

## Three real original-photo tests — private evidence, NOT publicly committed

All three original JPEG SHA-256 hashes matched previously audited sources. Fresh local Tesseract (not a saved Child OCR replay) was run using two PSM modes plus four image transformations. A private source-neighborhood assessment checked text candidates near the prior source OCR evidence boxes. The new varied views improve the *possibility* of finding source text but **do not** certify field accuracy or correct column associations.

The complete original-image OCR strings, particular supplier/item values, original source boxes, and per-field results are retained only in the user's private R243 evidence ZIP. **Original photos and customer OCR are not pushed to GitHub**.

The user explicitly excluded one unreadable Metro invoice identifier from acceptance; no replacement was invented. Other readable characters, printed item-table rows and tax/total relationships still need independent verification.

## Remaining production-release blockers

- Source-aligned automatic recognition is not 100% on the three originals, even with multiscale alternatives; held-out invoices and item-row mapping remain unaccepted.
- No fully validated bundled PaddleOCR CPU/GPU model stack; only a relocated Tesseract CPU runtime has passed genuine Windows OCR tests.
- Real Inno installer/update, on-device existing-Child migration, automatic update, reverse compatibility and rollback have not been fully exercised; simulated rollback is not a substitute.
- The repository is **still public**, with historical real-invoice photos in an earlier source archive; removal from new builds does not mitigate prior Git exposure. The repo owner/admin must address visibility and history exposure.
- **NO Setup.exe, Update.exe, automatic accounting voucher import or production release approved.**
