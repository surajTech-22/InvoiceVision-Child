"""R239 independent, read-only Indian GSTIN checksum validator.

Checksum is evidence of OCR quality, NOT authoritative proof of supplier
identity. Never modify OCR source data or authorize accounting posting.
"""
import re
A="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
FORM=re.compile(r"\\A[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]\\Z")
FIND=re.compile(r"(?<![A-Za-z0-9])([0-9]{2}[A-Za-z]{5}[0-9]{4}[A-Za-z][A-Za-z0-9]Z[A-Za-z0-9])(?![A-Za-z0-9])")

def check_digit(value):
    if not isinstance(value,str) or len(value)!=14 or any(c not in A for c in value):
        raise ValueError("Expected uppercase 14-char GSTIN prefix")
    factor=2;total=0
    for c in reversed(value):
        n=A.index(c)*factor
        total+=n//36+n%36
        factor=1 if factor==2 else 2
    return A[(36-total%36)%36]

def review(texts,boxes):
    if not isinstance(texts,list) or not isinstance(boxes,list) or len(texts)!=len(boxes) or len(texts)>20000:
        raise ValueError("Invalid original OCR evidence")
    proposals=[]
    for i,(raw,box) in enumerate(zip(texts,boxes)):
        if not isinstance(raw,str) or not isinstance(box,list) or len(box)!=4 or any(type(z)!=int for z in box) or not (0<=box[0]<box[2] and 0<=box[1]<box[3]):
            raise ValueError("Invalid OCR text/rectangle")
        for match in FIND.finditer(raw):
            literal=match.group(1);code=literal.upper()
            pattern=bool(FORM.fullmatch(code))
            expected=check_digit(code[:14]) if pattern else None
            proposals.append({
                "source_token_index":i,"original_box":list(box),
                "original_text_substring":literal,
                "original_span":[match.start(1),match.end(1)],
                "format_valid":pattern,
                "checksum_valid":bool(pattern and code[-1]==expected),
                "expected_check_digit":expected,
                "original_ocr_modified":False,
                "printed_identity_certified":False,
                "accounting_write_permitted":False,
                "posting_eligible":False,
            })
    return {
        "status":"GSTIN_SOURCE_CHECKDIGIT_REVIEW_ONLY",
        "total_observed":len(proposals),
        "checksum_disagreements":sum(not v["checksum_valid"] for v in proposals),
        "candidates":proposals,
        "source_ocr_modified":False,"approved_gstin_values":0,
        "accounting_write_permitted":False,"posting_eligible":False,
        "release_approved":False}
