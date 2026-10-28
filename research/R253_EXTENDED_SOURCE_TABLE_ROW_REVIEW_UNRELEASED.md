# InvoiceVision R252–R253 — source-bound table header and row-span recovery (UNRELEASED)

Date: 2026-10-27. Research branch `research/invoicevision-r220-source-witness`.

## Fixes in the actual Windows Child Engine

- R252: Do not stop at a plausible item-table heading when it produced zero source-linked item rows; inspect a later real table header. Normalize punctuation on **heading tokens only** (e.g., `QTY.`, `AMOUNT:`) while preserving the raw original OCR text and original source rectangles.
- R253: Replace the narrow 28%-page-height candidate search with a bounded longer scan (at most half-page, maximum 900 original pixels beyond the header). Stop at a subsequently printed complete column heading or at a printed subtotal/total label in the description region. Neither summary rows nor arbitrary currency numbers become accepted accounting items.
- Existing quantity AND amount source-box matching for separate OCR views remains mandatory. All candidate rows, values and source coordinates remain proposals, and no value is corrected, posted or approved.

## Synthetic regressions

In `experiments/test_r245_field_row_anchors.py`:
- A higher placeholder heading has no items; the lower printed table contributes the original 2-view row candidate and the **lower header box** is retained.
- Punctuated headings propose source-linked numeric cells without changing the printed heading strings.
- Header punctuation cannot waive the mandatory description/quantity/amount triad.
- Seven physically distinct printed item lines produce **14 view candidates** (7 per view); a subsequent `TOTAL` section cannot yield a phantom eighth item row. **Accepted item rows remain zero.**

## Genuine Windows verification

- R252 Windows Child WPF build/startup, staging and source-safety tests: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40454278081 — success.
- R253 Windows Child WPF build/startup, R245 and other source-row regressions, original archive preservation and unapproved-installer rejection: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40454686098 — success.
- R253 source-change Windows live CPU OCR synthetic: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40454632855 — success.
- Original 73-file Child source hash and overlay-stage safeguards remain in force. No production setup or update was published.

## Remaining original-photo blockers

The last independently reported private original-photo R251 replay remains:
- Sri Rama: 0 distinct tentative row; the printed single product row is not captured.
- Nandi: 1 distinct tentative row versus 7 manually verified source rows.
- Metro: 1 tentative row with conflicting OCR alternative amount readings; the blurred invoice identifier is intentionally excluded.

Those **R251 real-photo results are not re-scored as improved** merely because this R253 synthetic regression passes. The source photos/private OCR are intentionally absent from the public GitHub commits and were not available for a new private R253 original-photo replay in this session.

Full original-photo character, field and row accuracy, final offline model parity, installed Windows update/rollback and historical public invoice-photo exposure remain release blockers. No AAH/Tally posting, merging, Setup.exe or Update.exe authorized.
