"""R223 source-bound printed item-table row hypotheses (no OCR edits or posting).

This is NOT a physical-cell or field accuracy certification. Every proposed cell
cites unmodified source OCR indices and bounding rectangles. Fold perspective,
merged OCR tokens, headers and tax summaries remain explicitly uncertain.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter


def _norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())


def _role(s):
    n = _norm(s)
    if n in {'products','product','productname','produciname','productdescription','itemdescription',
             'itemname','itenname','descriptionofgoods','itemdeseription',
             'desorptionofcoods','descriptionofcoods'}:
        return 'description'
    if n in {'hsn','hsncode','hsncoda','hsnsac','hsnno','hisnsac','hsnsacgsy'}:
        return 'hsn'
    if n in {'sno','sn','srno','srna','slno','snoandkind','snokind','sl'}:
        return 'serial'
    if n in {'quantity','qnantity','qty','pcs','case','qtypcs','weightkg','auanlity'}:
        return 'quantity'
    if n in {'rate','basicrate','unitrate','price','netprice','mrp','rpu','rato'}:
        return 'rate'
    if n in {'amount','netamt','netamount','taxable','taxableamt',
             'totalvalueincoftaxrs','gross','grossamt','grossamount'}:
        return 'amount'
    if n in {'cgst','sgst','sgstutgst','igst','gst','gstpercent','scheme','discount',
             'schdis','schdispercent','grossdisc'}:
        return 'tax_or_discount'
    return None


def _rect(b,w,h):
    if not isinstance(b,(list,tuple)) or len(b)!=4:
        raise ValueError('Invalid original OCR rectangle shape')
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in b):
        raise ValueError('Invalid original OCR rectangle coordinate')
    if not (0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h):
        raise ValueError('Original OCR rectangle outside photograph')
    return tuple(b)


def _cx(b):return (b[0]+b[2])/2

def _cy(b):return (b[1]+b[3])/2


def _slope(anchors):
    """Robust-ish heading baseline; never a transformation of source boxes."""
    if len(anchors)<2:return 0.0
    pairs=[]
    for i,a in enumerate(anchors):
        for b in anchors[i+1:]:
            dx=_cx(a['box'])-_cx(b['box'])
            if abs(dx)>70:
                s=(_cy(a['box'])-_cy(b['box']))/dx
                if abs(s)<=.075:
                    pairs.append(s)
    if not pairs:return 0.0
    pairs.sort()
    return pairs[len(pairs)//2]


def _is_item_description(t):
    n=_norm(t)
    if len(n)<5 or sum(ch.isalpha() for ch in n)<4:return False
    blockers=('total','taxable','cgst','sgst','igst','rupees','invoice','taxamount',
              'noofitems','nooftems','numberofitems','noofpieces',
              'amountinwords','roundoff','freight','discount','gst',
              'hsn','sac','grandtotal','subtotal','roundo','schamt')
    if any(n.startswith(k) for k in blockers):return False
    return True


def propose(case, original_bytes):
    """Produce strict review-only product rows, no fabricated logical cells."""
    if hashlib.sha256(original_bytes).hexdigest()!=case['source_sha256']:
        raise ValueError('Original invoice SHA-256 mismatch')
    w=case['source_width'];h=case['source_height']
    if type(w) not in (float,int) or type(h) not in (float,int) or not math.isfinite(w) or not math.isfinite(h) or w<=0 or h<=0:
        raise ValueError('Invalid original invoice dimensions')
    texts=case['raw_texts'];boxes=case['raw_boxes']
    if len(texts)!=len(boxes):raise ValueError('OCR source indices/boxes mismatch')
    boxes=[_rect(b,w,h) for b in boxes]
    out={'photo':case['file'],'source_sha256':case['source_sha256'],
         'source_token_count':len(texts),'original_tokens_preserved':True,
         'original_boxes_preserved':True,'unassigned_source_indices':[],
         'proposed_table_count':0,'proposed_row_count':0,'tables':[],
         'accepted_field_count':0,'printed_cell_boundaries_verified':0,
         'posting_eligible':False,'release_approved':False}
    role_items=[{'index':i,'role':_role(t),'box':b,'raw_text':t}
                for i,(t,b) in enumerate(zip(texts,boxes))]
    heading_candidates=[a for a in role_items if a['role']=='description' and
                        (a['box'][2]-a['box'][0])>=.8*(a['box'][3]-a['box'][1])]
    used=set()
    for desc in heading_candidates:
        dx=_cx(desc['box']);dy=_cy(desc['box'])
        # Only choose other HEADER words near this original printed row, never
        # infer headers from item data or a distant tax-summary table.
        window=max(23,.038*h)
        anchors=[a for a in role_items if a['role'] is not None and
                 a['index']!=desc['index'] and abs(_cy(a['box'])-dy)<=window and
                 .0001<=(_cx(a['box'])/w)<=.9999 and
                 a['box'][2]-a['box'][0]>=.5*(a['box'][3]-a['box'][1])]
        anchors.append(desc)
        # Ignore multiple words from the same column position (e.g. wrapped
        # "Rate" under "Basic"); retain only one column candidate per band.
        anchors.sort(key=lambda a:(_cx(a['box']),abs(_cy(a['box'])-dy)))
        dedup=[]
        for a in anchors:
            if dedup and abs(_cx(a['box'])-_cx(dedup[-1]['box']))<8:
                if abs(_cy(a['box'])-dy)<abs(_cy(dedup[-1]['box'])-dy):dedup[-1]=a
            else:dedup.append(a)
        anchors=dedup
        if len(anchors)<4 or len({a['role'] for a in anchors})<3 or \
                not {'hsn','amount','rate','quantity'}.intersection(a['role'] for a in anchors):
            continue
        # For one invoice, recognize each heading once. Do not create another
        # item-table out of the overlapping tax-summary header.
        if desc['index'] in used:continue
        slope=_slope(anchors)
        # Avoid proposing beyond next printed Total boundary.
        # Correct heading slope only for the row coordinate comparison.
        def adjusted(b):return _cy(b)-slope*(_cx(b)-dx)
        first_y=adjusted(desc['box'])
        footers=[adjusted(b) for i,(t,b) in enumerate(zip(texts,boxes))
                 if i not in {a['index'] for a in anchors} and
                 _norm(t) in {'total','subtotal','grandtotal','grosstotal','nettotal'}
                 and adjusted(b)>first_y+max(27,.020*h)]
        search_limit=min(first_y+max(85,.26*h),min(footers) if footers else float('inf'))
        # Another distinct description heading starts another printed block.
        # Never absorb a second product subsection into the first table.
        future_desc=[adjusted(a['box']) for a in heading_candidates
                     if a['index']!=desc['index'] and
                     adjusted(a['box'])>first_y+max(27,.020*h)]
        if future_desc:
            search_limit=min(search_limit,min(future_desc))
        head_ids={a['index'] for a in anchors}
        ordered=sorted(anchors,key=lambda a:_cx(a['box']))
        ix=ordered.index(desc)
        left=-float('inf') if ix==0 else (_cx(ordered[ix-1]['box'])+dx)/2
        right=float('inf') if ix==len(ordered)-1 else (_cx(ordered[ix+1]['box'])+dx)/2
        # The description must actually be in the FIRST supported item row;
        # no text substitution or invented row from other numeric columns.
        row_starts=[]
        for i,(t,b) in enumerate(zip(texts,boxes)):
            y=adjusted(b)
            if i in head_ids or not(first_y+max(14,.011*h)<y<search_limit):continue
            if not (left<=_cx(b)<right) or not _is_item_description(t) or _role(t)=='description':continue
            if any(abs(y-r['aligned_y'])<max(13,.012*h) for r in row_starts):
                continue
            row_starts.append({'source_index':i,'aligned_y':y,'source_box':list(b),'raw_text':t})
        row_starts.sort(key=lambda a:a['aligned_y'])
        if not row_starts:continue
        table={'description_header_source_index':desc['index'],
               'header_source_indices':[a['index'] for a in ordered],
               'headers':[{'source_index':a['index'],'raw_text':a['raw_text'],
                           'source_box':list(a['box']),'role_hint':a['role']}
                          for a in ordered],
               'header_slope_hypothesis':round(slope,6),
               'source_row_boundary_verified':False,
               'physical_column_dividers_verified':False,
               'table_end_aligned_y_hypothesis':round(search_limit,3),
               'rows':[],'ignored_non_item_tokens':[]}
        for row in row_starts:
            near=max(11,min(22,.010*h))
            members=[]
            for i,(t,b) in enumerate(zip(texts,boxes)):
                if i in head_ids or i in used or _cy(b)<=dy-.05*h:continue
                if not first_y+max(12,.009*h)<adjusted(b)<search_limit:continue
                if abs(adjusted(b)-row['aligned_y'])<=near:
                    # A token belongs to at most one row, and if two row bands
                    # are close to an equal distance we refuse the assignment.
                    nearest=sorted((abs(adjusted(b)-r['aligned_y']),r['source_index']) for r in row_starts)
                    if len(nearest)>1 and abs(nearest[1][0]-nearest[0][0])<1.5:
                        continue
                    if nearest[0][1]==row['source_index']:
                        members.append(i)
            if row['source_index'] not in members:members.append(row['source_index'])
            members=sorted(set(members),key=lambda i:_cx(boxes[i]))
            cells=[]
            for i in members:
                b=boxes[i];center=_cx(b)
                col=min(range(len(ordered)),key=lambda k:abs(center-_cx(ordered[k]['box'])))
                next_dist=sorted(abs(center-_cx(o['box'])) for o in ordered)
                boundary_margin=min(5,max(2,(b[2]-b[0])*.08))
                bounds=[(ordered[k]['role'],ordered[k]['index']) for k in range(len(ordered))
                        if (k==0 or b[0] < (_cx(ordered[k-1]['box'])+_cx(ordered[k]['box']))/2-boundary_margin)
                        and (k==len(ordered)-1 or b[2] > (_cx(ordered[k]['box'])+_cx(ordered[k+1]['box']))/2+boundary_margin)]
                # Spanning source OCR token is never split into phantom
                # independent fields; flag multiple column intersections.
                crosses=[]
                for k in range(len(ordered)-1):
                    cut=(_cx(ordered[k]['box'])+_cx(ordered[k+1]['box']))/2
                    if b[0]+boundary_margin<cut<b[2]-boundary_margin:crosses.append(k)
                cells.append({'source_token_index':i,'original_box':list(b),
                              'raw_text':texts[i],
                              'nearest_header_source_index':ordered[col]['index'],
                              'column_role_hint':ordered[col]['role'],
                              'source_token_crosses_column_hypotheses':bool(crosses),
                              'physical_cell_verified':False,'value_verified':False})
            if len(cells)<2:continue
            # When the printed header explicitly offers an HSN column, require
            # at least one SOURCE token with a plausible HSN numeric run near
            # that column. This rules out subtotal/total lines silently
            # mistaken for a product description (e.g. 'Ional' for 'Total').
            # Does NOT certify HSN meaning, number or character accuracy.
            if any(a['role']=='hsn' for a in ordered):
                hsn_centers=[_cx(a['box']) for a in ordered if a['role']=='hsn']
                if not any(re.search(r'(?<!\d)\d{6,10}(?!\d)',c['raw_text']) and
                           (c['column_role_hint']=='hsn' or
                            any(c['original_box'][0]<=x<=c['original_box'][2] for x in hsn_centers))
                           for c in cells):
                    continue
            table['rows'].append({'description_anchor_source_index':row['source_index'],
                                  'source_indices':[c['source_token_index'] for c in cells],
                                  'original_tokens':cells,'row_value_verified':False,
                                  'row_physical_boundary_verified':False,
                                  'posting_eligible':False})
            used.update(members)
        if table['rows']:
            out['tables'].append(table)
            used.update(head_ids)
    out['proposed_table_count']=len(out['tables'])
    out['proposed_row_count']=sum(len(t['rows']) for t in out['tables'])
    out['unassigned_source_indices']=[i for i in range(len(texts)) if i not in used]
    assert len(set(used))==len(used)
    assert sorted(used|set(out['unassigned_source_indices']))==list(range(len(texts)))
    return out
