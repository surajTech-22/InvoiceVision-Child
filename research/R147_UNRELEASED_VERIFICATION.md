# R147 unreleased — actual Child CPU corpus and multilingual evidence

Date: 2026-10-20. Research-only. **NOT** an installer or accounting-accuracy certificate.

## Source and reproducible evidence
- Pinned original source archive SHA-256: `ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59`.
- The **actual staged Windows Child adapter** ran PP-OCRv5 mobile via PaddleOCR 3.7.0 / PaddlePaddle 3.2.2 / PaddleX 3.7.2 on **51/51** unique source images: 36 synthetic, 15 real.
- Verified output artifact from Windows run **39455484213**, artifact name `InvoiceVision-R146-Windows-Actual-Child-OCR-Unverified`; downloaded artifact ZIP SHA-256: `b48e481fa01551fb608945fada39243ca777a27a93962deb7de7c9af127700df`.
- Archive integrity check passed. It contains 51 UTF-8 TSV files, 51 source-vs-Paddle-vs-logical-zone comparison images, and a UTF-8 JSON report. **Exactly 51/51** case statuses are `COMPLETED_UNVERIFIED`; 0 failures.
- All 51 cases explicitly preserved original source pixels; 0 OCR text lines cropped by emitted logical-zone cuts. **Nine real** source images produced ONLY an `unknown` logical zone (source-vs-logic mismatch persists). Full printed cells/box geometry, field association, and mapping NOT verified.
- Across 190 source tiles, all 190 completed on CPU. A `gpu:0` attempt was explicitly rejected as CUDA unavailable, then CPU used. **No actual CUDA GPU hardware was tested**.
- 6 Paddle model hash files captured in the original report. All 51 source-image SHA-256 values are retained.
- Earlier Windows run **39447768680** was red: 42 successes / 9 `UnicodeEncodeError` failures, caused by Windows default cp1252 writing CJK/Greek OCR strings. The R147 strict UTF-8 patch corrected the export problem; it does not verify all transcribed text.

## Implemented on research branch only
- Actual Child CPU corpus outputs: atomic strict UTF-8 TSV and JSON; never silently transliterate or drop the recognized characters.
- Strict UTF-8 file reads/outputs in other OCR research tools (R136, R143/144/145, R146 field evaluation and rezone); ambiguous legacy cp1252 files are rejected rather than silently converted.
- Source SHA and raw model outputs remain unchanged. Failed atomic writes cannot replace prior reports.
- R138 cross-engine candidate comparisons and R146 benchmark reference matching now retain Unicode letters/digits, rather than comparing Arabic/Chinese names by only surviving ASCII characters and causing false agreement.
- Verified R147 source-linked replay/field comparison, Unicode negative controls, R138 consensus and R143 continuation regression tests on **both Windows and Linux** (latest completed R147 CI **39457318939**).
- Changes consolidated via research-only PR #1 merge commit `1beba464bec1c5ca6781b93144c104c861eef39d` into `research/invoicevision-r143-unreleased`. Not merged into `main`; installed Child and AAH unaffected.

## Mandatory remaining release gates (DO NOT CLAIM SUCCESS)
1. Nine real photos with `unknown` zones require source-backed physical and recursive semantic analysis, without cutting unidentified text.
2. Reconcile all 68 previously unresolved OCR text associations, field labels, exact amounts, and cross-engine mismatches; do not confuse successful OCR execution with field accuracy.
3. Verify printed physical boxes and merged-cell/column relations on all 51 unique sources and reconcile 52 logical benchmark slots; test previously unseen invoice formats.
4. Exercise real GPU (optional), offline CPU installation/models, child UI navigation, AAH fallback, and no-accounting-posting rules.
5. Test Windows Setup/Update with existing workspace/accounting data, safe backups and rollback, and post-install original-invoice comparisons.
6. Latest R144 Windows full CI on the newly merged research branch must also pass; prior successful run predates the final research consolidation.

R147 is **not 100% accepted**. Neither Setup.exe nor Update.exe is authorized for release.
