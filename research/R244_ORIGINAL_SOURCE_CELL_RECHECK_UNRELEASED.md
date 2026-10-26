# R244 — low-confidence printed-cell rereads in actual Child (UNRELEASED)

Verified 26 October 2026. This is **not** a production installer, not all-field OCR certification and not authorization to send anything to accounting.

## What was actually changed

- Generic `INVOICE_OCR_FIELD_CROP_REVIEW_R244.py` processes the actual Child source-coordinate OCR TSV. It selects **at most four** low-confidence original tokens based on their measured Tesseract confidence, prioritizing potentially ambiguous identifiers and numbers; there are no invoice-specific, vendor-specific, or customer-specific rules.
- For each source token, the engine rereads its **original source-image pixel crop** through bounded 3x grayscale and CLAHE variants using local Tesseract PSM 7 and PSM 6. Each reading is separate source-linked evidence and may conflict with the first OCR; it **never replaces the first recognized value, changes original pixels, or approves accounting**.
- Integrated into the real Child's `Analyze` handoff and existing R226 review metadata, and displayed in the native WPF source-review panel. The panel clears these proposals when switching invoices.
- The local source OCR can fail or return conflicting results. Failures are reported explicitly as `RECHECK_UNAVAILABLE`, preserving original OCR and blocking posting.

## Actual Windows success

- [Native Windows .NET 10 WPF Child compilation and nine R244 crop safety tests, original baseline hash, and eight installer refusal gates: run 40359115656](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40359115656), **success**.
- [Actual Windows Child `analyze` and approved-region `ocr` with R243/R244 review: run 40358925674](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40358925674), **success**. The synthetic invoice exercised **four** actual bounded low-confidence source-cell rereads with accounting permission remaining false.
- [Relocated bundled Windows CPU Python/OpenCV/NumPy/Tesseract engine, true WPF startup, live OCR and isolated backup/rollback: run 40359213497](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40359213497), **success**.
- A previous failed WPF build detected a local-variable name conflict in the review panel. Fixed, then successfully rebuilt; no client application or data was modified.
- The exact Windows-staged Child Python sources and build proof were recovered from CI. **Neither private original photos nor original customer OCR were committed to the public repository.**

## Original-photo private evidence and current limits

Three exact original photographs were reread locally with fresh Tesseract CPU evidence in several source-preserving preprocessing modes. Separate targeted source-rectangle experiments tried low-resolution cell rereads, then checked candidate readings against existing manually audited original source fields. The strict source-crop experiment found possible reference strings in **14 of 17** selected Sri Rama checks, **16 of 21** Nandi checks, and **8 of 15** Metro checks. These are *reference-string presence within known source rectangles*, **not** an automatic-correctness score for the native app. There remain unrecognized data and unresolved row/field associations.

One blurred Metro invoice identifier is **excluded** from acceptance at the user's direction. No substitute value was generated.

The private raw OCR, ground truth and exact mismatch lists are returned only to the user as `InvoiceVision_R244_Real_Invoice_Crop_OCR_Private_Evidence.zip`, **not uploaded to GitHub**.

## Production release still blocked

- Every readable invoice field, source row, source-cell association, HSN, tax, amount, and held-out case has **not** passed automatic recognition acceptance on actual customer documents.
- Bundled PaddleOCR model weights / model parity and CPU/GPU fallback are not fully accepted; only the independently tested bundled CPU/Tesseract path has passed on clean Windows.
- A real on-device Inno Setup/updater deployment with existing user data backup/migration/rollback, automatic update, and recovery is not accepted; R242 was an isolated file-level rollback simulation.
- The public repository retains original private customer invoice photographs in an older source archive/Git history. New clean binaries do not resolve that exposure; an authorized administrator must remediate visibility/history and assess forks/copies.
- Production `Setup.exe` and `Update.exe` remain blocked. **No AAH/Tally voucher posting, installed app update or user accounting data changes.**
