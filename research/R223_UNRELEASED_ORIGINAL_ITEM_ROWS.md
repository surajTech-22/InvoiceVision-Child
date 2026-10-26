# R223 — original-photo item-row grouping (UNRELEASED)

**26 October 2026. No changes to the installed Windows Child, AAH, Tally or accounting data.**

## Source-provenance replay performed locally
- 15 exact original invoice JPEGs recovered from the user's retained InvoiceVision checkpoint. 15/15 SHA-256 checks match original saved Windows Child OCR report; source image dimensions checked.
- 2,361/2,361 original OCR observations and original OCR bounding rectangles preserved with zero substituted text.
- 26 **review-only** item-row hypotheses across 9/15 original invoices. **6/15 are unresolved** by this conservative technique.
- 66 OCR tokens appear to span proposed column boundaries and are explicitly flagged, not split into invented values.
- Original-photograph counts visually checked for five invoices: Nandi Marketing 1000258304 (10 rows); Adarsh Papad 1000258305 (1); S A Enterprises 1000258306 (3); 1000258314 (2); Amazon Distributors c694fd17... (4). These are row counts only, NOT accepted field values or fully certified physical cells.
- Main Amazon product rows are separated from its later promotional subtable and summary; an OCR misreading of 'Total' as 'Ional' is not permitted to create a product row without source HSN evidence.
- Previously established R220–R222 regression suite: 24/24 passed locally. R223 immutable-source/row-safety tests: 11/11 passed locally. **35/35 passed** locally.
- Annotated side-by-side originals/OCR geometry, full per-source replay results and logs were packaged in `InvoiceVision_R223_Original_ItemRows_Research.zip` (user-visible local file), with SHA-256 `8fa5faba6e13e15a23306586d1103ff725d3765affef886e5518218583422977`. User image content and private OCR corpus were **not** committed to GitHub.

## Design/limitations
- Runs against original saved OCR text/boxes with SHA-verified image bytes, a conservative header-relative skew hypothesis and source-token-to-row grouping.
- Returns original source token indices and boxes and a conservative column **hint** only. Never modifies OCR, fabricates separated OCR values, certifies a printed physical table border, or permits accounting posting.
- This is NOT a new OCR character-recognition engine; missed tokens and wrong character readings remain. Sideways pages and weak-layout cases remain unsupported.
- Never interpret the proposal count as end-to-end correct rows, verified item amounts, invoice totals, or 100% invoice accuracy.
- Standalone read-only Python research; Windows WPF Child integration, CPU/GPU fallback acceptance, regression on unseen invoices, release packaging, rollback, and AAH/Tally protections are still unverified.
- Historic GitHub-hosted CI jobs failed before receiving runner steps. **Windows/Linux GitHub CI has not been confirmed**. Do not merge or release Setup.exe/Update.exe.

## Independent CI (synthetic only)
`python -m unittest discover -s experiments -p 'test_r223_source_table_rows.py' -v`

The 15 photographs, source OCR report, and local real-photo replay are deliberately excluded from the GitHub repository. Checkpoint is **research-only** and not release-approved.
