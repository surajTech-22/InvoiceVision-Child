# R240–R241 — genuine Windows offline CPU OCR and relocated Child runtime (UNRELEASED)

26 October 2026. **Not a production acceptance certificate, and not a released installer.**

## R240: actual live OCR, not just synthetic zone-proposal tests

**Windows workflow [40350722054](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40350722054) succeeded.** It executed the exact staged Child category-first Python analyzer against a noncustomer synthetic invoice on Windows, using a locally installed Tesseract backend. It then passed the source hash-bound review JSON back to the **actual** Child `ocr` subcommand and successfully recognized the known invoice number, item description and total amount in reviewed regions. Neither original source image nor accounting data was changed.

A genuine live inference failure revealed a previous parser defect: R226 accepted word-only synthetic TSV but rejected Tesseract's page/block/paragraph/line TSV hierarchy. Fixed to ignore valid OCR structural rows (levels 1–4), preserve word source evidence (level 5), and fail closed on malformed geometry. Added a regression using true Tesseract-style hierarchy.

## R241: relocation-tested, self-contained CPU OCR dependencies

**Windows workflow [40351490342](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40351490342) succeeded.** It:

1. Verifies the sealed 73-source archive before any staging; no user customer images are committed to GitHub.
2. Builds an isolated runtime directory `Runtime/Python` with a fully copied Python 3.11, OpenCV 4.11 and NumPy 2.1.3, and `Runtime/Tesseract` with Tesseract and English traineddata.
3. Verifies the **relocated** Python executable imports the runtime libraries, and relocated Tesseract reads its training data.
4. Compiles and starts the real .NET 10 self-contained WPF Child with that runtime copied into its published application folder.
5. Executes real `analyze` and `ocr` on a synthetic printed invoice using the exact **published relocated** Python/Tesseract binaries. Both live stages pass, source hashes match, no text is approved for accounting.
6. Records SHA-256 checksums for the runtime executables and English OCR model in `R241_RUNTIME_VERIFICATION.json`, and `offline_runtime_bundled=true` in `BUILD_VERIFICATION.json`.
7. Publishes **only synthetic JSON verification and hashes** as GitHub Actions evidence, **not** a customer photograph, raw customer OCR, distributable application ZIP, or installer.

The actual native Child launch paths have been wired to find `Runtime/Python/python.exe` and set local Tesseract environment variables **only in the OCR subprocess**, without changing system PATH, existing AAH OCR environments, or client data. When a previously verified Paddle runtime is available, it may retain precedence; the copied CPU OCR runtime ensures an independent fallback.

## Explicitly unverified

- PaddleOCR's full offline model files are **not** bundled or tested as relocatable. This is a **CPU/Tesseract** offline OCR workflow.
- The tested Windows runner is not proof of successful installation, migration or rollback on the user's real systems.
- The 51-case OCR corpus and all 55 readable reference fields are not certified accurate under fresh bundled inference. One blurred Metro identifier is excluded from source-level acceptance at user request, without guessing its value.
- Update/rollback and existing user accounting/state preservation need dedicated integration tests.
- The public repository still has customer invoice images in historical source archives and requires repository-visibility/historical-exposure remediation by an authorized administrator.

**No production Setup.exe/Update.exe was created, and no AAH/Tally posting or installed user data was changed.**
