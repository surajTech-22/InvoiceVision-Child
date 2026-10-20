# R146 continuation — unreleased

Actual Child adapter now rejects mismatched text/score/recognized-position arrays,
invalid confidence, nonfinite/out-of-source/degenerate geometry, missing result
pages and multiple results for a single input tile. Detection-only polygons are
not used as recognition positions. Polygon and raw text evidence is retained at
the adapter boundary; the legacy TSV still contains enclosing integer rectangles.
Fractional polygons use floor/ceil enclosure instead of rounding into the text.

A real Paddle 3.2.2 / PaddleOCR 3.7.0 runtime test exposed silent CPU substitution
when gpu:0 was requested. The adapter now checks CUDA availability before model
initialization and reports the explicit CPU fallback. This does not certify real
GPU hardware. The interrupted pre-fix corpus is superseded, not counted as GPU
verification.

Recursive zoning protects observed multi-column item tables and neighboring
standalone label/value groups. Raw text hypotheses remain intact; table context
prevents product description words from becoming independent party sections.
Candidate cuts use actual text-free projection gaps instead of anchor midpoints
that may land on intervening unknown text. Logical groups are not physical boxes.

77 regressions and original recursive/metadata checks passed locally before the
final gap-selection adjustment; targeted tests passed after it. Full retest and
actual 51-source Paddle corpus and Windows CI are in progress. No accuracy or
release certification is implied. Existing app and accounting data are untouched.
