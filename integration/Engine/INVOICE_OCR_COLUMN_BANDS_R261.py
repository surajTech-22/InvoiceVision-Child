"""R261: original-source ruled-column candidates, never verified financial fields."""
from __future__ import annotations
import hashlib
import re
import csv
import io
from statistics import median

def _center(b):
    return ((b[0]+b[2])/2,(b[1]+b[3])/2)

def _name(s):
    return re.sub(r"[^A-Z0-9]","",s.upper())

def review(image,bands,variants,width,height,*,max_rows=12,reader=None):
    import cv2
    import numpy as np
    if not hasattr(image,"shape") or image.ndim!=3 or tuple(image.shape[:2])!=(height,width):
        raise ValueError("Original source image required")
    sha=hashlib.sha256(image.tobytes()).hexdigest()
    if reader is not None and not callable(reader):
        raise ValueError('Optional offline original-source OCR reader must be callable')
    if (type(width)!=int or type(height)!=int or not
        (180<=width<=6000 and 180<=height<=6000 and 1<=max_rows<=12)):
        raise ValueError("Unsafe original image dimensions")
    if (not isinstance(bands,dict) or
        bands.get("status")!="SOURCE_REPEATED_RULING_ROW_BANDS_REVIEW_ONLY" or
        bands.get("posting_eligible") is not False or bands.get("verified_item_rows")!=0):
        raise ValueError("Trusted source ruling evidence required")
    rows=bands.get("row_bands");rulers=bands.get("physical_divider_y_at_amount_column")
    headers=bands.get("source_table_header_boxes")
    if (not isinstance(rows,list) or not (1<=len(rows)<=max_rows) or
        not isinstance(rulers,list) or len(rulers)!=len(rows)+1 or
        not isinstance(headers,dict) or not isinstance(variants,list) or len(variants)!=2):
        raise ValueError("Unbounded source grid evidence")
    words=[];seen=set()
    for view in variants:
        if (not isinstance(view,dict) or view.get("posting_eligible") is not False
            or view.get("source_boxes_are_original_pixels") is not True
            or not isinstance(view.get("variant"),str)
            or view["variant"] in seen):
            raise ValueError("Untrusted source OCR view")
        seen.add(view["variant"]);source=view.get("source_words")
        if not isinstance(source,list) or len(source)>480:
            raise ValueError("Excessive source words")
        for i,token in enumerate(source):
            box=token.get("original_source_box") if isinstance(token,dict) else None
            text=token.get("original_source_text") if isinstance(token,dict) else None
            if (not isinstance(box,list) or len(box)!=4 or
                any(type(z)!=int for z in box) or
                not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height) or
                not isinstance(text,str) or not text.strip() or len(text)>1500):
                raise ValueError("Invalid original-coordinate OCR word")
            words.append({"box":box,"text":text.strip(),"view":view["variant"],"index":i})
    if any(not isinstance(b,list) or len(b)!=4 or
           any(type(z)!=int for z in b) or not
           (0<=b[0]<b[2]<=width and 0<=b[1]<b[3]<=height)
           for b in headers.values()):
        raise ValueError("Invalid source headings")
    top=min(b[1] for b in headers.values());bottom=max(b[3] for b in headers.values())
    heading=[w for w in words if abs(_center(w["box"])[1]-(top+bottom)/2)<=45]
    def pick(regex):
        return [w for w in heading if re.fullmatch(regex,_name(w["text"]))]
    wants={"printed_hsn":pick("HSN"),"printed_pcs":pick("PCS|PES|QTY|QUANTITY"),
           "printed_base_rate":pick("BASE"),"printed_taxable_amount":pick("TAXABLE")}
    marks=[w for w in heading if re.fullmatch(
        "HSN|CS|CASE|PCS|PES|QTY|UN|UNITS|TOTAL|PKM|MRP|UPC|"
        "BASE|RATE|SCH|DISC|RS|TAXABLE|GST|CGST|SGST|NET|AMT",
        _name(w["text"]))]
    columns={};missing=[];ambiguous=[]
    for field,tokens in wants.items():
        groups=[]
        for token in sorted(tokens,key=lambda w:_center(w["box"])[0]):
            x=_center(token["box"])[0]
            group=next((g for g in groups if abs(g["x"]-x)<=15),None)
            if group:group["evidence"].append(token)
            else:groups.append({"x":x,"evidence":[token]})
        if not groups:
            missing.append(field);continue
        if field=="printed_pcs" and len(groups)>1:
            # On retail invoices "Sch/Pcs" or an isolated "/Pes" is a
            # different discount-per-piece heading from the quantity Pcs.
            # Resolve only if EXACTLY ONE physical candidate is bracketed
            # by independently printed CS/CASE and TOTAL/UNITS headings.
            # No guessed x coordinate, supplier name or OCR number is used.
            left_marks=[_center(m["box"])[0] for m in marks
                        if _name(m["text"]) in ("CS","CASE")]
            right_marks=[_center(m["box"])[0] for m in marks
                         if _name(m["text"]) in ("TOTAL","UNITS")]
            max_gap=max(80,min(180,width*.115))
            bracketed=[g for g in groups
                       if any(0<g["x"]-lx<max_gap for lx in left_marks)
                       and any(0<rx-g["x"]<max_gap for rx in right_marks)]
            if len(bracketed)==1:
                groups=bracketed
        if len(groups)!=1:
            ambiguous.append(field);continue
        group=groups[0];anchor=group["x"]
        # Never promote arbitrary BASE text to a monetary rate header.
        if field=="printed_base_rate" and not any(
            abs(_center(t["box"])[0]-anchor)<=32 and
            abs(_center(t["box"])[1]-_center(group["evidence"][0]["box"])[1])<=32
            for t in pick("RATE")):
            missing.append(field);continue
        other=[_center(x["box"])[0] for x in marks if abs(_center(x["box"])[0]-anchor)>15]
        ls=[x for x in other if x<anchor];rs=[x for x in other if x>anchor]
        span=max(42,min(90,width*.030))
        left=max((max(ls)+anchor)/2,anchor-span) if ls else anchor-span
        right=min((min(rs)+anchor)/2,anchor+span) if rs else anchor+span
        if right-left<15:
            ambiguous.append(field);continue
        columns[field]={"heading_x":round(anchor,2),"left":round(left,2),
                        "right":round(right,2),
                        "header_source_provenance":[{"view":w["view"],
                          "source_token_index":w["index"],
                          "literal":w["text"],"source_box":w["box"]}
                          for w in group["evidence"]]}
    # Never reuse the far-right source y rulings as the y boundaries of a
    # different numeric column on a skewed invoice photograph.
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    fg=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                             cv2.THRESH_BINARY_INV,41,12)
    kw=max(28,min(75,round(width*.035)))
    horizontal=cv2.morphologyEx(fg,cv2.MORPH_OPEN,
                  cv2.getStructuringElement(cv2.MORPH_RECT,(kw,1)))
    first_top=min(p[1] for p in rows[0]["source_description_quad"])
    last_bottom=max(p[1] for p in rows[-1]["source_description_quad"])
    pitch=median([rulers[i+1]-rulers[i] for i in range(len(rows))])
    search_top=max(0,int(first_top-max(10,pitch*.6)))
    search_end=min(height,int(last_bottom+max(12,pitch*.85)))
    for col in columns.values():
        x=round(col["heading_x"]);margin=max(8,min(22,round(width*.012)))
        if x-margin<0 or x+margin>=width:continue
        trace=np.count_nonzero(horizontal[search_top:search_end,x-margin:x+margin],axis=1)
        ys=np.flatnonzero(trace>=max(5,round(margin*.44)))+search_top
        groups=[]
        for y in ys:
            if groups and y-groups[-1][-1]<=2:groups[-1].append(int(y))
            else:groups.append([int(y)])
        dividers=[float(median(g)) for g in groups];n=len(rows)
        matches=[]
        for start in range(max(0,len(dividers)-n)):
            part=dividers[start:start+n+1]
            if (all(.70*pitch<=part[j+1]-part[j]<=1.30*pitch for j in range(n))
                and abs(part[0]-first_top)<=max(18,pitch*1.1)
                and abs(part[-1]-last_bottom)<=max(18,pitch*1.1)):
                matches.append(part)
        if len(matches)!=1:
            col["local_ruling_status"]="NO_UNIQUE_PHYSICAL_COLUMN_GRID";continue
        col["local_divider_y_original_pixels"]=matches[0]
        col["local_ruling_status"]="ORIGINAL_SOURCE_PIXEL_RULINGS"
    out=[];used={}
    for idx,row in enumerate(rows):
        quad=row.get("source_description_quad") if isinstance(row,dict) else None
        if (not isinstance(quad,list) or len(quad)!=4 or
            any(not isinstance(p,list) or len(p)!=2 or
                any(type(z)!=int for z in p) or
                not (0<=p[0]<=width and 0<=p[1]<=height) for p in quad) or
            row.get("row_number_is_proposal")!=idx+1 or
            row.get("posting_eligible") is not False or
            row.get("source_values_verified") is not False):
            raise ValueError("Unsafe physical source row geometry")
        if not (0<=rulers[idx]<rulers[idx+1]<=height):
            raise ValueError("Invalid source row pitch")
        fields={}
        for field,col in columns.items():
            if col.get("local_ruling_status")!="ORIGINAL_SOURCE_PIXEL_RULINGS":
                continue
            observations=[]
            for word in words:
                x,y=_center(word["box"])
                if not col["left"]<=x<=col["right"]:continue
                lines=col["local_divider_y_original_pixels"]
                if not lines[idx]+1<=y<=lines[idx+1]-1:continue
                if not re.search(r"\d",word["text"]):continue
                key=(word["view"],word["index"])
                if key in used and used[key]!=idx:
                    raise ValueError("Source numeric token claimed by two rows")
                used[key]=idx
                observations.append({"source_view":word["view"],
                    "source_token_index":word["index"],
                    "original_source_text":word["text"],
                    "original_source_box":word["box"],
                    "numeric_text_verified":False,"posting_eligible":False})
            crop_views=[]
            if reader is not None:
                # Only a genuine local ruled cell may be reread. No guessed
                # header, extrapolated y from a different source column, or
                # arithmetic-generated source box is permitted here.
                x0=max(0,int(col["left"])+1)
                x1=min(width,int(col["right"])-1)
                y0=max(0,int(lines[idx])+2)
                y1=min(height,int(lines[idx+1])-1)
                if x1-x0<8 or y1-y0<7:
                    raise ValueError("Unsafe original numeric cell crop")
                original_crop=image[y0:y1,x0:x1]
                original_crop_sha=hashlib.sha256(original_crop.tobytes()).hexdigest()
                # The interpolation exists only in memory as an OCR witness.
                scaled=cv2.resize(original_crop,None,fx=4,fy=4,
                                  interpolation=cv2.INTER_CUBIC)
                def read_words(psm):
                    tsv=reader(scaled,psm)
                    if not isinstance(tsv,str) or len(tsv)>100_000:
                        raise ValueError("Unbounded source numeric OCR TSV")
                    parsed=csv.DictReader(io.StringIO(tsv),delimiter="\t")
                    if not parsed.fieldnames or not {"level","text"}<=set(parsed.fieldnames):
                        raise ValueError("Malformed source numeric OCR TSV")
                    return [v["text"].strip() for v in parsed
                            if v.get("level")=="5" and v.get("text","").strip()][:30]
                words_psm7=read_words(7)
                crop_views.append({
                    "source":"TEMP_ORIGINAL_NUMERIC_CELL_PSM7",
                    "ocr_literal_text":" ".join(words_psm7)[:240],
                    "original_source_pixel_rect":[x0,y0,x1,y1],
                    "original_crop_sha256":original_crop_sha,
                    "source_text_verified":False,"posting_eligible":False})
                # Garbled nonempty PSM7 output (e.g., border symbols joined
                # to digits) must not block an independent second source
                # witness. Run the bounded alternative only on unreliable
                # literal single-cell OCR; never select or certify a value.
                psm7_single_numeric=(len(words_psm7)==1 and
                    re.fullmatch(r"[+-]?\d+(?:,\d{2,3})*(?:\.\d{1,2})?",
                                 words_psm7[0]) is not None)
                if not psm7_single_numeric:
                    words_psm6=read_words(6)
                    crop_views.append({
                        "source":"TEMP_ORIGINAL_NUMERIC_CELL_PSM6_FALLBACK",
                        "ocr_literal_text":" ".join(words_psm6)[:240],
                        "original_source_pixel_rect":[x0,y0,x1,y1],
                        "original_crop_sha256":original_crop_sha,
                        "source_text_verified":False,"posting_eligible":False})
            fields[field]={"header_original_source":col["header_source_provenance"],
                "source_column_x":[col["left"],col["right"]],
                "source_observations":observations,
                "source_crop_ocr_alternatives":crop_views,
                "field_value_certified":False,"posting_eligible":False}
        out.append({"row_number_is_proposal":idx+1,"source_description_quad":quad,
                    "original_source_numeric_fields":fields,
                    "missing_printed_headers":list(missing),
                    "ambiguous_printed_headers":list(ambiguous),
                    "row_completely_verified":False,"posting_eligible":False})
    if hashlib.sha256(image.tobytes()).hexdigest()!=sha:
        raise RuntimeError("Source pixels changed")
    return {"status":"PRINTED_RULING_COLUMNS_REVIEW_ONLY",
            "source_row_count":len(out),
            "printed_numeric_headers_found":sorted(columns),
            "missing_printed_headers":missing,
            "ambiguous_printed_headers":ambiguous,
            "column_geometry":columns,"source_numeric_row_proposals":out,
            "certified_financial_fields":0,"certified_item_rows":0,
            "first_pass_ocr_modified":False,"accounting_write_permitted":False,
            "posting_eligible":False,"release_approved":False}
