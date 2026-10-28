"""R244: bounded source-region OCR rereads for low-confidence printed tokens.

All rereads are correlated readings from the same local OCR engine, NOT
independent ground truth. Nothing automatically replaces a source token or
authorizes accounting posting.
"""
from __future__ import annotations
import hashlib
import math
import re

HEADER=("level","page_num","block_num","par_num","line_num",
        "word_num","left","top","width","height","conf","text")

def uncertain_tokens(tsv,width,height,max_candidates=5,threshold=75):
    if not isinstance(tsv,str):raise ValueError("Original source OCR TSV missing")
    rows=tsv.splitlines()
    if not rows or tuple(rows[0].split("\t"))!=HEADER:
        raise ValueError("OCR TSV header differs from trusted Tesseract")
    if not (0<width<=30000 and 0<height<=30000 and
            1<=max_candidates<=20 and 0<threshold<=100):
        raise ValueError("Unsafe image or candidate limits")
    ranked=[]
    for lineno,row in enumerate(rows[1:],2):
        if not row.strip():continue
        cols=row.split("\t",11)
        if len(cols)!=12 or cols[0] not in ("1","2","3","4","5"):
            raise ValueError("Invalid source OCR TSV row")
        if cols[0]!="5":continue
        raw=cols[11].strip()
        try:
            x,y,bw,bh=map(int,cols[6:10]);conf=float(cols[10])
        except (ValueError,OverflowError) as e:
            raise ValueError("Invalid source OCR geometry or confidence") from e
        if not math.isfinite(conf):raise ValueError("Nonfinite OCR confidence")
        if conf<0 or not raw:continue
        if not(0<=x<x+bw<=width and 0<=y<y+bh<=height):
            raise ValueError("Source OCR token escaped original image")
        if len(raw)>1500:raise ValueError("Unbounded source text")
        if conf>=threshold or len(raw)<2:continue
        # Prioritize uncertain printed numeric and identifier-like tokens;
        # otherwise use a low-confidence alphabetic token. No specific
        # invoice, vendor, product, date or GSTIN string is hardcoded.
        priority=0 if any(c.isdigit() for c in raw) else 1
        ranked.append((priority,conf,lineno,{
            "raw_source_text":raw,"source_box":[x,y,x+bw,y+bh],
            "original_ocr_reported_confidence":round(conf,2),
            "source_tsv_row_number":lineno,
            "reason":"LOW_CONFIDENCE_SOURCE_TOKEN",
            "source_value_verified":False,"posting_eligible":False
        }))
    ranked.sort(key=lambda q:(q[0],q[1],q[2]))
    return [entry for _,_,_,entry in ranked[:max_candidates]]

def review(image,tsv,reader,*,max_candidates=5):
    import cv2
    if not callable(reader):raise ValueError("Local OCR engine required")
    if not hasattr(image,"shape") or image.ndim not in (2,3):
        raise ValueError("Decoded source image required")
    h,w=image.shape[:2]
    original_hash=hashlib.sha256(image.tobytes(order="C")).hexdigest()
    source=uncertain_tokens(tsv,w,h,max_candidates)
    proposals=[]
    for item in source:
        x0,y0,x1,y1=item["source_box"]
        mx=max(5,min(22,round((x1-x0)*.25)))
        my=max(5,min(15,round((y1-y0)*.55)))
        a=max(0,x0-mx);b=max(0,y0-my)
        c=min(w,x1+mx);d=min(h,y1+my)
        crop=image[b:d,a:c].copy()
        if not crop.size:
            raise ValueError("Unsafe empty source reread crop")
        gray=(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
              if crop.ndim==3 else crop.copy())
        up=cv2.resize(gray,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
        variants={"gray_3x":up,
                  "clahe_3x":cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(up)}
        observations=[]
        for viewname,view in variants.items():
            for psm in (7,6):
                try:
                    text=reader(view,psm)
                    if not isinstance(text,str):raise ValueError("OCR engine returned nontext")
                    observations.append({"variant":viewname,"psm":psm,
                                         "reading":text.strip()[:220],
                                         "source_approval":False})
                except Exception as exc:
                    observations.append({"variant":viewname,"psm":psm,
                                         "status":"RECHECK_UNAVAILABLE",
                                         "error_type":type(exc).__name__,
                                         "source_approval":False})
        proposals.append({**item,
                          "reread_original_source_crop":[a,b,c,d],
                          "reread_observations":observations,
                          "original_source_text_overwritten":False,
                          "field_value_certified":False,
                          "posting_eligible":False})
    if hashlib.sha256(image.tobytes(order="C")).hexdigest()!=original_hash:
        raise RuntimeError("Reread unexpectedly modified decoded source image")
    return {"status":"UNCERTAIN_SOURCE_TOKEN_REREADS_REVIEW_ONLY",
            "decoded_frame_sha256":original_hash,
            "source_tokens_selected":len(proposals),
            "review_items":proposals,
            "original_ocr_text_modified":False,
            "original_pixels_modified":False,
            "accepted_field_values":0,
            "posting_eligible":False,"release_approved":False}
