"""R229 source-locked orientation and HSN row recovery. REVIEW ONLY.

Neither source OCR text/boxes nor image bytes are modified. No numerical
characters, physical cells or monetary values are certified or posted.
"""
from __future__ import annotations

import hashlib
import re

HSN = re.compile(r'^\d{6,10}$')
HEADER_OTHER = {'hsn','description','serial','quantity','rate','amount'}

def _center(b):
    return ((b[0]+b[2])/2, (b[1]+b[3])/2)

def _rotated_case(case):
    w=case['source_width'];h=case['source_height']
    return {**case,'source_width':h,'source_height':w,
            'raw_boxes':[[b[1],w-b[2],b[3],w-b[0]] for b in case['raw_boxes']}

def _strong_sideways_evidence(case,r223):
    candidates=[]
    for i,(s,b) in enumerate(zip(case['raw_texts'],case['raw_boxes'])):
        role=r223._role(s)
        if role in HEADER_OTHER and b[3]-b[1]>1.7*(b[2]-b[0]):
            candidates.append((i,role,_center(b)[0]))
    for _,role,x in candidates:
        cluster=[(i,r) for i,r,cx in candidates
                 if abs(cx-x)<=max(28,.035*case['source_width'])]
        if len({r for i,r in cluster})>=3 and any(r=='description' for i,r in cluster):
            return True
    return False

def _remap_orientation(table,case):
    def replace_token(token):
        idx=token.get('source_token_index',token.get('source_index'))
        if idx is not None:
            old=token.get('original_box',token.get('source_box'))
            if old is not None:token['logical_orientation_box']=old
            if 'original_box' in token:token['original_box']=list(case['raw_boxes'][idx])
            if 'source_box' in token:token['source_box']=list(case['raw_boxes'][idx])
    for hdr in table.get('headers',[]):replace_token(hdr)
    for row in table.get('rows',[]):
        replace_token(row)
        for tok in row.get('original_tokens',[]):replace_token(tok)
    table['source_original_boxes_preserved']=True
    table['geometry_used_for_grouping']='ROTATED_90_CCW_LOGICAL_VIEW_ONLY'
    table['physical_cell_truth_verified']=False
    return table

def _hsn_rows(case,r223,already):
    texts=case['raw_texts'];boxes=case['raw_boxes']
    w=case['source_width'];h=case['source_height']
    roles=[r223._role(t) for t in texts]
    headers=[]
    for i,role in enumerate(roles):
        if role!='hsn':continue
        hx,hy=_center(boxes[i])
        near=[(j,r) for j,r in enumerate(roles) if j!=i and r in HEADER_OTHER
              and r!='hsn' and abs(_center(boxes[j])[1]-hy)<=max(28,.030*h)]
        if len({r for j,r in near})>=2:headers.append((i,near))
    if not headers:return []
    output=[];used=set(already)
    for hi,near in headers:
        hx,hy=_center(boxes[hi])
        desc_headers=[j for j,r in near if r=='description']
        desc_x=_center(boxes[desc_headers[0]])[0] if desc_headers else None
        for i,t in enumerate(texts):
            x,y=_center(boxes[i])
            if (not HSN.fullmatch(t.strip()) or i in used or y<=hy+2
                or y>hy+max(100,.14*h) or abs(x-hx)>max(25,.045*w)):
                continue
            opts=[]
            for j,t2 in enumerate(texts):
                xx,yy=_center(boxes[j])
                if j==i or j in used or roles[j] in HEADER_OTHER:continue
                letters=''.join(ch for ch in t2 if ch.isalpha())
                if len(letters)<9 or not(y-max(15,.010*h)<=yy<=y+max(15,.010*h)):
                    continue
                if re.match(r'(?i)^(total|gross|tax|round|amount|output|sub|grand|invoice|gst|rupees|less)\b',t2.strip()):
                    continue
                if desc_x is None:
                    if xx>=hx-24 or hx-xx>.45*w:continue
                    dist=hx-xx
                else:
                    if abs(xx-desc_x)>max(43,.09*w):continue
                    dist=abs(xx-desc_x)
                opts.append((abs(y-yy)+.15*dist,j))
            if not opts:continue
            opts.sort();best=opts[0][1]
            if best in used:continue
            output.append({'hsn_source_token_index':i,
                           'description_source_token_index':best,
                           'source_indices':[best,i],
                           'raw_source_texts':[texts[best],texts[i]],
                           'source_boxes':[list(boxes[best]),list(boxes[i])],
                           'table_header_source_index':hi,
                           'review_status':'HSN_AND_DESCRIPTION_GEOMETRY_ONLY',
                           'actual_cell_boundaries_verified':False,
                           'all_characters_verified':False,'posting_eligible':False})
            used.update((best,i))
    out=[];seen=set()
    for row in output:
        i=row['hsn_source_token_index']
        if i not in seen:out.append(row);seen.add(i)
    return out

def propose(case,source_bytes,r223):
    """Require original bytes or exact decoded-frame SHA before proposals."""
    if hashlib.sha256(source_bytes).hexdigest()!=case['source_sha256']:
        raise ValueError('Source image or decoded frame hash mismatch')
    baseline=r223.propose(case,source_bytes)
    orientation='ORIGINAL_COORDINATES';tables=[]
    if _strong_sideways_evidence(case,r223) and baseline['proposed_row_count']==0:
        candidate=r223.propose(_rotated_case(case),source_bytes)
        if candidate['proposed_row_count']:
            orientation='ROTATED_90_CCW_LOGICAL_VIEW_ONLY'
            tables=[_remap_orientation(t,case) for t in candidate['tables']]
    merged=[];trusted=[]
    for table in baseline['tables']:
        for row in table['rows']:
            hsns=[i for i in row['source_indices']
                  if HSN.fullmatch(case['raw_texts'][i].strip())]
            descriptions=[i for i in row['source_indices']
                if r223._role(case['raw_texts'][i]) is None
                and len(''.join(ch for ch in case['raw_texts'][i] if ch.isalpha()))>=8
                and not re.match(r'(?i)^(invoice|buyer|tax|gross|total|amount|gst|round|discount)',case['raw_texts'][i])]
            ys=sorted(_center(case['raw_boxes'][i])[1] for i in descriptions)
            separated=bool(ys and ys[-1]-ys[0]>=max(7,.003*case['source_height']))
            if len(hsns)>=2 and len(descriptions)>=2 and separated:
                merged.append({'description_anchor_source_index':row['description_anchor_source_index'],
                               'source_indices':list(row['source_indices']),
                               'hsn_source_indices':hsns,
                               'status':'MULTIPLE_HSN_TOKENS_IN_ONE_UNCERTAIN_ROW',
                               'physical_row_truth_verified':False})
            else:
                trusted.extend(row['source_indices'])
    used=trusted+[i for t in tables for row in t['rows'] for i in row['source_indices']]
    more=_hsn_rows(case,r223,used) if not tables else []
    effective=baseline['proposed_row_count']-len(merged)
    return {'source_sha256':case['source_sha256'],
            'raw_observation_count':len(case['raw_texts']),
            'baseline_item_rows':baseline['proposed_row_count'],
            'baseline_merged_row_warnings':merged,
            'baseline_unmerged_row_count':effective,
            'orientation':orientation,'orientation_tables':tables,
            'sideways_additional_rows':sum(len(t['rows']) for t in tables),
            'hsn_anchor_rows':more,'hsn_additional_rows':len(more),
            'total_provisional_rows':effective+sum(len(t['rows']) for t in tables)+len(more),
            'original_ocr_text_changed':False,'original_source_boxes_changed':False,
            'physical_cells_verified':0,'accepted_field_values':0,
            'posting_eligible':False,'release_approved':False}
