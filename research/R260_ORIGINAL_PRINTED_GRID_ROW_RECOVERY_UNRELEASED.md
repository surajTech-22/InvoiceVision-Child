# InvoiceVision R259–R260: source-printed physical row-band recovery — UNRELEASED

**October 27, 2026 | Research-only draft.** Never treat physical row boundaries as accepted accounting rows, source text corrections, or model accuracy certification.

## Code integrated in actual staged Windows Child

- New `integration/Engine/INVOICE_OCR_RULED_ROW_BANDS_R259.py`: verifies a real printed Product/Pcs-or-Qty/Taxable-or-Amount header and a physically later printed Total. Detects repeated long horizontal ruling fragments from **unmodified original source pixels**, including separate left/right y witnesses and row-pitch alignment. Makes bounded **skew-aware source quadrilaterals** for description regions; the first top boundary and missing rulings are explicitly inferred, not fabricated as observations.
- The Child's real `INVOICE_OCR_GRID_TABLE_R246.py` now invokes this new module in the **separate read-only grid-review evidence** path. `source_printed_row_band_count_r259` is **not** added to accepted item rows or posted quantities/amounts. Any module failure returns an unavailable review status with zero certified items.
- R259 optional source-pixel 4x rectified PSM7 rereads keep the tentative exact OCR words separately, never writing back to the source first pass.
- R260: If a row-crop PSM7 returns **no words**, one bounded 3x **original pixel** context-crop PSM6 reread is saved as a second source alternative, explicitly marked `may_contain_adjacent_source_ink=true`. All text remains unverified, and malformed/unbounded TSV fails closed.
- Genuine WPF Child staging now installs the R259 module into an isolated Windows publish tree with SHA comparison. Original baseline archive integrity remains verified. No installed customer app or accounting data is changed.

## Windows test status

- [Genuine .NET 10 WPF Child compile/startup, R259/R260 safety regressions, source module publish hashes and blocked installer checks](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40475456505): **successful**.
- Six R259 synthetic geometry/negative tests plus two R260 fallback/source safety tests passed in the same workflow. This synthetic unit suite is **not** full original invoice character accuracy.

## Private original-photo replay

Three source photographs were independently loaded from the user's private R153 archive. Exact original JPEG SHA-256 identities checked, and source decoded pixel hashes remained unchanged. Fresh local offline Tesseract v5.5.0 on the exact R260 Engine files produced:

| Private source case | Prior R258 provisional numeric/fragment rows | R260 physically detected ruled bands | Bands with at least one unverified description text alternative | Verified item rows |
|---|---:|---:|---:|---:|
| One-row source A | 1 | 0 (no qualifying repeated grid) | 0 | 0 |
| Seven-row source B | 1 | **7** | **7** | 0 |
| One-row source C | 1 | 0 (no qualifying repeated grid) | 0 | 0 |

These are distinct evidence types. Seven printed source bands do **not** establish seven complete product rows: text contains OCR character mistakes, and HSN/quantity/amount columns were **not** independently validated. The unreadable identifier on source C stays excluded. This original-photo replay was performed locally in a private user-only workspace, **not** on a real installed Windows accounting workstation. Customer photos and raw OCR values are intentionally excluded from this public GitHub note and commits. The user-only evidence archive is `InvoiceVision_R260_Private_Original_Row_Verification_UNRELEASED.zip` with SHA-256 `d0d35f711d47ef7de5c644dcd3121bd437481f8d01b947a8d9b8e1c77c1586a6`.

## Release blockers

- Fully verified every-character invoice OCR, seven complete source-value row mappings, field/tax accuracy and acceptance still **not met**.
- The current offline packaged CPU model is Tesseract only; optional Paddle/model parity and real user-installed Windows update, protected data migration and rollback are still unaccepted.
- Pre-existing historically committed customer images remain exposed in the public repository source archive; repository administrator-level remediation remains mandatory before production publication.
- Keep PR **draft**. Do not merge, ship Setup.exe or Update.exe, silently change source OCR, or post to AAH/Tally.
