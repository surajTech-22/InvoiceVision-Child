# R148 — source-backed joined date/time OCR recovery (UNRELEASED)

Date: 2026-10-20. Research branch only; Child, AAH, Tally and accounting data unchanged.

The R147 Windows actual staged Child CPU corpus (run 39455484213) completed **51/51 unverified OCR inference** cases with **51 UTF-8 TSV files, 51 source/model/zone comparison images and one UTF-8 JSON report**. No original photo pixels changed and no emitted split cropped recognized text. **Nine original photographs remain unknown-only logical zones**. Zero source-visible physical box/cell layouts certified; zero accounting fields approved; real GPU execution and Windows installer/rollback not verified.

R147 corpus artifact ZIP SHA256: `b48e481fa01551fb608945fada39243ca777a27a93962deb7de7c9af127700df`.
Source archive SHA256: `ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59`.

## Concrete new R148 evidence
An actual 1000258308.jpg PaddleOCR output includes the exact raw token:
`03/09/202602:08PM`
next to source OCR label `Date`. Existing date matching missed this token because the year digits touch the 12-hour clock. The new R148 strict numeric date-time parser can propose the source-exact calendar substring `03/09/2026` only when the joined clock suffix `02:08PM` is valid. The complete original OCR token, coordinates and token references are retained; this does **not** verify the date against source pixels or give it posting authority. Invalid dates, impossible times, related invoice-number confusion and absent timestamps are rejected.

R148 passed source-backed unit tests and existing R138/R141 field-control suites on Ubuntu and Windows in run **39459396291**. Safely merged via research-only PR #2, commit `83abb65b1888fa748d652d32e8ed44cbee1fa7d6`; **not merged into main**.

The latest R144 staged Child 51-source Windows CI run **39458335303** was still running when this note was written. No claim of 100% acceptance.

## Mandatory blockers
- Physically prove all printed table borders, cells, item/tax/totals separation and recursive coherent zones on all originals; nine real pages are still unknown-only.
- Resolve remaining OCR text associations and field accuracy, not merely output-serialization success; source-backed evidence required.
- Reconcile the 52 logical slots vs 51 unique source images, verify unseen formats.
- Real CPU offline installation, optional GPU, Child UI navigation, AAH fallback, posting protections, installer/update and rollback tests.
- Keep Setup.exe and Update.exe withheld until all source-backed accuracy, geometry and user workflow gates actually pass.

No invented dates, no auto-posted values, no production release.
