"""R153 — source-only, review-only nearest label-value evidence.

Do NOT interpret a candidate as a verified field. Only cite original OCR
indices and actual source-image geometry; never invent a physical separator or
replace a raw token, silently resolve conflicting readings, or post to Tally.
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path

from r152_unknown_semantic_islands import propose as r152_propose, _box

_DATE = re.compile(r'(?<!\d)(?:\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})(?=(?:\d{1,2}:\d{2}(?::\d{2})?(?:AM|PM)?)?(?!\d))', re.I)
_NUMBER = re.compile(r'^\s*:?[ \t]*(?:(?:rs\.?|inr|₹)[ \t]*)?[-+]?(?:\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?[ \t]*$',re.I)
_ADMIN = re.compile(r'\b(?:gstin|phone|contact|mobile|address|pin\s*code|pincode|state|terms|tax|total|item|product|seller|buyer|invoice|date|signature|authorized|authorised|quantity|rate|order|shipping|consignee)\b',re.I)
_OTHER_LABEL = re.compile(r'\b(?:subtotal|round\s*off|net\s*amt|tax\s*amount|taxable|cgst|sgst|igst|igst|hsn|qty|scheme|discount|credit|savings)\b',re.I)


def _axis_and_cost(ab,bb,w,h):
    """Return spatial proximity on the printed text reading axis.

    No rotation or source image transformation is applied. Vertical readings
    correspond to a sideways photographed page, and require column overlap.
    """
    x0,y0,x1,y1=ab;u0,v0,u1,v1=bb
    aw=x1-x0; ah=y1-y0; bw=u1-u0;bh=v1-v0
    if ah>=aw*1.55:
        gap=v0-y1
        overlap=max(0,min(x1,u1)-max(x0,u0))/min(aw,bw)
        maxgap=min(h*.20,max(45,1.5*ah))
        if -3<=gap<=maxgap and overlap>=.32:
            return 'vertical_downstream',round(max(0,gap)/max(12,ah),4)
        return None
    if aw < ah*.9:  # Ambiguous almost-square orientation: no cross-axis guess.
        return None
    gap=u0-x1
    vertical_overlap=max(0,min(y1,v1)-max(y0,v0))/min(ah,bh)
    if -4<=gap<=min(w*.14,max(36,1.3*aw)) and vertical_overlap>=.40:
        return 'horizontal_right',round(max(0,gap)/max(12,aw),4)
    below_gap=v0-y1
    left_offset=abs(u0-x0)
    # Only genuinely immediate, same-left-margin text below anchor.
    if -2<=below_gap<=min(h*.055,max(18,2.0*ah)) and left_offset<=max(12,1.3*ah):
        return 'horizontal_next_line',round(max(0,below_gap)/max(10,ah)+left_offset/max(12,aw),4)
    return None


def _kind_for_anchor(text,category):
    if category=='totals':return 'total_amount'
    if category in ('buyer','supplier'):return category
    if category=='invoice_meta':
        if re.search(r'\bdate\b',text,re.I):return 'invoice_date'
        if re.search(r'\b(no\.?|number|#)\b',text,re.I):return 'invoice_number'
    return None


def _candidate_syntax(kind,text):
    text=str(text).strip()
    if kind=='total_amount':return bool(_NUMBER.fullmatch(text))
    if kind=='invoice_date':return bool(_DATE.search(text)) and not _OTHER_LABEL.search(text)
    if kind=='invoice_number':
        return (2<=len(text)<=45 and not _DATE.search(text)
          and not re.search(r'\d{1,2}[:.]\d{2}[:.]\d{2}',text)
          and not _ADMIN.search(text) and bool(re.search(r'\d',text)))
    if kind in ('buyer','supplier'):
        return (4<=len(text)<=95 and sum(x.isalpha() for x in text)>=4
                and not _ADMIN.search(text) and not _OTHER_LABEL.search(text)
                and not re.search(r'(?i)^(?:phno|phoneno|telno|mobno|gstno|panno)',text)
                and not _NUMBER.fullmatch(text))
    return False


def associate(case):
    raw=r152_propose(case)
    texts=case.get('raw_texts',[]);boxes=case.get('raw_boxes',[])
    valid={i:_box(box,case['source_width'],case['source_height']) for i,box in enumerate(boxes)}
    source_islands=raw['semantic_islands']
    anchor_ids={j for island in source_islands for j in island['source_indices']}
    proposals=[]
    for island in source_islands:
        i=island['source_indices'][0];label=str(texts[i]);category=island['category']
        kind=_kind_for_anchor(label,category)
        if kind is None:continue
        a=valid[i]
        candidates=[]
        for j,text in enumerate(texts):
            if j==i or j in anchor_ids or valid[j] is None:continue
            if not _candidate_syntax(kind,text):continue
            pos=_axis_and_cost(a,valid[j],case['source_width'],case['source_height'])
            if pos is None:continue
            mode,score=pos
            candidates.append({'source_token_index':j,'raw_value':str(text),
                 'original_box':valid[j],'reading_direction':mode,'proximity':score,
                 'original_ocr_value_unchanged':True,
                 'value_verified':False,'physical_border_verified':False,
                 'posting_eligible':False})
        candidates.sort(key=lambda x:(x['proximity'],x['source_token_index']))
        # We preserve all candidates; even apparent winner gets NO authority.
        proposals.append({'source_anchor_index':i,'source_label':label,
           'source_label_box':a,'category':category,'candidate_field':kind,
           'candidates':candidates,'candidate_count':len(candidates),
           'association_ambiguous':len(candidates)!=1,
           'semantic_leaf_approved':False,'field_value_verified':False,
           'posting_eligible':False})
    # Same OCR token may support multiple labels; conflicts explicitly persist.
    claimed=defaultdict(list)
    for p in proposals:
        for q in p['candidates']:claimed[q['source_token_index']].append(p['source_anchor_index'])
    shared={i:xs for i,xs in claimed.items() if len(xs)>1}
    for p in proposals:
        if any(q['source_token_index'] in shared for q in p['candidates']):p['association_ambiguous']=True
    covered=sorted(set(raw['unclassified_original_indices']) |
                   {i for p in source_islands for i in p['source_indices']} |
                   {x['source_index'] for x in raw['invalid_original_indices']})
    assert covered==list(range(len(texts)))
    return {'file':case['file'],'source_sha256':case['source_sha256'],
       'source_token_count':len(texts),'source_token_membership_preserved':True,
       'original_unknown_parent_retained':True,'source_anchor_count':len(source_islands),
       'field_anchor_count':len(proposals),'proposals':proposals,
       'candidate_mentions':sum(len(x['candidates']) for x in proposals),
       'shared_candidate_conflicts':shared,'approved_field_count':0,
       'printed_physical_boxes_approved':0,'logical_splits_emitted':0,
       'posting_eligible':False,'release_authorized':False}


def audit(report,originals_dir):
    source=report['cases']
    assert len(source)==51
    real=[c for c in source if c.get('kind')=='real']
    assert len(real)==15
    folder=Path(originals_dir)
    output=[]
    for case in real:
        if sha256((folder/case['file']).read_bytes()).hexdigest()!=case['source_sha256']:
            raise ValueError('Source mismatch: '+case['file'])
        output.append(associate(case))
    return {'kind':'R153_READ_ONLY_FIELD_ANCHOR_ASSOCIATION',
      'real_cases':len(output),'all_source_hashes_passed':True,
      'cases':output,'source_token_count':sum(c['source_token_count'] for c in output),
      'field_anchor_count':sum(c['field_anchor_count'] for c in output),
      'candidate_mentions':sum(c['candidate_mentions'] for c in output),
      'cases_with_candidates':sum(c['candidate_mentions']>0 for c in output),
      'field_accuracy_certified':False,'printed_boxes_certified':False,
      'automated_posting':False,'installer_release_approved':False}