"""R248 original-pixel table amount reread, never automatic value substitution.

When cell-bound OCR loses a leading digit, a bounded context crop can recover
additional text. Original source boxes and all alternate OCR readings remain
visible; multiple OCR modes from the same engine do NOT certify a field.
"""
from __future__ import annotations
import hashlib
import re

_NUMBERS=re.compile(r"(?<![A-Za-z0-9])\d{1,9}(?:[.,]\d{1,2})?(?![A-Za-z0-9])")

def reread(image,physical_rows,reader,max_rows=3):
    import cv2
    if not callable(reader):
        raise ValueError("Local OCR callback required")
    if not isinstance(physical_rows,list) or len(physical_rows)>24:
        raise ValueError("Invalid source physical rows")
    if not 1<=max_rows<=4:
        raise ValueError("Unbounded row read limit")
    h,w=image.shape[:2]
    before=hashlib.sha256(image.tobytes(order="C")).hexdigest()
    items=[]
    for row in physical_rows[:max_rows]:
        if row.get("posting_eligible") is not False:
            raise ValueError("Unsafe source row")
        variants=row.get("source_variants")
        if not isinstance(variants,list) or not 1<=len(variants)<=2:
            raise ValueError("Source alternatives required")
        observation=variants[0]
        b=observation.get("amount_source_box")
        source_text=observation.get("original_amount")
        if (not isinstance(source_text,str) or len(source_text)>120 or
            not isinstance(b,list) or len(b)!=4 or
            any(type(x)!=int for x in b) or not
            (0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h)):
            raise ValueError("Untrusted amount source cell")
        # Physical source box determines both row and column. Extend to the
        # left for potentially clipped leading digits, and slightly above/
        # below for photographic skew. Nearby rows may enter this crop, so
        # every candidate remains for manual SOURCE-CELL verification.
        bw=b[2]-b[0];bh=b[3]-b[1]
        mx=max(12,min(45,round(bw*1.1)))
        my=max(8,min(23,round(bh*.9)))
        a=max(0,b[0]-mx);top=max(0,b[1]-my)
        c=min(w,b[2]+max(9,round(mx*.45)))
        bottom=min(h,b[3]+my)
        original_crop=image[top:bottom,a:c].copy()
        gray=(cv2.cvtColor(original_crop,cv2.COLOR_BGR2GRAY)
              if original_crop.ndim==3 else original_crop.copy())
        up=cv2.resize(gray,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
        enhanced=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(up)
        observations=[]
        for name,view in (("gray_4x",up),("clahe_4x",enhanced)):
            for psm in (6,7):
                try:
                    raw=reader(view,psm)
                    if not isinstance(raw,str):
                        raise ValueError("OCR engine returned nontext")
                    values=list(dict.fromkeys(_NUMBERS.findall(raw[:300])))[:15]
                    observations.append({
                        "variant":name,"psm":psm,
                        "literal_ocr_text":raw.strip()[:300],
                        "decimal_candidates_unverified":values,
                        "posting_eligible":False})
                except Exception as exc:
                    observations.append({
                        "variant":name,"psm":psm,"status":"RECHECK_UNAVAILABLE",
                        "error_type":type(exc).__name__,
                        "decimal_candidates_unverified":[],
                        "posting_eligible":False})
        items.append({
            "original_amount_ocr":source_text,
            "original_amount_source_box":list(b),
            "temporary_context_crop_original_coordinates":[a,top,c,bottom],
            "alternate_readings":observations,
            "candidate_selected_automatically":False,
            "field_value_certified":False,
            "posting_eligible":False})
    if hashlib.sha256(image.tobytes(order="C")).hexdigest()!=before:
        raise RuntimeError("Original source image pixels changed")
    return {
        "status":"SOURCE_TABLE_AMOUNT_CELL_REREAD_ONLY",
        "source_decoded_pixel_sha256":before,
        "source_item_rows_reviewed":len(items),
        "row_amount_rereads":items,
        "original_source_pixels_modified":False,
        "accepted_amount_values":0,
        "accounting_write_permitted":False,
        "posting_eligible":False,
        "release_approved":False}
