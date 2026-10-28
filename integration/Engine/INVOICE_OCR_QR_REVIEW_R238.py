"""R238: source-pixel QR invoice-identifier corroboration for InvoiceVision Child.

An unreadable barcode does NOT invalidate OCR, but a successfully decoded QR
does not by itself certify field identity or authorize posting. Candidate doc
numbers are accepted ONLY when explicitly keyed in decoded JSON. Raw QR
payloads (which may contain personal/accounting information) are never logged,
returned, or written to public research artifacts.
"""
from __future__ import annotations
import hashlib
import json
import re

_KEYS={"docno","invoiceno","invoicenumber","documentnumber","documentno"}
_DOC=re.compile(r"[A-Za-z0-9][A-Za-z0-9/_-]{1,49}\Z")
_MAX_PIXELS=30_000_000
_MAX_PAYLOAD_BYTES=8192

def _explicit_ids(payload):
    if not isinstance(payload,str) or len(payload.encode("utf-8"))>_MAX_PAYLOAD_BYTES:
        return []
    try:
        tree=json.loads(payload)
    except (ValueError,TypeError):
        return []
    result=[]
    def visit(node,depth=0):
        if depth>3 or len(result)>20:return
        if isinstance(node,dict):
            for key,value in list(node.items())[:60]:
                if not isinstance(key,str):continue
                name=re.sub(r"[^a-z0-9]","",key.casefold())
                if name in _KEYS and isinstance(value,(str,int)) and type(value) is not bool:
                    candidate=str(value).strip()
                    if _DOC.fullmatch(candidate):
                        result.append(candidate)
                elif isinstance(value,(dict,list)):
                    visit(value,depth+1)
        elif isinstance(node,list):
            for element in node[:20]:
                if isinstance(element,(dict,list)):visit(element,depth+1)
    visit(tree)
    return sorted(set(result))

def _result(decoded,source_sha256,review_boxes=None):
    if not decoded:
        return {
            "status":"SOURCE_QR_UNREADABLE_REVIEW_REQUIRED",
            "source_frame_sha256":source_sha256,
            "qr_found":bool(review_boxes),
            "qr_payload_sha256":None,
            "qr_invoice_id_candidates":[],
            "original_photo_sha256_verified":False,
            "source_text_modified":False,
            "invoice_number_certified":False,
            "posting_eligible":False,
            "release_approved":False,
        }
    payloads=sorted(set(decoded))
    candidates=sorted(set(value for payload in payloads for value in _explicit_ids(payload)))
    status=("SOURCE_QR_INVOICE_CANDIDATE_UNVERIFIED" if len(candidates)==1 else
            "SOURCE_QR_MULTIPLE_IDS_REVIEW_REQUIRED" if len(candidates)>1 else
            "SOURCE_QR_DECODED_NO_EXPLICIT_INVOICE_ID")
    return {
        "status":status,
        "source_frame_sha256":source_sha256,
        "qr_found":True,
        # Preserve only hashes of possibly sensitive QR payloads.
        "qr_payload_sha256":[hashlib.sha256(p.encode("utf-8")).hexdigest() for p in payloads],
        "qr_invoice_id_candidates":candidates,
        "source_evidence_contains_identifiers":bool(candidates),
        "original_photo_sha256_verified":False,
        "source_text_modified":False,
        "invoice_number_certified":False,
        "accounting_write_permitted":False,
        "posting_eligible":False,
        "release_approved":False,
    }

def review(image):
    """Decode bounded source-image views, without uploading or modifying pixels."""
    import cv2
    if not hasattr(image,"shape") or len(image.shape) not in (2,3):
        raise ValueError("Missing decoded source frame")
    h,w=image.shape[:2]
    if not (80<=w<=6000 and 80<=h<=6000 and h*w<=_MAX_PIXELS):
        raise ValueError("Source frame dimensions outside QR review bounds")
    frame_sha=hashlib.sha256(image.tobytes(order="C")).hexdigest()
    # A tax invoice's QR is usually in the upper-right; use a wide ROI that
    # does not require supplier-specific geometry. The entire-source view is
    # checked once for other layouts. Use bounded scans (not an endless search).
    detector=cv2.QRCodeDetector()
    x0,y0,x1,y1=int(.53*w),int(.03*h),int(.98*w),int(.46*h)
    roi=image[y0:y1,x0:x1]
    views=[("full",image),("upper_right",roi)]
    if max(roi.shape[:2])<=1800:
        views.append(("upper_right_2x",
                      cv2.resize(roi,None,fx=2,fy=2,
                                 interpolation=cv2.INTER_CUBIC)))
    decoded=[];detected=False
    for name,view in views:
        try:
            raw,corners,_=detector.detectAndDecode(view)
            if corners is not None:detected=True
            if isinstance(raw,str) and raw.strip():decoded.append(raw)
        except cv2.error:
            continue
    if hashlib.sha256(image.tobytes(order="C")).hexdigest()!=frame_sha:
        raise RuntimeError("QR review mutated original image")
    return _result(decoded,frame_sha,detected)
