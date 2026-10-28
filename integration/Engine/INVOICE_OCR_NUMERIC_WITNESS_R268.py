"""R268: bounded lexical evidence for source-number review, NOT financial OCR.

This only annotates literal already-observed OCR characters. It neither
calculates monetary values nor approves, normalizes, or posts invoice data.
"""
from __future__ import annotations
import re

# Character boundaries avoid treating a digit inside an OCR word as an
# independent printed financial field. Original text and span always survive.
_FRAGMENT=re.compile(r"(?<![A-Za-z0-9])\d+(?:,\d{2,3})*(?:\.\d{1,2})?(?![A-Za-z0-9])")
_FIELDS={"printed_hsn","printed_pcs","printed_base_rate","printed_taxable_amount"}

def _one_text(text, source, original_rect=None):
    if not isinstance(text,str) or len(text)>240:
        raise ValueError("Unbounded literal source OCR")
    matches=list(_FRAGMENT.finditer(text))
    if len(matches)>15:
        raise ValueError("Too many numeric substrings")
    return {
        "source":source,
        "literal_original_ocr":text,
        "source_rect":original_rect,
        "numeric_substrings":[{
            "literal_substring":m.group(),
            "start_char":m.start(),
            "end_char":m.end(),
            "adjacent_non_numeric_ocr":bool(text[:m.start()].strip() or
                                            text[m.end():].strip()),
            "field_value_verified":False,"posting_eligible":False}
            for m in matches],
        "original_value_rewritten":False,
        "field_value_certified":False,"posting_eligible":False
    }

def review(column_review):
    """Report contradictions and exact OCR digit spans for each physical row."""
    if (not isinstance(column_review,dict) or
        column_review.get("status")!="PRINTED_RULING_COLUMNS_REVIEW_ONLY" or
        column_review.get("posting_eligible") is not False or
        column_review.get("certified_item_rows")!=0 or
        column_review.get("certified_financial_fields")!=0):
        raise ValueError("Only original source unverified numeric review allowed")
    rows=column_review.get("source_numeric_row_proposals")
    if not isinstance(rows,list) or len(rows)>12:
        raise ValueError("Unbounded source row count")
    output=[]
    for position,row in enumerate(rows,1):
        if (not isinstance(row,dict) or row.get("row_number_is_proposal")!=position
            or row.get("posting_eligible") is not False
            or row.get("row_completely_verified") is not False):
            raise ValueError("Nonprovisional source row")
        fields=row.get("original_source_numeric_fields")
        if not isinstance(fields,dict) or not set(fields)<=_FIELDS:
            raise ValueError("Unknown numeric source field")
        present={}
        for label,cell in fields.items():
            if (not isinstance(cell,dict) or cell.get("posting_eligible") is not False
                or cell.get("field_value_certified") is not False):
                raise ValueError("Untrusted financial field cell")
            raw=cell.get("source_observations")
            crops=cell.get("source_crop_ocr_alternatives")
            if (not isinstance(raw,list) or len(raw)>24 or
                not isinstance(crops,list) or len(crops)>12):
                raise ValueError("Unbounded OCR source alternatives")
            witnesses=[]
            for o in raw:
                if (not isinstance(o,dict) or
                    o.get("numeric_text_verified") is not False or
                    o.get("posting_eligible") is not False or
                    not isinstance(o.get("source_view"),str) or
                    not isinstance(o.get("source_token_index"),int)):
                    raise ValueError("Untrusted original OCR token")
                witnesses.append(_one_text(
                    o.get("original_source_text"),
                    "ORIGINAL_OCR:"+o["source_view"]+":"+str(o["source_token_index"]),
                    o.get("original_source_box")))
            for o in crops:
                if (not isinstance(o,dict) or
                    o.get("source_text_verified") is not False or
                    o.get("posting_eligible") is not False or
                    not isinstance(o.get("source"),str)):
                    raise ValueError("Untrusted original source crop")
                box=o.get("original_source_pixel_rect")
                digest=o.get("original_crop_sha256")
                if (not isinstance(box,list) or len(box)!=4 or
                    any(type(z)!=int for z in box) or
                    not (0<=box[0]<box[2] and 0<=box[1]<box[3]) or
                    not isinstance(digest,str) or
                    not re.fullmatch(r"[0-9a-f]{64}",digest)):
                    raise ValueError("Source crop hash or geometry missing")
                witnesses.append(_one_text(o.get("ocr_literal_text"),o["source"],box))
            distinct=sorted({v["literal_substring"]
                             for w in witnesses for v in w["numeric_substrings"]})
            count=sum(len(w["numeric_substrings"]) for w in witnesses)
            # Identical OCR text from independent passes is not source truth;
            # merely record agreement/disagreement and keep all alternatives.
            present[label]={
                "source_witnesses":witnesses,
                "numeric_fragment_alternatives":distinct,
                "numeric_fragment_observations":count,
                "has_unresolved_disagreement":len(distinct)>1,
                "needs_original_pixel_verification":True,
                "candidate_value_selected":False,
                "field_value_certified":False,
                "posting_eligible":False}
        output.append({"row_number_is_proposal":position,
            "numeric_fields":present,"row_complete_certified":False,
            "posting_eligible":False})
    return {
        "status":"LITERAL_NUMERIC_SOURCE_FRAGMENTS_REVIEW_ONLY",
        "source_row_count":len(output),
        "source_rows":output,
        "verified_financial_fields":0,"verified_item_rows":0,
        "accounting_write_permitted":False,"posting_eligible":False,
        "release_approved":False}
