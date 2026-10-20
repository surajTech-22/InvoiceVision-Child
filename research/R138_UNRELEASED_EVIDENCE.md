# R138 research continuation — UNRELEASED (2026-10-20)

Branch: `research/invoicevision-r138-unreleased`. Parent: R135 research branch. No production AAH, Tally, Child, Android or Windows install changes.

## CPU model comparison, 15 original photographs
Both independently installed CPU engines completed 15/15 inference without source modifications. These are recognition outputs, **not** field accuracy or zone geometry certifications.

- RapidOCR: 15/15 CPU inference completed.
- PaddleOCR PP-OCRv5 mobile: 15/15 CPU inference completed.
- Independently verified byte-identical source SHA-256 for each pair of model inputs.
- Polygon-overlap matched OCR lines: 2,331.
- Text agreement: 1,678; punctuation/spacing differences: 200; text conflicts: 453.
- Unmatched RapidOCR lines: 121; unmatched PaddleOCR lines: 161.
- Numerically conflicting matched lines: 195.
- High-risk concrete disagreements: Bairava tax `152.04` vs `162.04`, item amount `67.80` vs `67.00`; Veerabhadreswara `418.15` vs `418.16`, `2986.81` vs `2986.01`.
- Two engines sometimes agree on the **same incorrect spelling**; agreement is not source transcription truth.

Method: compare native-source four-corner OCR polygons, use convex polygon IoU >= 0.36 and one-to-one greedy association, then compare NFKC/casefolded text while preserving punctuation and digit differences. All matched and unmatched tokens remain review-only; no automatic correction or accounting posting. The local reproducible analysis script is `r138_dual_engine_consensus.py`, with JSON and 15 annotated source-image comparisons.

## Source manifest reconciliation
R14 benchmark scope: 3 original photos + 13 Library photo slots + 36 synthetic pages = 52 slots. Present archives contain 15 unique real photo files + 36 synthetic pages = 51 unique hashes. The missing 52nd source byte copy is the historical Library-page-13 duplicate of original Metro; the 52-slot manifest records it as an **alias without separately available bytes**, not as a newly verified second copy. All 51 available distinct source bytes reverified against the source archives. Do not claim current 52/52 byte verification.

## Generic CPU orientation improvement
Earlier Tesseract OSD yielded unreliable or missing orientation for many originals. A new research-only confidence-weighted 4-rotation OCR scorer uses no supplier names, no filename heuristics and no source-hash rotation overrides. On 15/15 real photographs, it returned provisional right-angle hypotheses; 3 original photos matched independently established orientations. Nine additional rotated versions of those 3 photos passed the rotation-equivariance check. This is not page-geometry acceptance. The research implementation is `r137_adaptive_orientation.py` plus isolated subprocess tests `r138_orientation_isolated.py` and `r138_rotation_equivariance.py` in the local checkpoint.

## Mandatory release gates still failing
- 68 prior unresolved OCR line associations have not been certified; R138 conflicts add independent uncertainty, not approved corrections.
- Table physical borders, row/column identities, header/value pairing and source-backed leaf-zone non-overlap have not been exhaustively verified.
- Source-visible text and tax, round-off, grand-total relationships remain unresolved on some real photographs.
- Actual native Windows Child GUI, .NET publish, Setup/Update installer, data preservation and rollback not tested.
- The duplicate Library source copy is not independently present to rehash.
- No automatic posting, no installer, no production merge authorized.

## Next research
Add line-level numeric conflict quarantine and evidence-only semantic child grouping. Compare model results on orientation-corrected sources, but retain original four-corner coordinate transforms and reject unsupported printed lines. Run full synthetic and real visual regression with explicit independent acceptance, then Windows native application and installation tests.
