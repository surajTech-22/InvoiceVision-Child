# R227 — verified full original-photo replay against exact Windows-staged Child engine

**Date:** 2026-10-26  
**Status:** Source and review-preservation verification **passed**; character / field accuracy remains **unreleased and unverified**.

## What was verified (private local replay)

The private, user-owned R153 checkpoint ZIP was recovered directly from the user's file library. The saved Child R147 report contains **51 cases: 15 original photographs and 36 synthetic fixtures**. R227 used the same 15 original JPEG bytes, verified their exact SHA-256 hashes and decoded dimensions, and read the saved OCR observations.

The *actual* R226 Child review and recursive zone modules were recovered **byte-for-byte** from the successful Windows CI build #40309131418 (GitHub Actions). SHA-256 of recovered modules:

- `INVOICE_OCR_RECURSIVE_ZONES_R109.py`: `82135713d5c3fe363de65d6f47796f24265d7fa63931489ba92a7fa2eb9abaf0`
- `INVOICE_OCR_SOURCE_REVIEW_R226.py`: `2d78d5599ad32b446ee84dc95461f56b032b741bbe863087755d93b13306f7c5`
- `INVOICE_OCR_SOURCE_ROWS_R223.py`: `1f653e662f1700d5f85070c3d0d7afa6e30fa51f964675c90e6883fa3449b136`

The run executed **15 original-photo reviews**. For each photo, exact same source-coordinate TSV was passed to the staged recursive engine with `INVOICEVISION_SOURCE_REVIEW_R226` disabled and then enabled. Original photograph bytes, decoded pixels, OCR source lines and zone leaves remained unchanged.

| Source-evidence metric | Verified |
|---|---:|
| Exact original photo SHA checks | 15 / 15 |
| Original saved OCR text/boxes | 2,361 / 2,361 |
| Review-only item-row hypotheses | 26 across 9 photos |
| Original photos without proposed item rows | 6 |
| Suspicious date observations | 7 |
| Compare recursive leaves opt-in vs off | Identical across 15 |
| Original pixels modified | 0 |
| Approved/certified item values | 0 |
| Accounting writes | 0 |

**Important:** The saved R147 OCR report lacks original OCR confidence scores. TSV confidence is an explicit fixed inclusion placeholder of `99`; it must NEVER be used as model quality, OCR confidence, recognition completion, or field accuracy. This is **saved-Child-OCR replay**, not fresh inference.

## Reproduction without uploading private invoices

A portable helper script has been committed at `scripts/r227_replay_original_child_review.py`; it requires a local user-owned evidence checkpoint and exact staged Child Engine directory (for example, the trusted engine files in build run #40309131418 artifact):

```powershell
python scripts/r227_replay_original_child_review.py --checkpoint <LOCAL_R153_EVIDENCE_ZIP> --engine <STAGED_CHILD_ENGINE_FOLDER> --out <LOCAL_JSON_OUTPUT>
```

The result contains SHA hashes, counts, review status and safeguards, but no original OCR strings or photo bytes. The script is syntax-checked in Windows GitHub CI; the fully integrated replay was also performed locally on the retained originals with the exact CI modules. Private invoice images, text and contact information were NOT uploaded to GitHub.

Evidence: user-owned `InvoiceVision_R227_Verified_Windows_OriginalReplay.zip` (metadata and source hashes only), SHA-256: `af6ea89dfa623fee0303497b108a091ebd9966ed1f6e1875b4b0cdaeea787d76`.

## Remaining release blockers

- The six currently unresolved original layouts need further image recognition, header/table segmentation or orientation analysis.
- OCR character errors, item values, supplier/buyer identifiers, tax, amount and date need independent image-confirmed ground truth across the full corpus.
- Opt-in review evidence is returned as metadata; the WPF user-facing review panels do not yet surface these unresolved tokens for correction.
- Actual fully provisioned offline OCR runtime, CPU/GPU switching, complete 51-case review and held-out sources, installer, update, existing-data retention and rollback remain unverified.
- There is no authorization for posting to AAH/Tally or releasing Setup.exe/Update.exe. Keep the PR draft.
