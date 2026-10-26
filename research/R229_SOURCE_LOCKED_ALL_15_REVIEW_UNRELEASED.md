# R229 — source-locked item-table recovery (UNRELEASED)

Date: 26 October 2026. No installed application, accounting, or user file was changed.

## Exact original-source replay, local only

On the exact R229 Child source modules retained from GitHub Windows build [40316129759](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40316129759), the user-owned private R153 checkpoint was replayed locally:

| Scope | Source-backed result |
|---|---:|
| Original JPEG source SHA-256 checks | 15/15 |
| Original saved Child OCR observations | 2,361 / 2,361 |
| Older R227 item-row proposals | 26 on 9/15 photographs |
| Revised R223 after OCR-header aliases | 28 on 11/15 photographs |
| R229 orientation + HSN candidate groups | **50 on 15/15 photographs** |
| Suspicious date source strings | 7 |
| Certified item values or physical cell boundaries | 0 |
| Approved automatic accounting writes | 0 |

All 50 row counts are *review-only hypotheses*. They do **not** assert correctness of the printed product lines or the character recognition, amounts, quantities or total values. R229 distinguishes multiple HSN/EAN tokens in a legitimate single row from distinct descriptions merged into an overly broad row by OCR geometry.

## What changed

- R223 header *role hints* now recognize common OCR misspellings such as `Produci Name` and `Desorption of Coods`, **without changing source text**.
- New `integration/Engine/INVOICE_OCR_LAYOUT_RECOVERY_R229.py` makes a bounded quarter-turn review proposal only when three distinct vertical header roles establish rotated geometry, mapping every returned bounding box to its original photo coordinates. Alternatively, it requires a source HSN header plus source numeric code and nearest original printed description text.
- `INVOICE_OCR_SOURCE_REVIEW_R226.py` attaches those proposals only within the preexisting **opt-in** Child review evidence. It fails closed on optional module failures and never modifies existing zone leaves or enables posting.
- `scripts/stage-r144-integration.py` stages the additive review module only after verifying every byte of the original sealed 73-file source manifest.
- Updated the private original replay harness to check changed R223 source-geometry counts (28) and R229 review groups (50). Original source photos remain private to the user's local checkpoint; they were not newly committed to GitHub.
- Synthetic source-only safety tests and genuine Windows integration and startup are verified on run [40316673277](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40316673277): 35 source-witness/row tests (includes 9 R229 tests), 9 R222 date tests, 6 actual Child review integration tests; separately reran the 9 R229 tests. All passed; release safeguard six rejection checks passed. All published Child engine source SHA readbacks passed.

## Security and release

**Repository privacy alert:** The repository is reported **public**, while its pinned baseline archive is known to contain user-originated invoices and ground-truth information. Request repository owner immediately restrict visibility and assess removal of those assets from public Git history; deleting the current file is not sufficient to revoke prior copies or all old Git objects. No private invoice data is included in this research note.

Remaining blocking acceptance: fresh offline OCR inference on all sources; independently checked printed character/field truth; full recursive zones, user-visible review/editor, held-out invoices; Windows installer/update/migration/backup/rollback. The system deliberately withholds `Setup.exe` and `Update.exe` and all accounting posting.
