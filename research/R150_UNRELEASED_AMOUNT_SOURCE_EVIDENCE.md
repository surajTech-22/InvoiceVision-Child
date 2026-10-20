# R150 — unreleased amount-source normalization checkpoint

Date: 2026-10-20. Research-only, **not installer approval**.

Actual R149 independent RapidOCR + staged Child PaddleOCR review ran across 15 original source photos, with original file hash and source coordinate evidence. Its 67 reference slots contain:
- 34 with no field candidate;
- 18 with wrong field candidates only;
- 14 with one or more reference-matching candidates (source text evidence, not verified accuracy);
- 1 with a match and alternatives.
Of the reference matches, 12 have text from both engines; neither engine agreement nor reference match confirms printed-value accuracy.

Detailed examination identifies 1000258309.jpg, grand_total expected 5181.00: both model OCR outputs include the exact token `:5181.00`, but the old strict amount syntax treats the leading label colon as numeric failure. R150 adds a **review-only** parser that retains `:5181.00` unchanged and permits a candidate decimal of 5181.00. The underlying image still needs source-pixel and field-label verification; no posting is authorized.

By contrast:
- 1000257923.jpg: 24254.85 vs 24255.00 is **not an exact match**, regardless of plausible rounding.
- Nandi 2ed12198...: 8840.47 vs 8840.00 is **not** silently corrected.
- Invoice totals must not be inferred from bare digits or tax components.

The R150 amount-parser regression tests passed on **Windows and Linux**, CI run 39461804640. Only a standalone research utility was added; actual Child app pipeline is unchanged.

Previous required blockers remain: nine real images with unknown-only zones; unresolved raw OCR associations, item/tax/totals cell ownership, printed physical boxes/cells across 51 unique/52 logical slots, unknown formats, actual UI integration, CPU/GPU and offline packaging verification, Windows Setup/Update rollback and account-data preservation. No 100% verification; no Setup.exe or Update.exe.
