# R138 — Dual CPU OCR and source-field evidence: UNRELEASED
2026-10-20. Original Child/AAH unchanged. No approved installation or posting.

## Verified
- Both RapidOCR and PaddleOCR completed CPU inference on all 15 original real photographs. Exact original image hashes match between engine artifacts.
- Token region alignment: 1,861 matching normalized readings, 260 close differences, 186 larger differences. These are not accuracy statistics.
- Across 15 original photos: 50 field hypotheses have same-region support from the other OCR engine, 36 have conflicting readings, 2 lack paired support. None has semantic or physical-layout approval.
- R138 conservative source-linked field and cross-engine conflict unit tests passed on both Windows and Linux.
- R135 source integrity was 51/51; baseline includes 68 unresolved OCR associations. No physical table/cell geometry fully approved.

## Source-based cases
- Metro: separate METRO and Cash and Carry India Ltd. word boxes can be considered together as a source text candidate; amount 3813.75 is near Total Amount / Net Amount.
- Veerabhadreshwara: From/To proximity gives vendor and buyer candidates. Keep OCR buyer spelling TRDING unchanged. Net Payable :5181.00 must not be replaced by round-off -0.27.
- Bairava: Amount Chargeable (in words) has 1,430.00 nearby. A company name in a signature zone cannot establish supplier authority.
- Durga: source grand total token 1431 is numerically equivalent to 1431.00; retain its original raw form.

## Files / safety
- experiments/r138_field_evidence.py; experiments/test_r138_field_evidence.py; experiments/r138_cross_model_consensus.py; experiments/test_r138_cross_model_consensus.py
- Preserve original source SHA-256 and each original OCR word polygon and raw engine reading.
- Never trust unsupported borders or auto-post an unverified candidate; no majority voting against source evidence.
- Outstanding gates: 51-unique/52-logical source visual acceptance, 68 text associations, independent supplier/buyer/invoice/item/tax/total zoning, unfamiliar layouts, native Child GUI, CPU-only dependencies, optional GPU, Windows install and rollback safety.

Status: BLOCKED. Retain research branch only, not an approved Setup.exe or Update.exe.