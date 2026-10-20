"""InvoiceVision R152: source-token semantic anchors inside unknown zones.

Research-only. The output is an INDEX of original OCR tokens, not new physical
rectangles or approved buyer/supplier/invoice fields. Source JSON is not changed.
"""
from __future__ import annotations
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

ANCHORS = {
    'supplier': (
        r'(?:supplier|supplier name|seller|seller name|sold by|bill from|supplier details)',
    ),
    'buyer': (
        r'(?:billed to|bill to|buyer|buyer name|customer name|customer details|recipient name)',
    ),
    'invoice_meta': (
        r'(?:invoice no\.?|invoice number|bill no\.?|bill number|invoice date|bill date|tax invoice no\.?|invoice #)',
    ),
    'totals': (
        r'(?:grand total|net payable|total amount payable|amount payable|amount chargeable|invoice total|net amount|net total)',
    ),
    'tax': (
        r'(?:taxable value|tax summary|total gst|total cgst|total sgst|total igst|cgst|sgst|igst|gst summary)',
    ),
    'item_table': (
        r'(?:description of goods|item description|description of items|hsn/sac|hsn code|quantity|qty\.?|unit price|item name|product name|rate per unit)',
    ),
    'terms': (
        r'(?:terms & conditions|terms and conditions|payment terms)',
    ),
}
# Strict beginnings ensure a product description mentioning a label later in
# its text does not become a semantic anchor. Inline values remain in raw text.
PATTERNS = {k: [re.compile(r'^\s*(?:'+v+r')(?:\s*[:=#\-]\s*.*|\s*$)', re.I)
                for v in vs] for k,vs in ANCHORS.items()}
GENERIC = { 'tax', 'total', 'date', 'amount', 'name', 'rate', 'buyer address', 'ship to', 'customer address' }


def anchors_for_text(text):
    """Return a role only with unique, source-visible label evidence."""
    t=str(text).strip()
    if not t or t.lower() in GENERIC:
        return []
    matched=[category for category,patterns in PATTERNS.items() if any(p.match(t) for p in patterns)]
    return matched if len(matched)==1 else []


def _box(box, width, height):
    try:
        if len(box)==4 and isinstance(box[0],(int,float)):
            a=list(map(float,box));x0,y0,x1,y1=a
        elif len(box)>=4 and isinstance(box[0],(list,tuple)):
            xs=[float(p[0]) for p in box];ys=[float(p[1]) for p in box]
            x0,y0,x1,y1=min(xs),min(ys),max(xs),max(ys)
        else: return None
        import math
        if all(map(math.isfinite,[x0,y0,x1,y1])) and 0<=x0<x1<=width and 0<=y0<y1<=height:
            return [x0,y0,x1,y1]
    except (TypeError,ValueError,OverflowError,IndexError): pass
    return None


def propose(case):
    """Preserve every original OCR token as exactly one anchor or residual.

    Never uses the reference answer, never invents a zone boundary, never posts.
    Anchor candidates may overlap visually, but not by token index.
    """
    src=case['source_sha256'];w=case['source_width'];h=case['source_height']
    lines=case.get('raw_texts',[]); boxes=case.get('raw_boxes',[])
    if len(lines)!=len(boxes):raise ValueError('OCR text/geometry count mismatch')
    categories=Counter(); groups=[];residual=[];invalid=[]
    for i,(text,rawbox) in enumerate(zip(lines,boxes)):
        box=_box(rawbox,w,h)
        if box is None:
            invalid.append({'source_index':i,'raw_text':str(text),'raw_box':rawbox})
            continue
        options=anchors_for_text(text)
        if options:
            category=options[0]
            groups.append({'category':category, 'source_indices':[i],
                           'raw_text':[str(text)],'source_boxes':[box],
                           'evidence':'EXACT_SOURCE_OCR_LABEL_PATTERN',
                           'field_value_verified':False,
                           'physical_border_verified':False,
                           'posting_eligible':False})
            categories[category]+=1
        else:
            residual.append(i)
    covered=[k for group in groups for k in group['source_indices']]+residual+[x['source_index'] for x in invalid]
    if sorted(covered)!=list(range(len(lines))):
        raise AssertionError('Source tokens double-assigned or lost')
    return {'file':case['file'],'source_sha256':src,'source_width':w,'source_height':h,
        'source_token_count':len(lines),'anchor_count':len(groups),
        'categories':dict(categories),'semantic_islands':groups,
        'unclassified_original_indices':residual,'invalid_original_indices':invalid,
        'source_token_membership_loss':0,'source_token_membership_duplicates':0,
        'parent_zone_remains_unknown':True,'zones_split':False,
        'printed_border_verified':False,'field_accuracy_verified':False,
        'posting_eligible':False,'release_authorized':False}


def audit_corpus(report, originals_dir=None):
    src=report.get('cases', [])
    if len(src)!=51 or Counter(c.get('kind') for c in src)!=Counter({'real':15,'synthetic':36}):
        raise ValueError('Expect verified 51-source / 15-real / 36-synthetic corpus')
    if len({(c.get('kind'),c.get('file')) for c in src})!=len(src):
        raise ValueError('Repeated source entry, cannot silently collapse invoice identities')
    if originals_dir is not None:
        originals_dir=Path(originals_dir)
        for c in src:
            if c.get('kind')=='real':
                p=originals_dir / c['file']
                if not p.is_file() or sha256(p.read_bytes()).hexdigest()!=c['source_sha256']:
                    raise ValueError('Original photo does not match original OCR provenance: '+c['file'])
    cases=[propose(c) for c in src if c.get('kind')=='real']
    if len(cases)!=15 or len({c['file'] for c in cases})!=15:
        raise ValueError('Expected 15 distinct real source cases')
    return {'kind':'R152_SOURCE_SEMANTIC_ISLANDS_NOT_PHYSICAL_ZONES',
       'cases':cases,'real_photos':len(cases),
       'original_unknown_only':sum(all(z['category']=='unknown' for z in c['leaves'])
            for c in src if c.get('kind')=='real'),
       'verified_against_original_photo_bytes':originals_dir is not None,
       'photos_with_source_label_anchors':sum(c['anchor_count']>0 for c in cases),
       'total_source_anchored_tokens':sum(c['anchor_count'] for c in cases),
       'all_original_raw_ocr_tokens_preserved':True,'source_pixels_modified':False,
       'unknown_parent_replaced':False,'physical_zones_verified':False,
       'field_accuracy_verified':False,'release_authorized':False}