# R236–R237 — exact-source OCR field recovery verified, unreleased

Date: 2026-10-26.

## Engineering changes
- Added **bounded, orientation-aware local source-cell rereads** of numeric values near genuine quantity headers. The original decoded photo and raw Child OCR remain unchanged. Local second-engine evidence is opt-in and only used for review: multiple passes from one OCR engine do not certify a financial field.
- Integrated it into the existing Child `Analyze` review metadata and native WPF warning panel. An unavailable offline backend produces a safe `LOCAL_SECONDARY_OCR_NOT_INSTALLED` status and never rewrites fields.
- Fixed a false-positive quantity-header association: a tall sideways quantity header must not claim later MRP, rate or amount columns. Verified against original source-coordinate snapshots and synthetic layout tests.
- Added a **generic, source-linked field-association review** that proposes (1) an 8-digit HSN with an attached row-number OCR prefix, (2) two literal decimal monetary strings joined into one OCR token, and (3) nearby branded company-title OCR fragments, while retaining each source token, substring and rectangle. No vendor, customer, source filename or amount is hardcoded in the public research module.
- Rejected city/postcode-shaped OCR text as an invented supplier-brand prefix, found when privately replaying the original sources.
- The native WPF review panel displays these provisional split-field suggestions, rejects unsafe input, and clears the prior invoice's suggestions. None of these fields can be auto-approved or posted to AAH/Tally.

## Windows and original-source verification
- Exact final Windows workflow: [run 40337378427](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40337378427), **success**, SHA `5707cb23d8553eabfd3e6769de7c22e3b776525e`. Genuine .NET 10 Child compile/startup, 73 sealed source checks, published engine SHA checks, Windows WPF panel startup, regression suites and six installer-blocking safeguards all passed. Compiled Child excludes benchmark customer photographs.
- Recovered the actual Python Engine sources from that Windows build, then replayed them *privately* against exact bytes of three original invoices and 432 saved actual Child OCR tokens; all original photo SHA-256 identities matched.
- In source-linked review, the one erroneous small quantity is re-read from the actual printed-cell crop as `20` (the saved Child recognized `2`), with corroborating local OCR passes. Two mis-glued HSN candidates and a joined two-decimal tax field are separated as provisional observations. An incorrectly fragmented supplier title is proposed from exact original OCR substrings, without inventing letters. The rejected city/postcode false-supplier prefix does not reappear.
- One blurry source invoice number remains **unverified**; a focused OCR reread returns conflicting characters. Do not fabricate it.
- Exact private source photographs and field-level truth are kept in a **separate user-only evidence package**, not committed to this public repository.

## Production blockers
**NO FINAL INSTALLER IS APPROVED.** This validates the research review engine and a limited original-photo source replay, not the complete offline packaged OCR model or error-free end-to-end invoice field extraction. Independently verified all-field accuracy, an offline OCR runtime on clean Windows systems, installer migration, updates, backups and rollback are still outstanding. The repository itself is also still public and contains a historical source archive with real invoice examples. Removing examples from published executables does **not** remove historical public exposure; GitHub visibility and history/fork assessment still require an owner/admin action.

Automatic accounting posting: **DISABLED**. User accounting data: **UNCHANGED**.
