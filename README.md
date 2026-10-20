# InvoiceVision Child — private Windows build and OCR research

**Build status:** CI infrastructure is configured. **No production installer has been released yet.**

- [Windows Setup / Update build workflow](.github/workflows/windows-installers.yml)
- [OCR benchmark workflow](.github/workflows/ocr-benchmark.yml)
- [Source import instructions](source/README.md)

## Initial source import required

The pinned verified baseline source ZIP must be uploaded once to the
[private source folder](source/). It is not currently in the repository.
The build workflow checks its exact SHA-256 before extracting it.
No substitute executables or unverified source packages are accepted.

The Windows workflow runs .NET 10 self-contained compilation and WPF startup
checks, then uses Inno Setup to create real `InvoiceVisionChild_Setup.exe` and
`InvoiceVisionChild_Update.exe` files. Both files are withheld on failed gates.

The current OCR workflow performs **real inference on generated synthetic
invoice layouts**. That does not prove accuracy on customer invoices.
Experimental format recognition remains separate until source-backed,
visually checked zone accuracy passes on unfamiliar invoices.

**Protected:** AAH Desktop, Tally, Bank Statement OCR, Android source and
existing accounting data are not installation targets. The initial
standalone installer is not an untested in-place replacement for older
AAH-managed InvoiceVision Child installations.
