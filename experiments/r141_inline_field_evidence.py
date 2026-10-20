"""R141 source-backed same-line OCR label/value candidate recovery.

Recognize text actually returned by OCR, never fill missing characters,
guess fields from vendor dictionaries, or post unverified invoice values.
"""
from __future__ import annotations
import re

LABELS={
 'supplier':[r'from',r'sold\s+by',r'supplier(?:\s+name)?',r'seller(?:\s+name)?',r'bill\s+from'],
 'buyer':[r'bill(?:ed)?\s+to',r'buyer(?:\s+name)?',r'customer\s+name',r'to'],
 'consignee':[r'ship\s+to',r'deliver(?:ed)?\s+to',r'consignee'],
 'invoice_number':[r'invoice\s*(?:no\.?|number|#)',r'inv\s*(?:no\.?|#)',r'bill\s*(?:no\.?|number|#)'],
 'invoice_date':[r'invoice\s*date',r'bill\s*date',r'dated',r'date'],
 'grand_total':[r'grand\s*total',r'net\s*payable',r'amount\s*payable',r'total\s*amount',r'net\s*amount',r'amount\s*chargeable',r'total'],
}
DATE=re.compile(r'(?<!\d)(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.][A-Za-z]{3,9}[-/.]\d{4})(?!\d)',re.I)
AMOUNT=re.compile(r'^\s*(?:₹|Rs\.?|INR)?\s*[-+]?\s*\d[\d,]*(?:\.\d{1,2})?\s*$',re.I)
EXCLUDE=re.compile(r'\b(?:tax|taxable|gst|igst|cgst|sgst|discount|round(?:ing)?\s*off|savings|quantity|qty|subtotal|gross)\b',re.I)
PREFIX={k:[re.compile(r'^\s*(?:'+label+r')\s*(?:[:#=\-]\s*|\s+)(\S.*)\s*$',re.I)
            for label in patterns] for k,patterns in LABELS.items()}

def parse_inline(line):
    """Raw OCR text hypotheses, not a model of invoice truth or layout."""
    text=str(line).strip();out=[]
    if not text:return out
    # Multiple explicitly delimited fields may share one OCR line. Split only
    # at printed labels, retaining the complete original line as evidence.
    labels=sorted({label for values in LABELS.values() for label in values} |
                  {r'(?:C[. ]*N|credit\s+note|(?:DL[.]?|FSSAI)\s+exp|exp(?:iry)?|due|order|delivery|shipping)\s+date'},key=len,reverse=True)
    boundary=re.compile(r'(?<!\S)(?:'+ '|'.join(labels)+r')\s*[:#=]\s*',re.I)
    markers=list(boundary.finditer(text))
    if len(markers)>1 and markers[0].start()==0:
        for index,marker in enumerate(markers):
            end=markers[index+1].start() if index+1<len(markers) else len(text)
            for row in parse_inline(text[marker.start():end].strip()):
                row['source_line']=text
                row['evidence']='SOURCE_INLINE_MULTIPLE_EXPLICIT_LABELS'
                out.append(row)
        return out
    for field,patterns in PREFIX.items():
        for pattern in patterns:
            match=pattern.match(text)
            if not match:continue
            value=match.group(1).strip(' :-#=')
            if not value:continue
            if field=='invoice_date':
                date=DATE.search(value)
                if date is None:continue
                value=date.group(0)
            elif field=='grand_total':
                if EXCLUDE.search(text) or not AMOUNT.fullmatch(value):continue
            elif field=='invoice_number':
                if DATE.search(value) or len(value)>55 or re.search(r'\b(?:total|gstin|tax|date)\b',value,re.I):continue
            elif field in ('supplier','buyer','consignee'):
                if EXCLUDE.search(value) or re.search(r'\b(?:tax\s*invoice|date|gstin|state|phone|mobile|total|authorized|signature|address|pin\s*code)\b',value,re.I):continue
                if re.fullmatch(r'\W*(?:bill(?:ed)?\s*to|ship\s*to|buyer|supplier)\W*',value,re.I):continue
                if sum(c.isalpha() for c in value)<3:continue
            out.append({'field':field,'raw_value':value,'source_line':text,
                'evidence':'SOURCE_INLINE_OCR_LABEL_AND_VALUE',
                'validated_against_pixels':False,'posting_eligible':False})
            break
    return out

def inspect_case(case,engine):
    rows=[]
    for i,text in enumerate(case.get('raw_texts',[])):
        for candidate in parse_inline(text):
            candidate.update({'engine':engine,'source_index':i,
                              'source_sha256':case.get('source_sha256')})
            rows.append(candidate)
    return {'file':case.get('file'),'source_sha256':case.get('source_sha256'),
            'proposals':rows,'field_accuracy_verified':False,'posting_eligible':False}

