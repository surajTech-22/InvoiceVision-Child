# R231 — Source-locked review queue and strict OCR conflict handling (UNRELEASED)

Verified 26 October 2026. This is **not** a production release and does not certify invoice accuracy.

## Changes
- Fixed the R230 second-engine comparison bug: mixed numeric agreements/disagreements are now reported as **mixed disagreement**, never as a clean agreement.
- Rejected arbitrary OCR strings with embedded letters/labels instead of stripping all non-digits to manufacture a matching HSN code.
- Differentiated empty, invalid, disagreeing, partially agreeing, and agreeing OCR variants; repeated views from the same secondary engine are never independent source truth.
- Introduced `INVOICE_OCR_REVIEW_QUEUE_R231.py`: an immutable-source, uniquely identified review queue over provisional item groups and date anomalies with exact original OCR text, source token indices and original source boxes. No overwrites, automatic corrections, approval, or Tally/AAH posting.
- The queue is attached to R226 **opt-in** Child review metadata. Disabled by default; not yet rendered by the native WPF review interface.
- Preserved all original sealed 73 baseline source SHA checks and staged R231 as an additive module. Published Windows Child Engine copies are SHA-256 verified.
- The R231 private **offline** review HTML has 50 item row thumbnails, four disputed HSN crop views, and seven date observations; corrections export as manual annotations without modifying originals. This ZIP is held only as a user-visible private artifact and is **not committed to public GitHub**.

## Verified
- New R230 conflict tests run on GitHub Linux/Windows: [Actions run 40320215785](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40320215785), success.
- Genuine .NET 10 WPF Child build/startup and synthetic review-queue invariants passed: [Actions run 40320994329](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40320994329).
- Recovered the **exact** source modules from that Windows build artifact. Private local replay tested all 15 exact original JPEG hashes and **2,361** saved Child OCR text observations: R231 created **50 provisional item-review entries and 7 date-review entries**. The original decoded pixels and OCR values were never changed.
- All 15 R231 review queues were available; 50 is *not* the verified product count. Each proposed entry requires human review. No character, item value, invoice amount or accounting field was certified.

## Outstanding, blockers to Setup.exe / Update.exe
1. **Privacy:** GitHub currently shows InvoiceVision-Child as public despite an embedded original-invoice corpus in the baseline source archive. The repository owner must restrict visibility and assess public history and copies. No further private source images/data should be pushed to this repository.
2. **OCR truth:** Full printed-source character verification and recognition of party/date/item/HSN/tax/total on all originals and held-out invoices, including the four second-engine HSN conflicts.
3. **UI:** Display/approve bounded review annotations in WPF, preserving the source OCR evidence; human annotations alone cannot authorize posting.
4. **Runtime:** Bundle and verify offline OCR dependencies/models; test CPU/GPU fallback and error paths on real Windows systems.
5. **Deployment:** Verify updates, old Child migration, data backups, rollback and Tally/AAH accounting protections.

**Release authorization: FALSE.** Installed applications and user accounting data were not changed.
