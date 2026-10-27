# R249–R251 — physical item-row safety and split TOTAL VALUE header (UNRELEASED)

**October 27, 2026. User directive:** Skip the unreadable Metro invoice ID, but **do not** invent it or treat any other unrecognized printed text as approved.

## New fixes

1. **R249: stop cross-row duplication/collapse.** `INVOICE_OCR_GRID_TABLE_R246.py` now merges two OCR predictions into one *physical* invoice row only if their original-pixel **quantity AND amount boxes** agree. Broad multiline description rectangles are no longer sufficient. Predictions from the same OCR view never coalesce, and an existing multi-view group must agree with every real numeric cell anchor before incorporating another reading. All conflicting literals and source boxes are preserved.
2. **R250: split "Total Value (incl of tax)" header.** The actual R245 field/row mapper recognizes a source-labelled amount column when a `TOTAL` token precedes a physically nearby OCR token beginning with `VALUE`/OCR-fragmented `INCL`. It does not assume that `Value` or `Total` alone is an invoice item amount. This fixes the previously unreachable header fallback caused by an early `AMOUNT`-token gate.
3. **R251: stop at subtotal/total footer.** Only item rows above printed `TOTAL`/`SUBTOTAL`/`NET` headings in the description-column area are proposed. This rejects financial-summary entries masquerading as additional sale items. All field and row results remain **read-only and unverified**.

## Native Windows acceptance

- [Actual .NET 10 WPF Child compile/startup and R245/R246/R248 tests: run 40450407539](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40450407539) **PASSED**, including new adjacent-multiline-row separation, source-cell drift, duplicate-view, split TOTAL VALUE, and summary/footer tests. Installer blockers remained active.
- [Bundled, relocated offline CPU OCR synthetic analyze + approved-region OCR + isolated rollback: run 40450351243](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40450351243) **PASSED**. This is **synthetic**, not full original-invoice acceptance.
- Exact Windows-staged Python engine artifact SHA-256: `7548b9a4fef935a958bc6d301b7536bb96b1f06c7251c63aa26c5226c89616d9`.

## Independently replayed three original user photographs (PRIVATE; no photos committed)

Downloaded the exact R251 Python engine from the successful Windows CI artifact, then executed **fresh local Tesseract** OCR using both de-ruled 2x PSM 11 and PSM 6 views on the original source JPEG pixels in a private workspace. Checked the JPEG identities and confirmed decoded source pixels remained unchanged.

| User original photograph | Source row hypotheses | Distinct provisional printed item rows | Certified accounting rows |
|---|---:|---:|---:|
| Sri Rama | 0 | 0 | 0 |
| Nandi | 1 | 1 | 0 |
| Metro | 2 (two OCR modes of one row) | 1 | 0 |

Metro's previously false totals-row proposal was removed, but **two OCR readings of the actual amount disagree**. They remain alternative evidence, never auto-selected. Nandi has seven manually identified printed rows, so one automatic proposal is **not complete extraction**. Sri Rama still needs item-row recognition. All source data stay private.

User-owned detailed SHA-256/geometry evidence: `InvoiceVision_R251_Private_Three_Originals_Source_Row_Verification.zip`, SHA-256 `da36378f8ddfc18cc8d18a21fb19c5148e3889dfed54081d72a468ec0147885b`.

## Release not authorized

Original invoice character/field/row OCR is not yet fully accepted. Automatic posting to AAH/Tally stays forbidden. The OCR CPU runtime was tested in a separate Windows workflow, but real installed-machine update/rollback and other engine requirements (including any PaddleOCR model parity) remain unaccepted. The GitHub repo is still **PUBLIC**, with an earlier source archive containing customer invoice photographs; this historic exposure requires repository admin visibility/history remediation. No production `Setup.exe` or `Update.exe` is authorized, and no installed user data was changed.
