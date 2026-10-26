# R230 — HSN digit-source conflicts require review (UNRELEASED)

Date: 26 October 2026.

Local original-source HSN review on the private invoice photographs recovered from the user's R153 checkpoint:
- 14 HSN-digit sources selected using original, source-hash-bound R229 item-row coordinates.
- Independent Tesseract engine default reread: 2/14 matches to saved Child OCR, 8 disagreements, 4 with no digits.
- Eight preprocessing/PSM variants of that **same** engine: 10/14 with at least one matching variant, 4/14 never matching. The variants are **correlated evidence**, not ground truth; no character or HSN value was certified.
- No OCR source text was overwritten. Original image hashes, source boxes and user accounting data remain unchanged. Neither confidence nor approvals were fabricated.
- The public repository contains **only the generic code and synthetic test cases**; no original photographs or raw customer OCR strings were uploaded for R230.

Added `experiments/r230_source_digit_disagreement.py` and eight synthetic safety tests. GitHub Windows **and** Linux jobs passed: [R230 safety run 40317772626](https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40317772626).

Review-only evidence ZIP shared with the user: `InvoiceVision_R230_Crop_OCR_Conflict_Evidence.zip`; SHA-256 `826dc06d238b9d0674839ccec1bb3bb75027778a73a9fa7350492e409a244a7f`.

**Production blockers remain:** full recognition accuracy with independent visual ground truth, missing/corrupted text, appropriate offline OCR runtime, UI review confirmation, full 51-case+held-out invoice acceptance, installers/updater/rollback verification. No automatic posting or release.

**Privacy blocker:** At this checkpoint the repository still reports `visibility=public` and its baseline source archive has a nested original-invoice photo corpus. Visibility changes, public history/fork assessment and incident handling require repository owner/administrator action. Do not further distribute this archive.
