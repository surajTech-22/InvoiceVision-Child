"""R243 independent high-resolution OCR evidence with correct original-source boxes.

New text is *alternate OCR evidence*, never a replacement or verified invoice
field. 2x scaling is reversed on every bounding rectangle, and all original
pixels and first-pass source TSV remain immutable.
"""
from __future__ import annotations
import hashlib
import math
import re

HEADER="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
_SAFE_VARIANTS=("gray_2x","clahe_2x")
def views(image):
    import cv2
    if not hasattr(image,"shape") or len(image.shape) not in (2,3):
        raise ValueError("Missing decoded image")
    h,w=image.shape[:2]
    if not 100<=h<=10000 or not 100<=w<=10000 or h*w>26000000:
        raise ValueError("Source exceeds bounded high resolution OCR")
    gray=(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
          if len(image.shape)==3 else image.copy())
    up=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    return {"gray_2x":up,
            "clahe_2x":cv2.createCLAHE(clipLimit=2.2,tileGridSize=(12,12)).apply(up)}

def source_words(tsv,width,height,scale=2):
    if not isinstance(tsv,str) or not tsv.startswith(HEADER+"\n"):
        raise ValueError("OCR TSV header invalid")
    if type(scale) is not int or scale<1 or scale>4:
        raise ValueError("Scale out of bounds")
    words=[]
    for row_id,row in enumerate(tsv.splitlines()[1:],2):
        if not row.strip(): continue
        a=row.split("\t",11)
        if len(a)!=12 or a[0] not in ('1','2','3','4','5'):
            raise ValueError("TSV hierarchy invalid at row "+str(row_id))
        if a[0]!='5':continue
        try:
            x,y,bw,bh=(int(a[i]) for i in (6,7,8,9))
            confidence=float(a[10])
        except (ValueError,OverflowError) as err:
            raise ValueError("TSV source coordinate invalid") from err
        if not math.isfinite(confidence) or confidence < -1 or confidence>100:
            raise ValueError("Nonfinite confidence")
        raw=a[11].strip()
        if not raw or confidence<0:continue
        if x<0 or y<0 or bw<=0 or bh<=0:
            raise ValueError("Negative OCR region")
        l=max(0,math.floor(x/scale));t=max(0,math.floor(y/scale))
        r=min(width,math.ceil((x+bw)/scale))
        b=min(height,math.ceil((y+bh)/scale))
        if x+bw>width*scale or y+bh>height*scale or l>=r or t>=b:
            raise ValueError("OCR rectangle outside original source")
        if len(raw)>1500:raise ValueError("Oversized OCR evidence token")
        words.append({"original_source_box":[l,t,r,b],
                      "original_source_text":raw,
                      "ocr_confidence_reported":round(confidence,1),
                      "source_tsv_row_number":row_id,
                      "field_value_verified":False,
                      "posting_eligible":False})
        if len(words)>8000:raise ValueError("Excessive OCR words")
    return words

def review(image,reader,*,max_words=500):
    """reader(image,psm)->Tesseract TSV. Source 2x OCR never becomes approved."""
    if not callable(reader):raise ValueError("Offline reader required")
    before=hashlib.sha256(image.tobytes()).hexdigest()
    h,w=image.shape[:2]
    candidates=[]
    for name,img in views(image).items():
        try:
            raw=reader(img,11)
            words=source_words(raw,w,h,scale=2)
            candidates.append({"variant":name,
                               "source_ocr_words_total":len(words),
                               "source_words":words[:max_words],
                               "source_boxes_are_original_pixels":True,
                               "source_text_not_replaced":True,
                               "field_values_verified":0,
                               "posting_eligible":False})
        except Exception as exc:
            candidates.append({"variant":name,"status":"REVIEW_UNAVAILABLE",
                               "error_type":type(exc).__name__,
                               "source_words":[],"posting_eligible":False})
    if hashlib.sha256(image.tobytes()).hexdigest()!=before:
        raise RuntimeError("Preprocessing changed decoded original photo pixels")
    return {"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
            "source_decoded_pixel_sha256":before,
            "scale_factors":[2,2],
            "variants":candidates,
            "source_original_pixels_unchanged":True,
            "original_OCR_text_overwritten":False,
            "accepted_field_values":0,
            "posting_eligible":False,
            "release_approved":False}
