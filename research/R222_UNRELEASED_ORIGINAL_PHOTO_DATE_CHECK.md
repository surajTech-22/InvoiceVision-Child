# R222 — original-invoice photo recheck (research only)

**2026-10-26. Not a Windows Child release. No auto-posting or original-text replacement.**

## Independent local test using the user's original photographs
- Recovered original R153 checkpoint: 15 exact JPEG bytes, 15/15 SHA-256 checks matched the saved Child OCR metadata.
- Kept 2,361/2,361 original PaddleOCR text observations and coordinates unchanged.
- R222 examined the original image regions, separately running the local Tesseract engine on an enlarged source crop and a locally contrast-adjusted view.
- Rotated a *derived* OCR crop by 90 degrees for tall sideways text. The source photograph and original bounding boxes were not transformed.
- Seven date anomalies across 15 real photos: five source-only boundaries for glued date/time, two alternate readings requiring human review.
- Found two image-backed discrepancies:
  - **1000258304.jpg**, Nandi Marketing e-invoice date: saved Child OCR `31/00/2026`; original printed photograph and both alternate OCR views `31/08/2026`.
  - **2ed12198-cc5a-4dc9-8f5c-70029f8b4f4b.jpg**, sideways Nandi Marketing bill date: saved Child OCR `04/09/2025 14:37:09`; original printed photograph and both alternate OCR views show date `04/09/2026`.
- Combined R220/R221/R222 local suite: **24/24 test methods passed**; R222 has 9 local regression methods including two genuine original-photograph checks.
- Source material/photos and visual review remain in the user's local evidence ZIP and are **not** committed to GitHub.

## Limitations, release blockers
- Two preprocessing views are **correlated runs of one OCR engine**, not independent accuracy certifications.
- All outputs are proposals only: `human_review_required=true`, `accounting_write_permitted=false`, `release_approved=false`.
- Cases without recognized date patterns are not considered verified; the module neither discovers all invoice fields nor repairs all OCR errors.
- No full character-level ground truth, item-table truth, recursively verified physical box boundaries, or full Child application integration established.
- The runtime needs Python, NumPy, OpenCV, and locally installed Tesseract. Not yet installed, wired into WPF, or performance-verified on customer Windows machines.
- Synthetic Windows/Linux workflow is **manual dispatch only** while GitHub-hosted runners have been failing before job steps. Cross-platform CI result is NOT certified. Real photos are deliberately excluded from GitHub CI.
- Setup.exe, Update.exe, AAH/Tally posting, and rollout remain **blocked**.

## Repeatable offline tests
```bash
python -m unittest discover -s experiments -p 'test_r22*.py' -v
python experiments/check_r222_original_source_dates_synthetic.py
```
The full real-source replay additionally requires the exact 15 source JPEGs and their saved Child OCR report from the user's R153 evidence checkpoint, neither of which is stored in this repository.
