# R242 — Bundled CPU OCR, protected-state rollback rehearsal and installer refusal gates

**Verified 2026-10-26. Research-only — production installers remain blocked.**

## Passing evidence (actual Windows CI)

- [Run 40353618445](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40353618445) built the real self-contained .NET 10 WPF Child after source hash validation and staged the Python 3.11/OpenCV/NumPy/Tesseract/English OCR runtime into its own published application folder.
- The **relocated published** OCR runtime successfully performed actual invoice `analyze` followed by approved-region `ocr`, both on a deliberately synthetic noncustomer invoice. The report explicitly says `offline_python_runtime_bundled=true`, `ocr_runtime_execution_kind=relocated_published_application_runtime`, and `customer_invoices_tested=0`.
- `BUILD_VERIFICATION.json` confirms `offline_runtime_bundled=true`, `child_startup_smoke_pass=true`, original 73 source SHA checks, and `private_invoice_corpus_included=false`. It explicitly reports `field_accuracy_certified=false`.
- An isolated update/rollback simulation used actual **published executable and engine files**, deliberately corrupted an installed sandbox engine module, detected the corruption, restored the original hash, and verified four sample LocalAppData files and one installation-local custom user file were byte-identical throughout. This is **not** a genuine Inno Setup or user-machine migration test.
- [Run 40353744122](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40353744122) passed true WPF build/startup and **eight** installer-rejection regressions, including fabricated full-corpus acceptance with build-level OCR accuracy still unverified, and missing bundled offline OCR dependencies. It did **not** produce Setup.exe/Update.exe.
- Only checksums and synthetic verification JSON were published as CI artifacts, not customer photos, sensitive QR data, executables, or an installable runtime.

## Scope and unresolved blockers

The user elected to **exclude the blurred Metro invoice identifier** from source-level acceptance; it remains null, never guessed or posted. This exception does not automatically certify every other image field or item-row association.

**Production blockers still open:**
1. Fresh **original-invoice** OCR comparison for all printable characters, 55 readable selected fields, and required 51-case/held-out acceptance (the successfully recognized R240/R241 invoice was synthetic).
2. PaddleOCR model bundle and CPU/GPU fallback acceptance when required for parity with the existing Child; R241 only proves an offline CPU/Tesseract path.
3. Actual setup/update/uninstall/data migration and rollback on representative Windows installations. R242 is a file-level isolated simulation, not a full installer test.
4. The repository is still public, despite historical source archives that include original customer invoice photographs. Removing the benchmark from published executables does not revoke public Git-history access. A repository administrator must handle visibility and history/fork assessment.

**No production installer, auto-update, accounting export, or modification of existing user data was made.**
