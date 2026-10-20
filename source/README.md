# InvoiceVision Child — verified Windows build source

This is the private, **standalone** repository for Invoice OCR Child. It is not
DeskSpace or AAH Desktop, and must not modify the protected Tally or Bank OCR
components.

## One-time source import (needed before the first Windows installers)

1. Download the exact file **INVOICE_OCR_CHILD_R113_R4_R2_VERIFIED_UPDATE.zip**
   from the previously supplied ChatGPT artifact.
2. In this repository, open the `source` folder, choose **Add file → Upload files**,
   and upload the ZIP **without unzipping or renaming it**.
3. Commit to `main`. The Windows installer workflow starts automatically.
4. Open the **Actions → InvoiceVision Child Windows installers** run.
5. An **InvoiceVisionChild-Windows-Installers** artifact appears only after all gates pass.

Pinned ZIP SHA-256:
`ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59`

If this exact archive is absent or mismatched, the workflow fails and does
**not** generate a pretend installer.

## CI workflows

- `.github/workflows/windows-installers.yml` — Windows .NET 10 self-contained
  publish, 73-file source SHA-256 verification, engine readback,
  real WPF startup smoke, Inno Setup `Setup.exe` and `Update.exe`,
  SHA-256 hashes and build reports.
- `.github/workflows/ocr-benchmark.yml` — independent CPU OCR inference in
  disposable GitHub runners; baseline uses synthetic invoices only.
  This is not yet a production field-accuracy benchmark.

## Important distinctions

- `InvoiceVisionChild_Setup.exe` is for a **new standalone installation** under
  the user's local Programs directory.
- `InvoiceVisionChild_Update.exe` requires an **existing standalone**
  installation made with the same Inno AppId. It will refuse to guess the
  location of an older AAH-managed Child. No untested legacy migration.
- Both executables bundle the .NET runtime; the user does not need a .NET SDK.
- The OCR Python runtimes/model weights are **not currently bundled into those
  installers**. The standalone app may require an independently provisioned
  OCR environment until a verified model-runtime distribution is available.
- Correct invoice fields/zones are NOT certified merely by successful OCR,
  compilation, or installer creation. Do not enable automatic AAH posting.
- Do not upload customer invoices to a public repo or third-party cloud OCR.

## Release policy

The first build is a **build-validation candidate**, not an approved
production release. Check installation, preservation of user data and real
invoice recognition before distributing either executable.
