# R239 — user-excluded blurred identifier; other original-source data reviewed (UNRELEASED)

**Date:** 2026-10-26. **Scope:** User requested that the blurred Metro invoice identifier stop blocking work on all other fields. The blurred source value is explicitly **excluded** from the private reference extraction. No invalid guessed identifier is substituted, certified or posted.

## Source evidence and checks

- Private original-photo audit: 3/3 exact JPEG hashes matched; 432 preserved saved actual Child OCR observations; 56 selected printed-field comparisons available.
- Private reference extraction: **55 selected fields presented**, while **one unreadable Metro invoice-number field is null/excluded**. Presentation is *not* automatic OCR certification or a posting authorization.
- Sri Rama: source-printed quantity `20` corroborated by tight-orientation second-engine local OCR; original Child OCR `2` kept as prior evidence. Printed rate/item/subtotal discrepancy remains separately represented.
- Nandi: two source-literal HSN/row-number splits and joined decimal tax amounts preserved; distinct bill date vs e-invoice date unchanged. New generic GSTIN checksum validator distinguishes source readings `29AAQFM2308H1Z3` (valid mod-36 check digit) from erroneous `29AAOFM2308H1Z3` (invalid). This does **not** grant supplier/master identity or accounting approval.
- Metro: supplier and printed product/tax values remain reviewable, but blurred invoice identifier is explicitly omitted. This does not make an otherwise incomplete invoice postable.

## Actual Windows Child regression verification

- Windows [run 40345980833](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40345980833): genuine .NET 10 WPF Child compiled and passed startup self-test.
- R239 source GSTIN module staged into actual Child Engine and surfaced in native WPF review panel; source hashes and published engine copies verified.
- R239 GSTIN synthetic tests, existing OCR/zones/field safety suites and six release-gate rejection checks passed.
- No private customer photographs were included in the compiled Windows output.

## Non-bypassable pending release checks

**Setup.exe/Update.exe are not approved.** The build and source-photo checks do not provide independent all-field/row OCR proof for 51 cases; real bundled *offline* Paddle/Tesseract Python runtime, installed-Windows end-to-end OCR, protected migration, backup/rollback and existing-data preservation are not accepted. The public source repository still contains historical invoice-photo evidence; GitHub owner/administrator visibility/history remediation is pending.

No existing installed AAH/Child data was altered; posting permission remains `false` for all reviewed fields.

The original customer images and detailed private reference extraction are kept **out of the public repository**. User-only evidence bundle SHA-256: `d42e88f94883b85433c269f76e79846889751c6656c76fe404a4ecbc5ea2eed8`.
