# R254–R258 — cross-view item-row source witnesses (UNRELEASED)

Date: 27 October 2026. **Research only; no posting or production installers.**

## Real source issues addressed

- R254: Separate printed product-table sections can be proposed independently. Duplicate detections of the same physical numeric cells in one OCR view are suppressed without merging nearby item rows.
- R255: Original-coordinate quantity/amount window widths adapt conservatively to wider document images. Two plausible money tokens in a numeric column remain ambiguous and no row is accepted.
- R256: Original-photo replay detected a regression where a fully enclosed OCR unit note could displace the actual printed quantity column. Only fully enclosed `(PCS)`-style unit notes are excluded from header/bounding marker selection; partly fragmented `CS)` side markers remain available to separate adjacent numeric cells.
- R257: **Printed HSN and FREE** headings are actual column separators. These restrict broad quantity windows so an HSN code or free-quantity value is never silently promoted to the printed sale quantity.
- R258: The genuine staged Child source-grid module now optionally adds a **review-only partial description** when one OCR view contains the physically anchored table heading and the exact quantity/amount cells, but lacks the description, and a second source-coordinate OCR view observes alphabetic fragments on the same row. The output lists independent source token indices for each OCR view, preserves all original source words and rectangles, sets `description_fragment_only=true`, and forbids value certification and accounting writes.

## Genuine Windows verification

- Actual Child WPF compilation, startup, source-layout regressions including split-view source proof and negative source-geometry tests, original-source preservation, publish hash checks and blocked installer gates **passed**: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40463273893
- Relocated published offline CPU Tesseract runtime, genuine native synthetic OCR analysis and isolated rollback **passed**: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40463141446
- Separate actual Windows synthetic OCR analysis **passed**: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40463141315

## Independent private original-photo validation

Verified three unchanged original JPEG file SHA-256 identities from the user's private source archive. Ran fresh Tesseract v5.5.0 offline OCR (grid-removed PSM 11 and 6) against the **exact GitHub R258 Child Engine Python source**: the Git blob hashes of the locally executed R245/R246 files matched the research branch. Zero printed values or originals were changed.

| Private source case | R251 distinct physical hypotheses | R258 distinct physical hypotheses | Accepted rows |
|---|---:|---:|---:|
| A — one-row source | 0 | **1 fragment-supported** | 0 |
| B — seven-row source | 1 | 1 | 0 |
| C — one-row source | 1 | 1 | 0 |

**Interpretation:** The first source now has one source-linked physical row proposal only because its quantity/amount text and incomplete description fragments exist in *different* OCR views. The complete product description and full-character correctness are **not** proven. The seven-row source still has six missing automatic row associations. The third source retains unresolved OCR-value disagreement and its unreadable identifier stays excluded. These results must not be reported as 100% accuracy.

Detailed original hashes, source row geometry, reproducible verification script and source-code hashes are retained in a separate **private user-only evidence ZIP**, never committed to the public repository. Customer photos, saved invoice fields and full OCR text are not included in this public note or new public commits.

## Release status

PR remains **draft**. No merge, Setup.exe, Update.exe, AAH/Tally posting, data migration or user installation was performed. Release is blocked on independently complete character/field/row OCR of the original invoices, migration/install/rollback acceptance on a real installed Windows application, optional non-Tesseract model parity, and remediation of previously exposed invoice photographs in the public repository's historical source archive.
