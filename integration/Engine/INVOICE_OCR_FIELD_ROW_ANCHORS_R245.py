"""R245: source-anchored field and table-column association across 2x OCR views.

Input consists solely of the original-pixel rectangles and exact OCR text
from R243. An anchor (label or physical table heading) is required before
proposing a value. No customer/vendor identifiers or values are hardcoded.
These are *unverified associations*, not corrected data or accounting fields.
"""
from __future__ import annotations
import re
from statistics import median

_FIELD_LABELS=(
    ("invoice_number",re.compile(r"\b(?:INVOICE|INV)\s*(?:NO|NUMBER|#|NUM)\b[.:\s#-]*",re.I)),
    ("invoice_date",re.compile(r"\b(?:INVOICE\s*DATE|BILL\s*DATE|DATE)\b[.:\s-]*",re.I)),
    ("net_total",re.compile(r"\b(?:GRAND\s*TOTAL|NET\s*(?:PAYABLE|AMOUNT)|TOTAL\s*PAYABLE)\b[.:\s-]*",re.I)),
)
_NUM_RE=re.compile(r"^(?:[₹Rs.\s]*)(\d+(?:,\d{2,3})*(?:\.\d{1,2})?)$")
_DATE_RE=re.compile(r"(?:0?[1-9]|[12][0-9]|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}")
_INV_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_-]{1,49}$")
_HEADS={
    "description": re.compile(r"^(?:DESCRIPTION|PARTICULARS|ITEM|PRODUCT|GOODS)$",re.I),
    "quantity": re.compile(r"^(?:QTY|QUANTITY|UNITS?|PCS)$",re.I),
    "rate": re.compile(r"^(?:RATE|PRICE|UNIT\s*RATE)$",re.I),
    "amount": re.compile(r"^(?:AMOUNT|VALUE|TOTAL)$",re.I)
}

def _tokenbox(item,w,h):
    if not isinstance(item,dict):
        raise ValueError("Nonobject source OCR observation")
    box=item.get("original_source_box")
    text=item.get("original_source_text")
    if (not isinstance(text,str) or len(text)>1500 or not text.strip() or
        not isinstance(box,list) or len(box)!=4 or
        any(type(q)!=int for q in box) or
        not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h)):
        raise ValueError("Invalid source-bound OCR observation")
    return box,text.strip()

def _lines(words):
    """Group words on original printed horizontal baselines, not OCR order."""
    if not words:return []
    heights=[v["box"][3]-v["box"][1] for v in words]
    tol=max(7,min(35,median(heights)*.70))
    lines=[]
    for word in sorted(words,key=lambda q:((q["box"][1]+q["box"][3])/2,q["box"][0])):
        cy=(word["box"][1]+word["box"][3])/2
        line=min(lines,key=lambda q:abs(q["cy"]-cy)) if lines else None
        if line is None or abs(line["cy"]-cy)>tol:
            lines.append({"cy":cy,"words":[word]})
        else:
            n=len(line["words"])
            line["words"].append(word)
            line["cy"]=(line["cy"]*n+cy)/(n+1)
    for line in lines:
        line["words"].sort(key=lambda q:q["box"][0])
    return sorted(lines,key=lambda q:q["cy"])

def _union(words):
    b=[q["box"] for q in words]
    return [min(q[0] for q in b),min(q[1] for q in b),
            max(q[2] for q in b),max(q[3] for q in b)]

def _add_field(view,line,category,match,output):
    words=line["words"]
    text=" ".join(w["text"] for w in words)
    # Associate right-hand print only when the candidate follows its LABEL.
    # Match spans are mapped to actual OCR words through the same join layout.
    spans=[];cursor=0
    for word in words:
        spans.append((cursor,cursor+len(word["text"])))
        cursor+=len(word["text"])+1
    anchor=[words[i] for i,(a,b) in enumerate(spans) if a<match.end() and b>match.start()]
    remaining=[words[i] for i,(a,b) in enumerate(spans) if a>=match.end()]
    if not anchor or not remaining:return
    if len(remaining)>8:return
    tail=text[match.end():].strip().lstrip(": #-")
    if not tail:return
    if category=="invoice_number":
        values=[word for word in remaining if _INV_RE.fullmatch(word["text"])]
        if len(values)!=1 or not any(c.isdigit() for c in values[0]["text"]):return
        chosen=values[0]["text"]
        evidence=[values[0]]
    elif category=="invoice_date":
        m=_DATE_RE.search(tail)
        if not m:return
        chosen=m.group()
        evidence=remaining
    else:
        nums=[]
        for word in remaining:
            v=word["text"].replace(",","")
            m=_NUM_RE.fullmatch(v)
            if m:nums.append((word,m.group(1)))
        if len(nums)!=1:return
        evidence=[nums[0][0]];chosen=nums[0][1]
    output.append({
        "type":"LABEL_VALUE_NEAR_SOURCE",
        "category":category,"candidate_text":chosen,
        "source_view":view,
        "label_literal_source_text":[w["text"] for w in anchor],
        "value_literal_source_text":[w["text"] for w in evidence],
        "label_source_box":_union(anchor),
        "value_source_box":_union(evidence),
        "field_value_certified":False,"posting_eligible":False
    })

def _table(lines,view,width,height,max_rows):
    """Require physically separate QTY and AMOUNT headers to propose rows."""
    output=[]
    for li,line in enumerate(lines):
        headers={}
        for word in line["words"]:
            text=word["text"].strip().strip(":")
            for name,regex in _HEADS.items():
                if regex.fullmatch(text) and name not in headers:
                    headers[name]=word
        if not {"quantity","amount"}.issubset(headers):
            continue
        head=headers
        qty=(head["quantity"]["box"][0]+head["quantity"]["box"][2])/2
        amount=(head["amount"]["box"][0]+head["amount"]["box"][2])/2
        if abs(qty-amount)<30:continue
        # Column spans derived only from actual source headings.
        col_bounds=sorted([qty,amount])
        if amount<qty:continue
        split=(qty+amount)/2
        header_bottom=max(q["box"][3] for q in head.values())
        table_end=min(height,header_bottom+min(max(140,int(height*.22)),650))
        for l in lines[li+1:]:
            if l["cy"]<=header_bottom or l["cy"]>table_end:continue
            source=l["words"]
            qty_words=[q for q in source if q["box"][0]>=qty-42 and q["box"][2]<=split+12
                       and _NUM_RE.fullmatch(q["text"].replace(",",""))]
            amount_words=[q for q in source if q["box"][0]>=split and
                          q["box"][0]<=amount+60 and
                          _NUM_RE.fullmatch(q["text"].replace(",",""))]
            if len(qty_words)!=1 or len(amount_words)!=1:continue
            if qty_words[0]["index"]==amount_words[0]["index"]:continue
            desc=[q for q in source if q["box"][2]<qty-10 and
                  re.search(r"[A-Za-z]",q["text"])]
            if not desc:continue
            output.append({
                "type":"HEADER_COLUMN_ITEM_ROW_UNVERIFIED",
                "source_view":view,
                "row_box":_union(desc+qty_words+amount_words),
                "description_original_ocr":" ".join(q["text"] for q in desc)[:220],
                "quantity_original_ocr":qty_words[0]["text"],
                "amount_original_ocr":amount_words[0]["text"],
                "description_source_boxes":[q["box"] for q in desc],
                "quantity_source_box":qty_words[0]["box"],
                "amount_source_box":amount_words[0]["box"],
                "source_token_indices":[q["index"] for q in desc+qty_words+amount_words],
                "header_source_boxes":{key:value["box"] for key,value in head.items()},
                "row_complete_certified":False,"posting_eligible":False
            })
            if len(output)>=max_rows:return output
        break
    return output

def propose(alternate,width,height,*,max_fields=30,max_rows=15):
    if not (type(width)==int and type(height)==int and
            0<width<=30000 and 0<height<=30000 and
            1<=max_fields<=40 and 1<=max_rows<=20):
        raise ValueError("Invalid original source image dimensions or caps")
    if not isinstance(alternate,dict) or alternate.get("status")!="SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY" or alternate.get("posting_eligible") is not False:
        raise ValueError("Only read-only R243 source evidence accepted")
    views=alternate.get("variants")
    if not isinstance(views,list) or len(views)!=2:
        raise ValueError("Two original-source OCR views required")
    fields=[];rows=[];seen=set()
    for view in views:
        if not isinstance(view,dict) or view.get("posting_eligible") is not False or view.get("source_boxes_are_original_pixels") is not True:
            raise ValueError("Variant lacks trusted source geometry")
        name=view.get("variant")
        if name not in ("gray_2x","clahe_2x") or name in seen:
            raise ValueError("Unexpected or duplicate source OCR view")
        seen.add(name)
        source=view.get("source_words")
        if not isinstance(source,list) or len(source)>600:
            raise ValueError("Unbounded source observations")
        words=[]
        for i,item in enumerate(source):
            box,raw=_tokenbox(item,width,height)
            words.append({"index":i,"box":box,"text":raw})
        lines=_lines(words)
        for line in lines:
            text=" ".join(q["text"] for q in line["words"])
            for category,pattern in _FIELD_LABELS:
                match=pattern.search(text)
                if match and len(fields)<max_fields:
                    _add_field(name,line,category,match,fields)
        if len(rows)<max_rows:
            rows+=_table(lines,name,width,height,max_rows-len(rows))
    return {
        "status":"SOURCE_FIELD_AND_ITEM_ROW_ASSOCIATIONS_REVIEW_ONLY",
        "source_views":sorted(seen),
        "field_label_anchored_proposals":fields,
        "field_proposals_count":len(fields),
        "table_header_anchored_row_proposals":rows,
        "row_proposals_count":len(rows),
        "source_box_orientation":"Child_decoded_oriented_source_frame",
        "source_values_overwritten":False,
        "verified_invoice_fields":0,
        "verified_table_rows":0,
        "accounting_write_permitted":False,
        "posting_eligible":False,
        "release_approved":False
    }
