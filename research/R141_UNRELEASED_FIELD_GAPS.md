# R141 research continuation — still withheld (2026-10-20)

This is **not an approved Child release**. No changes to main, AAH, Tally, installed Child, or user accounting data.

## Verified CI and source evidence
- R136 independent CPU RapidOCR and PaddleOCR processes both completed on the same 15 original photos, with SHA-256 matching source bytes.
- R135 cross-platform physical-split safety invariants passed, but do not certify printed boxes.
- R138 cross-platform OCR field/consensus safety checks passed; 88 field hypotheses: 50 cross-engine text support, 36 conflicts, 2 independent rechecks. No field was approved for posting.
- R140 pure safety CI passed on Windows and Linux. Offline same-15-photo review using axis envelopes yielded 194 numeric-string mismatches (the earlier polygon-based audit yielded 195; different matching geometry, NOT evidence one was corrected): 117 mixed-text/identifier, 30 partial-numeric, 24 bare-numeric/unclassified, 23 decimal-or-currency-shaped. All require manual confirmation before accounting use. The numeric-shape class is not proof a number is a total.
- R141 same-line parser tests added to both operating systems. The prior evaluator recognized 16 exact manual reference **candidate values** among 67 reference fields across 15 photographs. Read-only inline recovery found 3 additional candidates (Sri Rama invoice number A001168, Amazon INR 13365, Amazon INR 7501), raising candidate-value presence to 19/67. Neither score measures source-pixel transcription accuracy, semantic role precision, or actual invoice posting correctness.
- Original Nandi E55409 bill date reference is 04/09/2026, as confirmed by user. Do not overwrite the printed value with any 2025 OCR reading.

## Current limitations
1. 48/67 original reference-value slots still lack a matching candidate from these narrow parsers; others may be in unmatched raw OCR fragments.
2. 68 previously unresolved source-text associations have not been demonstrated fully resolved.
3. Physical printed borders/cells, row/column structure, recursive header/value grouping, and separation of item/tax/totals require source-backed human visual verification.
4. Need entire 51 unique source files / 52 logical slots and held-out unseen layouts.
5. Verify exact Windows Child integration (WPF), CPU models packaged offline with optional GPU, AAH fallback behavior, installer/update, data preservation, and rollback.
6. Do not promote any tool merely because its tests pass, and never invent recognized text.

## Next implementation work
- Reconcile new inline fields with R138 source coordinates; preserve tokens and competing model text, never set posting_eligible.
- Triage 23 decimal-shaped disagreements using nearby source-visible labels, not number shape or assumed accounting meaning.
- Improve supplier/buyer grouping for invoices without explicit inline labels using relative physical zones and source text; avoid vendor-specific heuristics.
- Compare all proposed zones against originals and reject any guessed or crossing borders.
- Save visual overlays for each material change. Only a fully verified Child installer warrants user notification.
