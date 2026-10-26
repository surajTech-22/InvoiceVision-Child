# R238 — offline QR invoice identifier corroboration (UNRELEASED)

26 October 2026. R238 is an incremental research/runtime improvement, **not** an installable or production-accepted OCR update.

## Implemented and Windows-verified

- New `INVOICE_OCR_QR_REVIEW_R238.py` uses bounded **offline OpenCV QR detection** on original invoice pixels (whole source and upper-right), without contacting any barcode or cloud service and without modifying source pixels.
- Only a QR payload with an **explicit invoice-document key** in parsed JSON (`DocNo`, `InvoiceNo`, `InvoiceNumber`, `DocumentNumber`) can yield a review-only identifier candidate. A long number, an IRN, a GSTIN, or unsigned/unstructured text never becomes a verified invoice number.
- QR payload text is *not* surfaced, logged or saved; only its SHA-256 and a strictly checked candidate string are retained in Child review metadata. Failed decode, conflicting candidates, missing keys and missing dependencies fail closed. All QR outputs remain `posting_eligible=false`, `invoice_number_certified=false`.
- The QR evidence now appears in the existing native WPF Child source-review panel, with a synthetic startup test for display and clearing on the next document.
- Genuine Windows WPF build/startup, the original 73 source hashes, privacy checks, published engine module SHA readback, all existing regression tests, six new QR synthetic safety tests and the installer rejection safeguards **passed** in [Windows run 40340576783](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40340576783).

## Private original-source replay

The actual QR module from that exact successful GitHub Windows artifact was recovered and privately executed over three original JPEG sources with their original bytes unchanged.

- One original contained a readable QR payload **without an explicitly labelled invoice number**. The module correctly refused to invent one.
- Two originals' printed QR evidence could not be decoded at the available source resolution, including the invoice with the blurred identifier that motivated this check. That identifier **remains UNVERIFIED**.
- No original customer image or decoded QR payload was uploaded to GitHub for R238; source identities, detailed results and the exact module binary are retained in a private user evidence package.

## Release blockers

The historical repository still has a **public source archive with customer invoice photographs**; exclusion from the compiled application does not erase public history. Repository visibility/historical exposure must be handled by an owner with admin authority.

Fresh whole-document OCR using a packaged offline runtime, full every-field source accuracy (including unreadable identifiers), user-data preservation, safe installer/update/rollback, and posting protections remain to be accepted. **No Setup.exe/Update.exe is authorized and no AAH/Tally accounting data was changed.**
