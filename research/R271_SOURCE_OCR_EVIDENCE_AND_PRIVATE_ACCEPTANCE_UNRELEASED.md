# R267–R271 original-source OCR evidence and release acceptance (UNRELEASED)

Date: 2026-10-28. Research branch only. No customer image, confidential OCR transcript, production installer, Tally voucher or app-data mutation is in this commit.

## Implemented safely in the real Windows Child research pipeline

**R267 — independent vertical source ruling witnesses.** Where the actual oriented original image contains two separately detected vertical cell borders, a bounded temporary OCR crop of the cell interior is saved as an additional unverified source alternative. It retains the original-pixel rectangle, the independent original source vertical ruling x coordinates and crop SHA-256. This path requires BOTH printed borders, never replaces literal source OCR, and never certifies a field. In the private seven-row original-photo probe, seven Pcs cells had detected vertical borders; their new OCR readings were *not* more accurate, so no original financial amount/quantity was corrected. The experimental alternate is retained only as uncertain review evidence.

**R268 — exact OCR number fragments, not guessed financial values.** The staged Child source-grid response has a distinct `source_numeric_fragment_review_r268` object. It lists exact character offsets and literal strings of number-like fragments from source words and original-pixel crop OCR alternatives, with all original source geometry/hashes, disagreement flags, and no winner selection. It fails closed on unsupported source types, invalid SHA-256, unsafe row counts, and untrusted "already posted" observations. Numeric substrings within corrupted OCR do *not* become verified quantities, HSNs, rates or amounts.

**R269 — different physical printed dates versus OCR disagreement.** Label associations retain distinct `printed_bill_date`, `printed_invoice_date`, `e_invoice_issue_date` and `generic_date_unresolved` tags. Source date suggestions are grouped by their original-pixel date rectangles first. Different year reads from the SAME physical rectangle are reported as `ocr_disagreement_same_date_region`, not falsely counted as multiple physically printed dates. Source values remain unchanged, no accounting date is selected. The private seven-row source yielded exactly such differing OCR year readings at one original-coordinate date box; this is an *unresolved OCR conflict*, not a corrected bill date.

## Private-original release acceptance contract (R270–R271)

The private-only `experiments/r270_private_original_acceptance.py` requires:
- Exact original-photo SHA-256 and oriented dimensions, independently source-transcribed printed fields, and matching source-linked OCR word boxes.
- Explicit complete required-document-field coverage, including invoice number, invoice date and total. The ONLY permissible unreadable-field exemption is an explicitly reasoned `invoice_number`; never skip items, tax totals, dates or amounts on that basis.
- Exact number of independently printed item rows; each required printed description, quantity, amount and all separately declared required item fields must match their **literal** source transcription and physical source box. Neither arithmetic totals nor approximate string similarity can compensate for missing OCR glyphs.
- A source match audit never authorizes Setup.exe, Update.exe, release merge, data migration or AAH/Tally posting. Production installer/rollback and model-parity acceptance are separate gates.
- Private OCR values are NOT emitted in public GitHub source or in the auditor's summary; mismatches are coded by field and row only.

## Verification and unresolved blockers

- R267 native Windows Child WPF compilation, startup and original-pixel safety regressions: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40629171376 — **PASS**.
- R268 native Child build and exact source fragment conflict regressions: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40629504635 — **PASS**.
- R269 native Child build, original pixel date-region and read-conflict regressions: https://github.com/surajTech-22/InvoiceVision-Child/actions/runs/40629769124 — **PASS**.
- R271 private-source acceptance tests are synthetic and checked by the R225 Windows validation workflow. They do not establish a real user installed application acceptance or match the three private originals automatically.

Last real private-original baseline remains: Sri Rama has one incomplete physical product hypothesis, Nandi has seven physical ruled row bands and 28 **unverified** candidate numeric source-cell witnesses but no complete verified seven-row financial result, and Metro has one incomplete item hypothesis with conflicting OCR money observations; the unreadable identifier remains excluded. No new independent all-character pass of all three has occurred in R267–R271. **Verified accounting fields and accepted rows remain zero.**

Historical public GitHub source history still contains customer photographs, which the R266 "block new media" rule cannot remediate; administrator-controlled history cleansing and prior-access review remain release blockers. Keep PR draft and all production release gates closed.
