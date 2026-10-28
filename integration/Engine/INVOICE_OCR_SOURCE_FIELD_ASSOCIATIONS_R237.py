"""R237 source-bound split-field proposals; never mutate recognized OCR text.

Generic, review-only evidence for: row serial glued to an HSN (eight digits),
tax amounts glued in an OCR run, and a header brand glued to an adjacent
legal company-name line. No invoice/customer/vendor hardcoding.
"""
from __future__ import annotations
import re

_HSN_ROW = re.compile(r'^([1-9])([0-9]{8})\s+(.{6,})$')
_AMOUNT = re.compile(r'[0-9]{1,9}\.[0-9]{2}')
_NAME_ENDING = re.compile(r'\b(?:LTD\.?|LIMITED|ENTERPRISES|INDUSTRIES|DISTRIBUTORS|CORPORATION|LLP)\b',re.I)
_BRAND = re.compile(r'[A-Z][A-Z0-9&.-]{2,18}\Z')


def _item(texts,boxes,i,kind,proposal,source_indices=None,additional=None):
    ids=source_indices if source_indices is not None else [i]
    for j in ids:
        if type(j) is not int or not 0<=j<len(texts):
            raise ValueError('Invalid original source token')
    return {
        'type':kind, 'candidate_text':proposal,
        'source_token_indices':list(ids),
        'original_ocr_texts':[texts[j] for j in ids],
        'source_boxes':[list(boxes[j]) for j in ids],
        'field_value_verified':False,'character_accuracy_certified':False,
        'original_source_changed':False,'accounting_write_permitted':False,
        'posting_eligible':False, 'release_approved':False,
        **(additional or {})
    }


def propose(texts,boxes,width,height):
    if not isinstance(texts,list) or not isinstance(boxes,list) or len(texts)!=len(boxes):
        raise ValueError('Missing source token/box evidence')
    if not (0<int(width)<=30000 and 0<int(height)<=30000):raise ValueError('Bad frame geometry')
    for i,(raw,b) in enumerate(zip(texts,boxes)):
        if (not isinstance(raw,str) or len(raw)>4000 or
            not isinstance(b,list) or len(b)!=4 or any(type(q)!=int for q in b) or
            not 0<=b[0]<b[2]<=width or not 0<=b[1]<b[3]<=height):
            raise ValueError('Invalid source token or rectangle')
    has_hsn_header=any(re.search(r'\bHSN\b',s,re.I) for s in texts)
    has_dual_tax=any(re.search(r'\bCGST\b',s,re.I) for s in texts) and \
                 any(re.search(r'\bSGST\b',s,re.I) for s in texts)
    output=[]
    if has_hsn_header:
        for i,s in enumerate(texts):
            match=_HSN_ROW.match(s.strip())
            if not match:continue
            prefix,code,description=match.groups()
            output.append(_item(texts,boxes,i,'HSN_WITH_ATTACHED_ROW_SERIAL',code,
                 additional={'separable_serial_prefix':prefix,
                             'description_text_same_source_token':description,
                             'source_substring_span':[1,9],
                             'exact_8_digit_code_candidate':True,
                             'hsn_association_requires_physical_cell_review':True}))
    if has_dual_tax:
        for i,s in enumerate(texts):
            value=s.strip()
            spans=list(_AMOUNT.finditer(value))
            if len(spans)!=2 or not (spans[0].start()==0 and
                                     spans[0].end()==spans[1].start() and
                                     spans[1].end()==len(value)):
                continue
            # Both values are literal substrings; no assumed left-to-right
            # CGST/SGST association until physical printed columns verified.
            output.append(_item(texts,boxes,i,'TWO_SOURCE_AMOUNTS_JOINED_BY_OCR',
                 [spans[0].group(),spans[1].group()],
                 additional={'possible_labels':['CGST','SGST'],
                             'field_column_assignment_verified':False,
                             'source_spans':[[m.start(),m.end()] for m in spans]}))
    # Only an upright top-of-page brand followed by a nearby, overlapping
    # company legal name is concatenated. No missing OCR letters invented.
    candidates=[]
    for i,first in enumerate(texts):
        brand=first.strip()
        # A postcode or phone tail is not a logo/brand: otherwise words like
        # TOWN-572103 get spuriously attached to a valid supplier line.
        if (not _BRAND.fullmatch(brand) or
            sum(ch.isdigit() for ch in brand)>2 or
            boxes[i][1]>=height*.35):continue
        fx=(boxes[i][0]+boxes[i][2])/2
        for j,legal in enumerate(texts):
            if i==j or not _NAME_ENDING.search(legal) or boxes[j][1]>=height*.35:continue
            if not(0<=boxes[j][1]-boxes[i][1]<=max(55,.05*height)):continue
            jx=(boxes[j][0]+boxes[j][2])/2
            if abs(fx-jx)>max(85,.1*width):continue
            if len(legal.strip())<12 or len(legal.strip())>150:continue
            candidates.append((i,j,brand+' '+legal.strip()))
    seen=set()
    for i,j,text in candidates:
        if (i,j) in seen:continue
        seen.add((i,j))
        output.append(_item(texts,boxes,i,'HEADER_SUPPLIER_NAME_FRAGMENTS',
                            text,[i,j],{'combined_literal_OCR_substrings_only':True,
                                        'supplier_role_not_certified':True}))
    return {'status':'SOURCE_BOUND_FIELD_ASSOCIATIONS_UNVERIFIED',
            'source_token_count':len(texts),'proposals':output,
            'proposal_count':len(output),'original_ocr_strings_modified':False,
            'original_source_boxes_modified':False,'accepted_field_values':0,
            'accounting_write_permitted':False,'posting_eligible':False,
            'release_approved':False}
