"""R140 source-linked accounting-critical OCR disagreement triage.

A disagreement is only a review hypothesis. Neither model agreement nor a
detected numeric token approves fields, printed boxes, or accounting posting.
"""
from __future__ import annotations
import re
from collections import Counter

DATE = re.compile(r"(?<!\\d)(?:\\d{1,2}[-/.]\\d{1,2}[-/.]\\d{4}|\\d{4}[-/.]\\d{1,2}[-/.]\\d{1,2})(?!\\d)")
NUMERIC = re.compile(r"^\\s*(?:(?:₹|rs\\.?|inr)\\s*)?([+-]?\\d{1,9}(?:,\\d{2,3})*(?:\\.\\d{1,3})?)\\s*$", re.I)

def box_of(v):
    try:
        if len(v)==4 and isinstance(v[0],(int,float)):
            x0,y0,x1,y1=map(float,v)
        else:
            x0=min(float(p[0]) for p in v)
            y0=min(float(p[1]) for p in v)
            x1=max(float(p[0]) for p in v)
            y1=max(float(p[1]) for p in v)
        if 0<=x0<x1 and 0<=y0<y1 and max(x1,y1)<100000:
            return x0,y0,x1,y1
    except (TypeError,ValueError,IndexError):pass
    return None

def intersect_over_union(a,b):
    area=lambda x:(x[2]-x[0])*(x[3]-x[1])
    it=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return it/max(1,area(a)+area(b)-it)

def tokens(case):
    return [{"id":i,"text":str(t),"box":b}
            for i,(t,v) in enumerate(zip(case.get("raw_texts",[]),case.get("raw_boxes",[])))
            if (b:=box_of(v)) and str(t).strip()]

def align(rapid,paddle,threshold=.36):
    matches=[]
    for a in rapid:
        for b in paddle:
            score=intersect_over_union(a["box"],b["box"])
            if score>=threshold:matches.append((score,a,b))
    matches.sort(key=lambda t:-t[0])
    seen_r=set();seen_p=set();selected=[]
    for score,a,b in matches:
        if a["id"] in seen_r or b["id"] in seen_p:continue
        seen_r.add(a["id"]);seen_p.add(b["id"])
        selected.append((a,b,round(score,4)))
    return selected

def digits(t):return "".join(ch for ch in str(t) if ch.isdigit())

def classify(a,b):
    x,y=str(a).strip(),str(b).strip()
    if digits(x)==digits(y):return "NO_DIGIT_DISAGREEMENT"
    if DATE.fullmatch(x) or DATE.fullmatch(y):return "DATE_SHAPED_CONFLICT"
    if NUMERIC.fullmatch(x) and NUMERIC.fullmatch(y):
        if re.search(r"[.,₹]|\\brs\\b|\\binr\\b",x+" "+y,re.I):
            return "DECIMAL_OR_CURRENCY_SHAPED_CONFLICT"
        return "BARE_NUMERIC_TOKEN_CONFLICT_UNCLASSIFIED"
    if re.search(r"[A-Za-z]",x+y):return "MIXED_TEXT_OR_IDENTIFIER_DIGIT_CONFLICT"
    return "PARTIAL_NUMERIC_OCR_CONFLICT"

def analyze(rapid,paddle):
    if not rapid.get("source_sha256") or rapid["source_sha256"] != paddle.get("source_sha256"):
        raise ValueError("Input photo hash mismatch: no cross-source OCR comparison")
    conflicts=[]
    for a,b,iou in align(tokens(rapid),tokens(paddle)):
        status=classify(a["text"],b["text"])
        if status=="NO_DIGIT_DISAGREEMENT":continue
        conflicts.append({"rapid_id":a["id"],"paddle_id":b["id"],
             "rapid_text":a["text"],"paddle_text":b["text"],
             "source_box_envelope":a["box"],"source_envelope_iou":iou,
             "classification":status,"field_mapping_verified":False,
             "transcription_verified":False,"physical_border_verified":False,
             "posting_eligible":False})
    return {"file":rapid.get("file"),"source_sha256":rapid["source_sha256"],
        "conflicts":conflicts,"counts":dict(Counter(x["classification"] for x in conflicts)),
        "source_readback_approved":False,"automatic_posting_enabled":False,
        "no_model_value_override":True}
