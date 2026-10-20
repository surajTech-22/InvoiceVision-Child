# R135 internal research checkpoint — not a release

Date: 2026-10-20. Original Child installation and AAH data unchanged. Parent source ZIP SHA-256: `ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59`.

## Source integrity
- 51 unique images rechecked by source SHA-256: 36 synthetic and 15 real.
- 68 unresolved OCR line associations inherited from R134. Zero newly accepted.
- Correct Nandi 2ed... invoice bill date reference: 04/09/2026 (user confirmed).
- 52-slot submission reconciliation and source-backed manual geometry acceptance remain pending.
- No production posting, Child integration, installation, or rollback approved.

## Reproduction and new findings
- Existing R134 page-local fallback still detects candidates in all 12 photo transformations, but candidate *presence* is not geometry correctness.
- For 1000258309.jpg, source candidate [29,794,855,869]; polygon IoU vs rotations ±4°: 0.99875 / 0.99874 using preserved four-corner coordinates.
- For 1000258311.jpg, source candidate [172,637,700,903]; polygon IoU: 0.96187 / 0.57304 (unstable at +4°). Bounding-box IoU is misleading after rotation.
- Three-view CPU OCR of 1000258311 identifies item and tax text, but no safe horizontal cut: text straddles the proposed y=708 boundary. Retain item and tax **semantic evidence groups** inside the parent; do not emit physical child boxes or a synthetic printed line.
- 1000258309 has no repeated tax anchor inside the provisional item-only region; avoid forced split.
- Multi-angle 5-view candidate consistency checked on 12 transformations: mixed results, not certified.

## Blocking gates (all mandatory)
1. Independently verify source-visible printed boxes, rows/columns, header/value grouping, and non-overlap for every case.
2. Resolve 68 text associations and preserve evidence on conflicting OCR across filters.
3. Separate item, tax-summary, round-off and total zones; avoid table wrappers extending into other groups.
4. Reconcile exact 52-slot list / 51 unique source bytes and any duplicates.
5. Run end-to-end Child GUI, CPU-only OCR runtime, Windows Setup/Update, backup/rollback and old AAH-managed migration safety tests.
6. Hold release until all tests and source-backed visual checks pass.

This branch is a research-only continuation reference, not an installer or permission to auto-post. Preserve raw source image bytes and independent uncertainty records. The full local R135 checkpoint contains the scripts, results and two annotated comparisons.
