#!/usr/bin/env python3
"""R138: source-linked, review-only OCR evidence fusion; no posting or invented text."""
from __future__ import annotations
import re
from dataclasses import dataclass
from experiments.r148_glued_datetime import read_glued_datetime

@dataclass(frozen=True)
class Token:
    text:str
    index:int
    box:tuple
    engine:str="rapidocr"
    @property
    def cx(self):return (self.box[0]+self.box[2])/2
    @property
    def cy(self):return (self.box[1]+self.box[3])/2
    @property
    def height(self):return self.box[3]-self.box[1]
    @property
    def width(self):return self.box[2]-self.box[0]

def box_of(poly):
    try:
        if hasattr(poly,"tolist"):poly=poly.tolist()
        if len(poly)==4 and isinstance(poly[0],(int,float)):
            x0,y0,x1,y1=map(float,poly)
        else:
            x0=min(float(p[0]) for p in poly);y0=min(float(p[1]) for p in poly)
            x1=max(float(p[0]) for p in poly);y1=max(float(p[1]) for p in poly)
        if 0<=x0<x1 and 0<=y0<y1 and max(x1,y1)<100000:
            return (x0,y0,x1,y1)
    except (IndexError,ValueError,TypeError):pass
    return None

def tokens_from_ocr(texts,boxes,engine="rapidocr"):
    return [Token(str(t).strip(),i,box_of(b),engine)
            for i,(t,b) in enumerate(zip(texts,boxes))
            if str(t).strip() and box_of(b) is not None]

def normalize(s):
    s=re.sub(r"\b(?:ltd\.?|limited)\b","limited",str(s).casefold())
    return ''.join(ch for ch in s if ch.isalnum())

def amount(s):
    s=str(s).strip().replace("₹","").replace("Rs.","").replace(",","").lstrip(": ").strip()
    return round(float(s),2) if re.fullmatch(r"[-+]?\d{1,9}(?:\.\d{1,2})?",s) else None

LABELS={
 "supplier":r"\b(?:from|sold\s*by|supplier\s*name|seller\s*name)\s*:?$",
 "buyer":r"^(?:to|billed\s*to|bill\s*to|buyer|customer\s*name)\s*:?$",
 "consignee":r"^(?:ship\s*to|deliver(?:ed)?\s*to|consignee)\s*:?$",
 "invoice_number":r"\b(?:invoice\s*(?:no|number|#)|inv\s*no|bill\s*(?:no|number))\s*:?$",
 "invoice_date":r"^(?:invoice\s*date|bill\s*date|dated|date)\s*:?$",
 "grand_total":r"\b(?:net\s*payable|grand\s*total|amount\s*payable|total\s*amount|net\s*amount|amount\s*chargeable(?:\s*\(in\s*words\))?)\s*:?$"
}
DATE=re.compile(r"(?<!\d)(\d{1,4}[-/.](?:\d{1,2}|[A-Za-z]{3,9})[-/.]\d{2,4})(?!\d)",re.I)
BAD_AMOUNT=re.compile(r"discount|saving|quantity|\bqty\b|\btax\b|\bgst\b|gross|round\s*off|taxable",re.I)
SIGNATURE=re.compile(r"^(?:for\s+|authori[sz]ed\s+signatory|principal\s+place\s+of\s+business)",re.I)
BAD_VALUE=re.compile(r"\b(?:phone|gstin|state|address|date|total|invoice|involce|recipient)\b",re.I)

def proximity(a,b,width,height):
    dx=b.cx-a.cx;dy=b.cy-a.cy;h=max(10,a.height,b.height)
    if dx>=-.5*h and abs(dy)<=.95*h:return dx/max(1,width)+abs(dy)/h*.06
    if 0<=dy<=1.75*h and abs(dx)<=max(180,.24*width) and b.box[0]>=a.box[0]-.5*h:
        return .22+dy/max(1,height)+abs(dx)/max(1,width)*.3
    return None

def reconstruct(case,engine="rapidocr"):
    tokens=tokens_from_ocr(case.get("raw_texts",[]),case.get("raw_boxes",[]),engine)
    width=case.get("source_width",1);height=case.get("source_height",1)
    proposals={k:[] for k in LABELS}
    for field,pattern in LABELS.items():
        for a in tokens:
            if SIGNATURE.search(a.text):continue
            if field=="grand_total" and BAD_AMOUNT.search(a.text):continue
            if field=="invoice_date" and re.search(r"\b(shipping|delivery|dispatch|due|order)\b",a.text,re.I):continue
            if not re.search(pattern,a.text,re.I):continue
            candidates=[]
            for b in tokens:
                if a.index==b.index:continue
                dist=proximity(a,b,width,height)
                if dist is None:continue
                if field=="grand_total":
                    if amount(b.text) is None or abs(b.cy-a.cy)>max(8,.45*max(a.height,b.height)):continue
                if field=="invoice_date" and not (DATE.search(b.text) or read_glued_datetime(b.text)):continue
                if field=="invoice_number" and (read_glued_datetime(b.text) or re.search(r"\b(date|time|gstin|tax|invoice\s*no|supplier)\b",b.text,re.I)
                    or re.fullmatch(r"\d{1,4}[-/][A-Za-z0-9]{1,3}[-/]\d{2,4}",b.text)):continue
                if field in ("buyer","supplier","consignee"):
                    if SIGNATURE.search(b.text) or BAD_VALUE.search(b.text):continue
                    letters=sum(c.isalpha() for c in b.text)
                    if letters<4 or letters<len(b.text)*.55:continue
                candidates.append((dist,b))
            for dist,b in sorted(candidates,key=lambda pair:pair[0])[:2]:
                proposals[field].append({"value":read_glued_datetime(b.text)["date"] if field=="invoice_date" and read_glued_datetime(b.text) else b.text,"raw_source_value":b.text,"source_tokens":[a.index,b.index],
                                         "distance":round(dist,4),"engine":engine,
                                         "evidence":"NEARBY_LABEL_VALUE_ONLY","verified":False})
    for a in tokens:
        if re.search(r"\b(shipping|delivery|dispatch|due|order)\s*date\b",a.text,re.I):continue
        m=DATE.search(a.text)
        if m and re.search(r"^\s*(?:invoice\s*date|bill\s*date|date|dated)\b",a.text,re.I):
            proposals["invoice_date"].append({"value":m.group(1),"source_tokens":[a.index],
              "engine":engine,"evidence":"LABELED_DATE_FRAGMENT","verified":False})
    # A short uppercase single-word header can sometimes be split from legal name.
    # This is a raw textual hypothesis, not authority about who supplied the invoice.
    proposals["supplier_fragments"]=[]
    upper=[t for t in tokens if t.cy<.35*height and t.width>=24 and not SIGNATURE.search(t.text)]
    for a in upper:
        if not re.fullmatch(r"[A-Z]{3,18}",a.text):continue
        if BAD_VALUE.search(a.text):continue
        for b in upper:
            if b.index==a.index or not 0<b.cy-a.cy<=max(85,3.5*a.height):continue
            if abs(b.cx-a.cx)>max(100,a.width*1.2):continue
            if BAD_VALUE.search(b.text) or not re.search(r"\b(ltd\.?|limited|llp|company|india|enterprises|trading|industries)\b",b.text,re.I):continue
            proposals["supplier_fragments"].append({"value":a.text+" "+b.text,
               "source_tokens":[a.index,b.index],"engine":engine,
               "evidence":"NEARBY_HEADER_FRAGMENT_PAIR","verified":False})
    return {"source_sha256":case.get("source_sha256"),"filename":case.get("file"),
            "fields":proposals,"posting_eligible":False,"field_accuracy_certified":False,
            "physical_boundaries_verified":False}

