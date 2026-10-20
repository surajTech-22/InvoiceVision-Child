# R145 continuation: release withheld

The R142 local checkpoint itself was not recovered. Work continued from the
latest recoverable development commit 752115585e14cd328a994b81ac65ed08449695fd
on research/invoicevision-r143-unreleased. Main and installed applications are
unchanged. No accounting data was opened, migrated, or edited.

## Source and corpus

Recovered the original source archive through a checksum-verified private
GitHub artifact. Archive SHA-256:
ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59.
All 73 baseline source-file SHA-256 checks passed. Found and hashed 51 unique
inputs: 36 synthetic fixtures and 15 real source photographs. Reconciliation
to the historical 52 logical submission slots is still not complete.

## Work verified in this session

- Fresh RapidOCR CPU inference completed on all 51 inputs. Package versions:
  RapidOCR 3.10.0, ONNX Runtime 1.31.0, OpenCV headless 4.11.0.86. The installed
  default model files are PP-OCRv6 small; this is not the PaddleOCR v5 adapter.
  Completion and recognized-line counts do not measure field accuracy.
- Replayed independent R136 RapidOCR/PaddleOCR reports on 15 original photos,
  checking original bytes and coordinate dimensions. Generated 15 three-pane
  field-proposal comparisons. No hypotheses were approved for posting.
- Re-ran OCR on both quarter turns of all three photos selected by vertical
  text geometry, retaining each direction and original-source polygons.
- Native geometry audited on all 51 inputs. Every displayed ruling pixel is
  a subset of the baseline native h13/v13 source masks; no joins were drawn.
  Generated 51 three-pane native comparisons and 51 source-mask images.
- Added enclosed-component detection without the old maximum width/height
  exclusion. Axis component candidates exist on 35/36 synthetic fixtures.
  Added rotation-tolerant enclosed source-ink contours with four-side support,
  without closing/dilation or drawing gaps: candidates exist on 36/36 fixtures,
  including global_poor_scan.png. Candidate presence is not visual certification.
- The exact native R56 golden-mask regression passed on all three originals.
  Baseline R104 source-pixel subset checks and recursive/metadata checks passed.
- Mapping rejects administrative customer lines, label-only parties, credit-note
  dates as invoice dates, and date/time values as invoice numbers; Ship To is
  separately represented as consignee. All linked proposals retain original
  SHA-256, OCR text, coordinates, competing evidence, and unverified state.
- Implemented reversible, source-bound magnification (1x/2x/4x/8x). A targeted
  Nandi date crop gives 04/09/2026 in enlarged colour and grayscale RapidOCR,
  while binary preprocessing retains a competing 2025 reading. Independent
  Tesseract colour/grayscale crop checks also read 2026. Preserve the conflict
  and the user's confirmed 2026 reference; do not silently rewrite raw OCR.

## Actual Child integration

Research overlays target the actual Paddle adapter and recursive-zone engine,
not installed files. Staging only permits repository integration-build, first
verifies all 73 original hashes, then records before/after hashes and updates
the isolated build manifest. The original archive remains immutable.

Paddle CPU remains the default. Opt-in auto/gpu tries gpu:0, falls back once
after initialization/inference/schema failure, discards partial generator
output, caches CPU, and surfaces CPU failure instead of returning empty success.
Mocked tests do not demonstrate real GPU hardware or real Paddle CPU inference.

The original recursive splitter checked only classified text when deciding
cuts. The overlay protects all intersecting source text, including unknown
lines, and rechecks the rounded cut coordinate. Original recursive/metadata
tests pass against the staged engine; targeted crossing-text regression passes.

Windows run 39438430410 passed on final two-overlay commit
5b497afc15457b38cfb90797fb76c76b3d24f42a: 66 regression tests, self-contained
.NET compilation, engine hash readback and real WPF startup smoke. Its Linux
job passed the same 66 regressions and 51-source native audit. No installer
was produced. Startup alone does not verify end-to-end invoice GUI use.

Replaying all 51 CPU OCR outputs through the staged Child recursive engine
produced 6 splits / 57 total leaves with zero source text lines cropped by
emitted splits. Most sources stayed unsplit; this is geometry safety only,
not evidence of complete semantic grouping or field mapping. Replay TSV
confidence was an explicit fixed inclusion flag, not a measured model score.

## Mandatory unresolved acceptance gates

1. Visually certify every physical box/line/cell against every original, including
   shadows, bending and broken borders; source-mask closure alone is insufficient.
2. Demonstrate coherent recursive grouping and exact field mapping/row associations
   on the complete corpus and held-out invoices. Many hypotheses remain ambiguous.
3. Reconcile the inherited 68 OCR associations and full reference-field failures;
   do not replace prior metrics with inference-completion counts.
4. Exercise actual Paddle CPU and GPU failure paths, offline bundled runtimes and
   model weights, end-to-end Windows Child invoice review, and AAH fallback.
5. Verify Windows installation/update, old AAH-managed Child migration behavior,
   existing-data preservation, backup and rollback in representative Windows setups.

100% acceptance is not met. Setup.exe and Update.exe remain withheld.
