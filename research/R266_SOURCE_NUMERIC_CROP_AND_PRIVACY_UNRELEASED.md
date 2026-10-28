# InvoiceVision R262–R266 — source-cell OCR, printed Pcs disambiguation and privacy gate (UNRELEASED)

**28 October 2026. Research-only draft. No installed user update, no accounting writes.**

## Actual staged Windows Child implementation

- **R262:** `INVOICE_OCR_COLUMN_BANDS_R261.py` now receives the existing offline Tesseract reader from the real staged Child grid-review integration. Only cells supported by an original printed column heading **and** local original pixel row rulings receive a bounded 4× in-memory OCR crop. Every candidate carries the original source pixel rectangle, SHA-256 of that crop, exact unmodified source OCR words and explicit `source_text_verified=false`, `posting_eligible=false`. A blank PSM7 reread yields a separate PSM6 alternative. Malformed or oversized TSV fails closed.
- **R263:** A quantity `Pcs`/OCR `Pes` heading can be distinguished from a physically distant `Sch/Pcs` discount heading only when one candidate is uniquely bracketed by independently recognized printed CS/CASE and TOTAL/UNITS headings. Multiple bracketed candidates remain ambiguous. This is a column **geometry association**, not numeric verification or generated data.
- **R264:** Border-damaged nonempty text (e.g. numeric OCR with extra glyphs) no longer prevents an independent PSM6 numeric-cell OCR view. Source OCR alternatives are never substituted into existing fields.
- **R265:** For illegible PSM7, one additional **bounded ±4–12 original pixel horizontal** temporary crop is OCRed separately. It is explicitly marked `may_contain_adjacent_source_ink=true` and retains its different source pixel rectangle and SHA-256; no crop interpretation is certified. The previous bounded PSM6 alternative remains available. The expanded crop is deliberately review-only due to potential neighboring cell ink.
- **R266:** A separate GitHub Actions job rejects any **newly added** original images, PDFs, archive bundles and private customer source folder paths in this public research branch. This is not historical data removal. Existing public Git history containing customer photos remains a privacy release blocker requiring admin remediation.

## Verified Windows CI

- [R262 native .NET Child build/startup and numeric crop source tests](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40627586631): **PASS**
- [R263 header disambiguation and Windows integration](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40627883728): **PASS**
- [R265 native Child compilation, original-source OCR regressions, protected installer gate](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40628224104): **PASS**
- [R266 separate public-source addition privacy gate](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40628326203): **PASS**
- [R266 source-witness safety](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40628332274): **PASS**

## Private original-photo observations

A private replay uses the original customer-owned three-photo archive with verified source pixel SHA-256 values. No original photo, invoice number, amount or raw OCR transcript was pushed to GitHub.

- Source A: the R258 cross-view **single provisional product row** remains incomplete; no repeated-grid numeric column added.
- Source B: seven physical row bands remain; R263's independent **CS–Pcs–Total Units** heading geometry resolves the earlier false Pcs-vs-discount ambiguity. The four column families (**HSN, Pcs, Base Rate, Taxable Amount**) permit 28 source-linked numeric-cell hypotheses. All 28 original crop views are **unverified**, frequently with border or neighboring characters. In the private R265 sample, one original PSM7 cell read was a single clean numeric string; 27 needed wider read evidence, and none of the 27 wider raw OCR strings met a strict single-number test. Wider source photos sometimes expose a fuller numeric substring, but that is **not** a verified printed value.
- Source C: one earlier provisional row retains conflicting OCR amount alternatives and its blurred invoice number remains excluded.
- Every original decoded pixel SHA-256 stayed unchanged. **Zero certified rows, zero certified financial fields, zero AAH/Tally writes.**

No photo-derived true financial values, customer addresses or original images are included in this public research document. Detailed private source OCR evidence is user-only.

## Outstanding work / release blockers

1. Source character-level validation of every printed row HSN, quantity, rate, amount, CGST/SGST and complete descriptions against original private photos; Nandi has seven physically located rows, **not seven certified product rows**.
2. Numeric crop correction without neighboring ink, cross-model independent OCR evidence and full validation of model/CPU/GPU fallback; do not silently choose a disputed reading.
3. Supplier, buyer, invoice dates and all line items for three originals and broader invoice layouts must pass the actual Windows Child/mobility JSON `AAH-MOBILE-INVOICE-V3` end-to-end acceptance.
4. Windows installed application data-preserving Update.exe / Setup.exe, AAH/mobile/Child integration and rollback acceptance; production release still blocked.
5. Administrator-managed removal of historical public original customer photos and review of prior download exposure. R266 prevents **new additions only**.

PR remains **DRAFT**, no merge, no installers, no user account changes.