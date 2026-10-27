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

def _header_text(value):
    """Match punctuation surrounding printed column labels, not OCR digits."""
    return value.strip(" \t:;.,|()[]{}")

def _table(lines,view,width,height,max_rows):
    """Anchor printed item rows to multi-line, spatially ordered table columns.

    Labels must come from the actual OCR tokens, never a supplier name or
    image-specific coordinate. A common Indian tax-invoice table uses 'Pcs'
    and 'Net Amt' where scanned OCR sometimes renders them 'Pes'/'Ant'.
    These are HEADER aliases only; no quantity or amount is auto-corrected.
    """
    output=[]
    # Source indices identify one physical heading/row *within this OCR view*.
    # Overlapping line bands may see the same printed header twice.
    seen_headers=set()
    seen_numeric_rows=set()
    all_words=[word for line in lines for word in line["words"]]
    for line in lines:
        # Source table headings can span two printed lines; group only within
        # 32 original pixels vertically, then require DESCRIPTION<QTY<AMOUNT.
        band=[x for x in all_words if
              line["cy"]-22 <= (x["box"][1]+x["box"][3])/2 <= line["cy"]+32]
        if len(band)>80:continue
        description=[x for x in band if re.fullmatch(
            r"(?i:DESCRIPTION|PRODUCT|PARTICULARS|ITEM|GOODS)",_header_text(x["text"]))]
        quantities=[x for x in band if re.fullmatch(
            r"(?i:QTY|QUANTITY|PCS|PES|PIECES)",_header_text(x["text"]))]
        amount_tokens=[x for x in band if re.fullmatch(
            r"(?i:AMOUNT|AMT|ANT|NETAMT|NETAMOUNT)",_header_text(x["text"]))]
        if not description or not quantities:continue
        net_tokens=[x for x in band if re.fullmatch(
            r"(?i:NET)",_header_text(x["text"]))]
        total_tokens=[x for x in band if re.fullmatch(
            r"(?i:TOTAL)",_header_text(x["text"]))]
        # Printed headers such as "Total Value (incl. of tax)" often arrive
        # as "Total" + "ValuetInclof" from a photographed invoice. "Value"
        # alone does not prove an item AMOUNT column: require the adjacent
        # source-literal TOTAL label, to the left and on the same table band.
        inclusive_value_tokens=[x for x in band if
            re.match(r"(?i:^VALUE(?:.{0,3}INCL.*)?$)",
                     re.sub(r"\s+","",x["text"]).strip(":|"))]
        eligible_amounts=[]
        for token in amount_tokens:
            name=_header_text(token["text"]).upper()
            if name in ("AMOUNT","NETAMOUNT","NETAMT"):
                eligible_amounts.append(token)
            elif any(0<token["box"][0]-n["box"][0]<80 and
                     abs((token["box"][1]+token["box"][3])/2 -
                         (n["box"][1]+n["box"][3])/2)<24 for n in net_tokens):
                eligible_amounts.append(token)
        for value_header in inclusive_value_tokens:
            if any(0<value_header["box"][0]-tot["box"][0]<105 and
                   abs((value_header["box"][1]+value_header["box"][3])/2 -
                       (tot["box"][1]+tot["box"][3])/2)<25
                   for tot in total_tokens):
                eligible_amounts.append(value_header)
        if not eligible_amounts:continue
        desc=min(description,key=lambda x:x["box"][0])
        qty=min((x for x in quantities if x["box"][0]>desc["box"][0]+35),
                key=lambda x:x["box"][0],default=None)
        if qty is None:continue
        amount=max((x for x in eligible_amounts if
                    x["box"][0]>qty["box"][2]+60),
                   key=lambda x:x["box"][0],default=None)
        if amount is None:continue
        qty_x=(qty["box"][0]+qty["box"][2])/2
        amount_x=(amount["box"][0]+amount["box"][2])/2
        desc_x=(desc["box"][0]+desc["box"][2])/2
        if not(desc_x+35<qty_x<amount_x-55):continue
        header_key=(desc["index"],qty["index"],amount["index"])
        if header_key in seen_headers:continue
        seen_headers.add(header_key)
        header_bottom=max(desc["box"][3],qty["box"][3],amount["box"][3])
        # The old 28%-of-page search cut off tall printed product tables:
        # seven source rows may span more than the OCR header's first quarter.
        # Extend the proposal-only search, still bounded by the image and by
        # printed section headings/totals below. This never certifies rows.
        table_end=min(height,header_bottom+min(max(240,int(height*.50)),900))
        for later in lines:
            if later["cy"]<=header_bottom+30:
                continue
            # A second, separate printed table heading should not be parsed
            # as an item of the previous table. Require all three headings
            # in the same OCR baseline, not the word TOTAL by itself.
            later_words=later["words"]
            if (any(re.fullmatch(r"(?i:DESCRIPTION|PRODUCT|PARTICULARS|ITEM|GOODS)",
                                 _header_text(x["text"])) for x in later_words)
                and any(re.fullmatch(r"(?i:QTY|QUANTITY|PCS|PES|PIECES)",
                                     _header_text(x["text"])) for x in later_words)
                and any(re.fullmatch(r"(?i:AMOUNT|NETAMT|NETAMOUNT)",
                                     _header_text(x["text"])) for x in later_words)):
                table_end=min(table_end,min(x["box"][1] for x in later_words))
        # A printed subtotal/total in the DESCRIPTION region marks the end
        # of the item table. Without this anchor, amounts from later tax/
        # payment summaries can become phantom item rows.
        footer_labels=[x for x in all_words if
                       x["box"][0]<qty["box"][0]-12 and
                       header_bottom+18<(x["box"][1]+x["box"][3])/2<table_end and
                       re.fullmatch(r"(?i:SUBTOTAL|TOTAL|GRAND|NET)",
                                    _header_text(x["text"]))]
        footer_stop=min(((x["box"][1]+x["box"][3])/2 for x in footer_labels),
                        default=table_end+1)
        # Description text determines ROW geometry, not numbers elsewhere.
        anchors=[x for x in all_words if
                 x["box"][0]>=desc["box"][0]-100 and
                 x["box"][2]<qty["box"][0]-12 and
                 header_bottom+3 < (x["box"][1]+x["box"][3])/2 < table_end and
                 re.search(r"[A-Za-z]{2,}",x["text"])]
        anchors.sort(key=lambda x:(x["box"][1]+x["box"][3])/2)
        centers=[]
        for word in anchors:
            cy=(word["box"][1]+word["box"][3])/2
            if centers and abs(centers[-1]["center"]-cy)<=12:
                group=centers[-1]
                old=len(group["words"])
                group["words"].append(word)
                group["center"]=(group["center"]*old+cy)/(old+1)
            else:
                centers.append({"center":cy,"words":[word]})
        for group in centers:
            cy=group["center"]
            if cy>=footer_stop-6:
                break
            # Require a UNIQUE numeric source observation near each detected
            # physical table column. Ambiguity is omitted, never guessed.
            # Distinguish close CS / PCS / Total Units columns from their
            # actual printed header centers, not from guessed invoice data.
            colmarks=[x for x in band if re.fullmatch(
                r"(?i:CS|CASE|TOTAL|UNIT|UNITS|MRP|UPC|PKM|RATE|PRICE|PCS|PES|QTY)",
                _header_text(x["text"]))]
            lefts=[(x["box"][0]+x["box"][2])/2 for x in colmarks
                   if (x["box"][0]+x["box"][2])/2<qty_x-8]
            rights=[(x["box"][0]+x["box"][2])/2 for x in colmarks
                    if (x["box"][0]+x["box"][2])/2>qty_x+8]
            qty_left=(max(lefts)+qty_x)/2 if lefts else qty_x-42
            qty_right=(min(rights)+qty_x)/2 if rights else qty_x+42
            qty_words=[x for x in all_words if
                qty_left <= (x["box"][0]+x["box"][2])/2 <= qty_right and
                abs((x["box"][1]+x["box"][3])/2-cy)<=21 and
                _NUM_RE.fullmatch(x["text"].strip("()|").replace(",",""))]
            amount_words=[x for x in all_words if
                # The nearby RATE value is not an AMOUNT value even if
                # OCR bounding boxes drift. Respect the printed AMOUNT
                # header's left edge to avoid matching two money columns.
                x["box"][0]>=max((qty_x+amount_x)/2,amount["box"][0]-22) and
                abs((x["box"][0]+x["box"][2])/2-amount_x)<=90 and
                abs((x["box"][1]+x["box"][3])/2-cy)<=21 and
                _NUM_RE.fullmatch(x["text"].strip("()|").replace(",",""))]
            if len(qty_words)!=1 or len(amount_words)!=1:continue
            if qty_words[0]["index"]==amount_words[0]["index"]:continue
            physical_key=(qty_words[0]["index"],amount_words[0]["index"])
            if physical_key in seen_numeric_rows:continue
            desc_words=sorted(group["words"],key=lambda x:x["box"][0])
            seen_numeric_rows.add(physical_key)
            output.append({
                "type":"HEADER_COLUMN_ITEM_ROW_UNVERIFIED",
                "source_view":view,
                "row_box":_union(desc_words+qty_words+amount_words),
                "description_original_ocr":" ".join(q["text"] for q in desc_words)[:220],
                "quantity_original_ocr":qty_words[0]["text"],
                "amount_original_ocr":amount_words[0]["text"],
                "description_source_boxes":[q["box"] for q in desc_words],
                "quantity_source_box":qty_words[0]["box"],
                "amount_source_box":amount_words[0]["box"],
                "source_token_indices":[q["index"] for q in desc_words+qty_words+amount_words],
                "header_source_boxes":{"description":desc["box"],
                                       "quantity":qty["box"],
                                       "amount":amount["box"]},
                "row_complete_certified":False,
                "posting_eligible":False
            })
            if len(output)>=max_rows:return output
        # Separate printed product sections are also permitted. A later
        # complete heading sets the prior table boundary; repeated source
        # numeric cells are never emitted again from overlapping bands.
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
        if name not in ("gray_2x","clahe_2x","grid_removed_psm11_2x",
                        "grid_removed_psm6_2x") or name in seen:
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
