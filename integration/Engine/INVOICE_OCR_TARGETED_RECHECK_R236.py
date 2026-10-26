"""R236 targeted source-image numeric OCR reread.

A source geometry bound (not arithmetic guessing) determines the candidate
crop. OCR observations can propose alternatives but never rewrite values or
grant accounting permission. An OCR reader is explicitly injected to support
the installed local OCR backend and safe CPU-only tests.
"""
from __future__ import annotations

import hashlib
import re

_NUMERIC = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,2})?\Z")
_QUANTITY = re.compile(r"\b(?:QTY|QUANTITY|PCS|UNITS?)\b", re.I)

def numeric_quantity_candidates(texts, boxes, max_candidates=24):
    if not isinstance(texts,list) or not isinstance(boxes,list) or len(texts)!=len(boxes):
        raise ValueError("Missing original OCR text/geometry")
    headers=[(i,b) for i,(s,b) in enumerate(zip(texts,boxes)) if isinstance(s,str) and _QUANTITY.search(s)]
    result=[]
    for i,(raw,b) in enumerate(zip(texts,boxes)):
        if not isinstance(raw,str) or not _NUMERIC.fullmatch(raw.strip()):continue
        if len(b)!=4 or any(type(n)!=int for n in b) or b[2]<=b[0] or b[3]<=b[1]:
            raise ValueError("Unsafe source coordinates")
        x0,y0,x1,y1=b
        for h, hb in headers:
            hx0,hy0,hx1,hy1=hb
            # Rotated invoice: the OCR line header runs vertically and a
            # small numeric value lies just to its left in source coordinates.
            sideways=(hx0>=x1 and hx0-x1<=max(65,3*(x1-x0)) and
                      min(y1,hy1)-max(y0,hy0)>=.50*(y1-y0))
            # Upright invoice: source number under a short table header.
            # Upright table headings have a horizontal text baseline. A
            # tall rotated heading must never claim later rate/price columns
            # merely because their x-coordinates happen to be nearby.
            upright=((hx1-hx0)>1.15*(hy1-hy0) and
                     y0>=hy1 and y0-hy1<=max(80,5*(y1-y0)) and
                     abs((hx0+hx1)/2-(x0+x1)/2)<=max(32,(hx1-hx0)*.75))
            if sideways or upright:
                result.append({'source_token_index':i,'header_source_token_index':h,
                               'original_ocr_text':raw,'source_box':list(b),
                               'suggested_rotation':'90_CCW' if sideways else '0',
                               'review_only':True})
                break
        if len(result)>=max_candidates:break
    return result

def _rotated(image,box,orientation):
    import cv2
    h,w=image.shape[:2]
    x0,y0,x1,y1=box
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError("Source box outside frame")
    if orientation=='90_CCW':
        return cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE),[y0,w-x1,y1,w-x0]
    if orientation=='90_CW':
        return cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE),[h-y1,x0,h-y0,x1]
    if orientation=='0':return image.copy(),list(box)
    raise ValueError("Unsupported source document orientation")

def reread(image, original_text, source_box, orientation, reader):
    """reader(crop, psm) -> string. Prefer same offline backend as original.

    The reread is always non-authoritative: multiple preprocessing passes from
    one OCR engine are correlated observations, not independent verification.
    """
    import cv2
    if not callable(reader) or not isinstance(original_text,str):
        raise ValueError("Offline OCR callback and original source text required")
    if not hasattr(image,'tobytes') or image.ndim not in (2,3):
        raise ValueError("Source image must be a decoded local frame")
    before=hashlib.sha256(image.tobytes()).hexdigest()
    frame,box=_rotated(image,source_box,orientation)
    x0,y0,x1,y1=box
    bw=x1-x0;bh=y1-y0
    # Tight margins are critical for small invoice numbers. Broad crops draw
    # in neighbouring glyphs/ruling lines and can corrupt '20' into '30'.
    px=max(3,min(9,round(bw*.35)))
    py=max(3,min(13,round(bh*.7)))
    left=max(0,x0-px);right=min(frame.shape[1],x1+px)
    top=max(0,y0-py);bottom=min(frame.shape[0],y1+py)
    if right-left<3 or bottom-top<3:
        raise ValueError("Source region too small to OCR")
    crop=frame[top:bottom,left:right].copy()
    scale=5 if max(crop.shape[:2])<140 else 3
    enhanced=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    views=[('source_rgb',enhanced)]
    if enhanced.ndim==3:
        gray=cv2.cvtColor(enhanced,cv2.COLOR_BGR2GRAY)
        views.append(('gray',gray))
    else:gray=enhanced
    # Do not threshold away faint original print: a low-contrast view is
    # auxiliary OCR evidence only, and the original image remains untouched.
    votes=[]
    for view_name,view in views:
        for psm in (7,8):
            raw=reader(view,psm)
            if not isinstance(raw,str):
                raise ValueError("OCR backend returned nontext")
            value=raw.strip()
            votes.append({'view':view_name,'psm':psm,'reading':value[:100],
                          'valid_number':bool(_NUMERIC.fullmatch(value))})
    readings=[v['reading'] for v in votes if v['valid_number']]
    consensus=readings[0] if len(readings)>=2 and len(set(readings))==1 else None
    if hashlib.sha256(image.tobytes()).hexdigest()!=before:
        raise RuntimeError("Source pixels changed while rereading OCR")
    return {
        'status':'SOURCE_NUMERIC_RECHECK_REVIEW_ONLY',
        'source_image_decoded_sha256':before,
        'original_source_box':list(source_box),
        'original_ocr_text':original_text,
        'rotation_used':orientation,
        'source_crop_in_rotated_coordinates':[left,top,right,bottom],
        'reread_votes':votes,
        'correlated_consensus_candidate':consensus,
        'candidate_disagrees_with_original':bool(consensus and consensus!=original_text),
        'source_image_changed':False,
        'original_ocr_value_replaced':False,
        'accepted_accounting_value':None,
        'field_accuracy_certified':False,
        'posting_eligible':False,'release_approved':False,
    }
