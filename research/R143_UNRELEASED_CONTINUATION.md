# R143 continuation — not a release

Date: 2026-10-20. Repository baseline: research/invoicevision-r135-unreleased,
commit 752115585e14cd328a994b81ac65ed08449695fd. R142 was described as a
local checkpoint in the prior handoff; its actual files were not recovered in
this session. This change does not claim to reproduce those unseen changes.

## Implemented and tested

- Keep Ship To / delivery-party candidates separate from billed buyer.
- Reject administrative customer labels, a label-only Buyer (Bill to),
  CN Date as invoice date, and date/time strings as invoice numbers.
- Validate calendar dates and link field candidates to original SHA-256,
  raw OCR tokens, source regions and original polygons. Invalid or missing
  coordinates remain visible as issues and cannot create linked candidates.
- Reversible quarter-turn reading hypotheses recover spatial associations
  in sideways photographs. No hypothesis is an approved orientation, and
  wrong-direction hypotheses can still produce false candidates.
- Recursive semantic subdivisions preserve all source token identities,
  stay inside parents, protect label/value group membership, reject
  unknown-role subdivision, and never imply printed physical borders.
- Injected runtime lifecycle caches the backend, falls back once from GPU
  initialization/inference/schema failure to CPU, and surfaces CPU failure.
  These are contract tests, not proof of real GPU or model operation.
- 55 local regression tests pass, including 300 deterministic randomized
  recursive coverage/non-overlap cases.
- Replayed existing independent R136 CPU OCR reports for all 15 recovered
  original photographs. Verified both reports against each original SHA-256
  and dimensions, retained raw text, and generated 15 three-pane source
  comparisons. No new OCR model inference was performed in this session.

## Visual findings and outstanding blockers

Sri Rama's rotated photograph visibly contains A001168, 17/09/2026,
and grand total 1140.00. The 90-degree reading hypothesis recovers
the 1140.00 candidate in both existing OCR outputs. This does not certify
other values, orientations, boxes or invoices.

The Metro comparison exposed customer administrative labels being treated
as buyer values and CN Date being treated as invoice date; regression tests
cover these errors now. Remaining unverified orientation hypotheses can
still associate tax/savings amounts with total labels. No automatic winner
is chosen and no value is eligible for accounting posting.

The Library source-download helper failed with HTTP 403 while listing its
hosted tools; therefore the complete source archive and all 51 unique
test inputs were not materialized in this session. GitHub text access works,
but its fetch tools cannot transfer the binary source ZIP. The existing
15-photo OCR artifacts were recoverable through GitHub artifact downloads.

Physical printed boxes, source-supported repairs, complete recursive
semantic correctness, all reference fields, actual CPU/GPU model fallback,
Windows WPF Child integration, offline runtime packaging, installer/update
data preservation and rollback remain unverified. Source comparisons are
review evidence, not physical-box certification. Existing application and
accounting data were not modified. Setup.exe and Update.exe remain withheld.
