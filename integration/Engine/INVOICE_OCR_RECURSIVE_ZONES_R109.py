#!/usr/bin/env python3
"""R109 content-aware, bounded recursive zoning.

Coordinates and source content are never rewritten. OCR is untrusted evidence,
not financial truth, and every proposed classification remains unapproved.
Output leaves retain a parent_id, depth, and decision evidence. When OCR is
missing or uncertain, preserve the coarse zone for explicit human review.
"""
import re
import math
from collections import defaultdict

CUES = {
    'supplier': (r'\bSUPPLIER\b', r'\bSELLER\b', r'\bVENDOR\b', r'\bSOLD\s+BY\b', r'\bFROM\s*:',
                 r'\bSUPPL(?:I)?ER\s+ADDR(?:ESS|E)?\b'),
    'buyer': (r'\bBILL\s*TO\b', r'\bBUYER\b', r'\bCUSTOMER\b', r'\bBILLED\s+TO\b'),
    'ship_to': (r'\bSHIP\s*TO\b', r'\bCONSIGNEE\b', r'\bDELIVER\s*TO\b'),
    'invoice_meta': (r'^INVOICE$', r'\bTAX\s+INVOICE\b', r'\bINVOICE\s*(?:NO|NUMBER|DATE|#)\b',
                     r'\bINV[ .]*(?:NO|DATE)\b', r'\bBILL\s*(?:NO|DATE)\b', r'\bPO\s*(?:NO|NUMBER)\b',
                     r'\b(?:ORDER|C[. ]*N|CREDIT\s+NOTE)\s*(?:NO\.?|NUMBER|DATE)\b',
                     r'\b(?:DOCUMENT|DOC)\s*(?:NO\.?|NUMBER|DATE)\b'),
    'item_table': (r'\bHSN\b', r'\bSAC\b', r'\bITEM\s*(?:NAME|DESCRIPTION)\b',
                   r'\bDESCRIPTION\b', r'\bQTY\b', r'\bQUANTITY\b', r'\bUNIT\s*PRICE\b'),
    'tax': (r'\bCGST\b', r'\bSGST\b', r'\bIGST\b', r'\bTAXABLE\s*(?:AMOUNT|VALUE)\b',
            r'\bGST\s*(?:AMOUNT|SUMMARY|RATE)\b'),
    'totals': (r'\bGRAND\s+TOTAL\b', r'\bNET\s*(?:AMOUNT|PAYABLE)\b',
               r'\bAMOUNT\s*(?:PAYABLE|IN\s+WORDS)\b', r'\bTOTAL\s*(?:AMOUNT|DUE)\b'),
    'payment': (r'\bIFSC\b', r'\bBANK\s*(?:DETAILS|ACCOUNT|NAME)\b',
                r'\bACCOUNT\s*(?:NO|NUMBER)\b', r'\bUPI\s*ID\b'),
    'terms': (r'\bTERMS\s*(?:&|AND)\s*CONDITIONS\b', r'\bDECLARATION\b', r'\bAUTHORIZED\s+SIGNATORY\b')
}
PATTERNS = {cat: [re.compile(pattern) for pattern in patterns] for cat,patterns in CUES.items()}
LABELS = {'supplier':'Supplier Information', 'buyer':'Buyer / Bill To',
          'ship_to':'Consignee / Ship To', 'invoice_meta':'Invoice Details',
          'item_table':'Items Table','tax':'Tax Details','totals':'Totals / Amount in Words',
          'payment':'Payment / Bank Details','terms':'Notes / Terms','unknown':'Unknown / Other'}


def category_scores(text):
    cleaned = re.sub(r'\s+', ' ', text.upper().replace('_',' ')).strip()
    return {cat: sum(bool(p.search(cleaned)) for p in patterns) for cat,patterns in PATTERNS.items()
            if any(p.search(cleaned) for p in patterns)}


def parse_tsv(raw, width, height):
    rows=defaultdict(list)
    for line in raw.splitlines()[1:]:
        p=line.split('\t',11)
        if len(p)!=12: continue
        try:
            conf=float(p[10]); x,y,w,h=(int(p[i]) for i in (6,7,8,9))
            word=p[11].strip()
            if conf<22 or not word or w<=0 or h<=0:continue
            x0=max(0,x);y0=max(0,y);x1=min(width,x+w);y1=min(height,y+h)
            if x1<=x0 or y1<=y0:continue
            rows[tuple(p[i] for i in (1,2,3,4))].append(dict(text=word,box=[x0,y0,x1,y1],conf=conf))
        except (ValueError,IndexError): continue
    lines=[]
    for ws in rows.values():
        ws.sort(key=lambda a:a['box'][0]);
        if not ws:continue
        # Split only a substantial visual gutter between word runs. This
        # recovers independent information in two columns sharing one OCR line.
        chunks=[];current=[ws[0]]
        for word in ws[1:]:
            gap=word['box'][0]-current[-1]['box'][2]
            if gap>=max(32,width*.065):chunks.append(current);current=[]
            current.append(word)
        chunks.append(current)
        for chunk in chunks:
            text=' '.join(w['text'] for w in chunk)
            xy=[min(w['box'][0] for w in chunk),min(w['box'][1] for w in chunk),
                max(w['box'][2] for w in chunk),max(w['box'][3] for w in chunk)]
            scores=category_scores(text)
            cat=max(scores,key=scores.get) if scores else 'unknown'
            lines.append(dict(xyxy=xy, text=text,category=cat,scores=scores,
                              confidence=round(sum(w['conf'] for w in chunk)/len(chunk),1)))
    return sorted(lines,key=lambda l:(l['xyxy'][1],l['xyxy'][0]))


def intersection_fraction(a,b):
    x0=max(a[0],b[0]);y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
    return max(0,x1-x0)*max(0,y1-y0)/max(1,(b[2]-b[0])*(b[3]-b[1]))


def in_zone(lines,xy):
    return [line for line in lines if intersection_fraction(xy,line['xyxy'])>=.55]


def content_groups(lines):
    """Protect observed table rows and adjacent standalone label/value pairs.

    These are logical groups, never claims that a printed border exists.
    Original text and individual source boxes remain in the returned evidence.
    """
    groups=[];used=set()
    header=re.compile(r'^(?:HSN(?:\s*[/&-]\s*(?:SAC|SKU))?|SAC|QTY|QUANTITY|'
                      r'(?:PRODUCT\s*[/&-]\s*)?DESCRIPTION|ITEM\s*(?:NAME|DESCRIPTION))$',re.I)
    headers=[l for l in lines if header.fullmatch(l['text'].strip())]
    for first in headers:
        if id(first) in used:continue
        fy=(first['xyxy'][1]+first['xyxy'][3])/2
        fh=first['xyxy'][3]-first['xyxy'][1]
        row=[l for l in headers if abs((l['xyxy'][1]+l['xyxy'][3])/2-fy)<=max(fh,l['xyxy'][3]-l['xyxy'][1])*.6]
        if len(row)<2 or max(l['xyxy'][0] for l in row)-min(l['xyxy'][0] for l in row)<2*fh:continue
        top=min(l['xyxy'][1] for l in row)
        bottom=max(l['xyxy'][3] for l in row)
        # A new explicit summary/party/metadata section ends the observed table.
        ends=[l['xyxy'][1] for l in lines if l['xyxy'][1]>bottom+fh*.5 and
              (l['category'] in ('totals','payment','terms') or
               re.match(r'^(?:taxable|sub\s*total|CGST|SGST|IGST|tax\s*(?:summary|amount)|bill\s*to|ship\s*to|invoice\s*(?:no|date))\b',l['text'],re.I))]
        end=min(ends) if ends else max(l['xyxy'][3] for l in lines)+1
        members=[l for l in lines if l['xyxy'][1]>=top-fh*.3 and l['xyxy'][3]<end]
        if len(members)<=len(row):continue
        used.update(map(id,members))
        groups.append({'category':'item_table','members':members,'reason':'observed_multi_column_item_header_and_following_rows'})
    # Keep standalone field labels with nearby same-row or next-row values.
    # Ambiguous neighboring readings are all protected; none is chosen as truth.
    label=re.compile(r'^(?:supplier(?:\s*name)?|seller(?:\s*name)?|sold\s*by|bill(?:ed)?\s*to|buyer(?:\s*name)?|customer\s*name|ship\s*to|consignee|invoice\s*(?:no\.?|number|date|#)|bill\s*(?:no\.?|number|date)|date|grand\s*total|net\s*(?:payable|amount)|total\s*amount|amount\s*payable)\s*[:#-]?$',re.I)
    for anchor in lines:
        if id(anchor) in used or not label.fullmatch(anchor['text'].strip()):continue
        a=anchor['xyxy'];ah=a[3]-a[1];members=[anchor]
        for value in lines:
            if value is anchor or id(value) in used or value['category']!='unknown':continue
            b=value['xyxy'];bh=b[3]-b[1];height=max(ah,bh)
            same_row=min(a[3],b[3])-max(a[1],b[1])>=.5*min(ah,bh)
            right=same_row and 0<=b[0]-a[2]<=12*height
            below=0<=b[1]-a[3]<=1.5*height and abs(b[0]-a[0])<=2*height
            if right or below:members.append(value)
        if len(members)>1:groups.append({'category':anchor['category'],'members':members,'reason':'adjacent_standalone_label_and_unclassified_values'})
    for group in groups:
        members=group['members']
        group['xyxy']=[min(l['xyxy'][0] for l in members),min(l['xyxy'][1] for l in members),
                       max(l['xyxy'][2] for l in members),max(l['xyxy'][3] for l in members)]
    return groups


def grouped_anchors(lines,groups):
    covered={id(l) for g in groups if g['category']=='item_table' for l in g['members']}
    anchors=[l for l in lines if l['category']!='unknown' and id(l) not in covered]
    anchors += [{'xyxy':g['xyxy'],'category':g['category'],'scores':{'item_table':1}}
                for g in groups if g['category']=='item_table']
    return anchors


def _best_partition(box, anchored, orientation, source_lines=None):
    x0,y0,x1,y1=box;coord=0 if orientation=='vertical' else 1
    bounds=(x0,x1) if coord==0 else (y0,y1)
    dim=bounds[1]-bounds[0]; minimum=max(18,dim*.16)
    if dim < 2*minimum+12: return None
    source=source_lines if source_lines is not None else anchored
    # Candidate gutters come from *all* observed text and protected groups.
    # An anchor midpoint may land on an intervening unclassified value even
    # when a real text-free gutter exists immediately beside it.
    spans=sorted((max(bounds[0],v['xyxy'][coord]),min(bounds[1],v['xyxy'][coord+2])) for v in source)
    merged=[]
    for start,end in spans:
        if end<=start:continue
        if merged and start<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],end)
        else:merged.append([start,end])
    cuts=[]
    for a,b in zip(merged,merged[1:]):
        if b[0]-a[1]<max(4,dim*.007):continue
        cut=(a[1]+b[0])/2
        if not(bounds[0]+minimum<=cut<=bounds[1]-minimum):continue
        left=[v for v in anchored if (v['xyxy'][coord]+v['xyxy'][coord+2])/2<cut]
        right=[v for v in anchored if (v['xyxy'][coord]+v['xyxy'][coord+2])/2>=cut]
        if not left or not right:continue
        lcats={v['category'] for v in left};rcats={v['category'] for v in right}
        if lcats & rcats: continue
        # Refuse splits through known text boxes; no need to hallucinate a border.
        if any(v['xyxy'][coord]<cut<v['xyxy'][coord+2] for v in (source_lines if source_lines is not None else anchored)):continue
        purity=len(left)+len(right)
        gap=b[0]-a[1]
        score=10*purity+min(20,100*gap/max(dim,1)) - abs(len(left)-len(right))*.3
        cuts.append((score,cut,lcats,rcats))
    return max(cuts,key=lambda e:e[0]) if cuts else None


def internal_format(lines,box):
    """Describe actual text placement inside one region; no invented cell borders."""
    ycenters=sorted((l['xyxy'][1]+l['xyxy'][3])/2 for l in lines)
    xstarts=sorted(l['xyxy'][0] for l in lines)
    row_count=0;last=None
    for y in ycenters:
        if last is None or y-last>7:row_count+=1;last=y
    columns=1
    if len(xstarts)>=4:
        gaps=[(xstarts[i+1]-xstarts[i],i) for i in range(len(xstarts)-1)]
        size=box[2]-box[0]
        if gaps and max(gaps)[0]>max(26,size*.16):
            at=max(gaps)[1]
            if at>=1 and len(xstarts)-at-1>=2:columns=2
    return {'observed_text_line_count':len(lines), 'observed_row_bands':row_count,
            'possible_text_columns':columns,
            'measured_text_span_xyxy':[
                min((l['xyxy'][0] for l in lines),default=box[0]),
                min((l['xyxy'][1] for l in lines),default=box[1]),
                max((l['xyxy'][2] for l in lines),default=box[2]),
                max((l['xyxy'][3] for l in lines),default=box[3])],
            'format_certified':False}


def refine_regions(img,coarse,raw_tsv=None,max_depth=3,max_leaves=70):
    h,w=img.shape[:2]
    text_lines=parse_tsv(raw_tsv,w,h) if raw_tsv else []
    next_id=1+max([int(r.get('id','R000')[1:]) for r in coarse if re.fullmatch(r'R\d{3}',r.get('id',''))] or [0])
    leaves=[];decisions=[]
    def visit(zone,parent=None,depth=0):
        nonlocal next_id
        xy=zone['xyxy'];lines=in_zone(text_lines,xy)
        groups=content_groups(lines)
        anchored=grouped_anchors(lines,groups)
        evidence=defaultdict(int)
        for line in anchored:evidence[line['category']]+=sum(line['scores'].values())
        ranked=sorted(evidence,key=lambda cat:(-evidence[cat],cat))
        # OCR is not the sole source of layout evidence. Preserve a non-unknown
        # structural hypothesis when text has no usable anchors, but never certify it.
        structural_category=zone.get('category','unknown')
        dominant=ranked[0] if ranked else (structural_category if structural_category in LABELS else 'unknown')
        origin='OCR_ANCHOR' if ranked else ('STRUCTURE_ONLY_UNVERIFIED' if dominant!='unknown' else 'UNCLASSIFIED_REVIEW')
        current=dict(zone)
        current.update(parent_id=parent,depth=depth,classification_evidence=origin,category=dominant,
                       label=LABELS[dominant],status='NEEDS_REVIEW',ocr_authorized=False,
                       proposed_approved=False,internal_format=internal_format(lines,xy),
                       content_evidence={'text_excerpt':' | '.join(l['text'] for l in lines)[:250],
                                         'recognized_lines':len(lines),
                                         'anchors':dict(evidence),
                                         'confidence':round(sum(l['confidence'] for l in lines)/len(lines),1) if lines else None,
                                         'ocr_available':bool(raw_tsv),
                                         'logical_groups':[{'category':g['category'],'xyxy':g['xyxy'],
                                            'reason':g['reason'],'physical_border_verified':False,
                                            'source_members':[{'text':l['text'],'xyxy':l['xyxy']} for l in g['members']]} for g in groups]})
        # Do not erase observed item-table evidence simply because Tesseract is absent.
        candidate=None
        if len(ranked)>=2 and depth<max_depth and len(leaves)+2<max_leaves:
            for direction in ('vertical','horizontal'):
                part=_best_partition(xy,anchored,direction,
                                     [l for l in text_lines if intersection_fraction(xy,l['xyxy'])>0]+groups)
                if part is not None and (candidate is None or part[0]>candidate[0]):
                    candidate=(part[0],direction,*part[1:])
        if candidate:
            _,axis,cut,lcats,rcats=candidate
            cut=round(cut)
            a=list(xy);b=list(xy)
            if axis=='vertical':a[2]=cut;b[0]=cut
            else:a[3]=cut;b[1]=cut
            # Only subdivide if each child has source-backed class evidence.
            coord=0 if axis=='vertical' else 1
            crossing=any(l['xyxy'][coord]<cut<l['xyxy'][coord+2]
                         for l in text_lines+groups if intersection_fraction(xy,l['xyxy'])>0)
            if not crossing and len(in_zone(anchored,a))>0 and len(in_zone(anchored,b))>0:
                decisions.append({'parent_id':current['id'],'axis':axis,'split_coordinate':cut,
                                  'depth':depth,'left_or_top':sorted(lcats),'right_or_bottom':sorted(rcats),
                                  'reason':'distinct OCR-labeled information groups with a visible text gutter',
                                  'review_required':True})
                for child in (a,b):
                    child_id=f'R{next_id:03d}';next_id+=1
                    if next_id>999:raise ValueError('Zone ID safety limit exceeded')
                    visit({**zone,'id':child_id,'xyxy':child,'source':'R109_CONTENT_AWARE_SPLIT',
                           'overlap_warnings':[]},current['id'],depth+1)
                return
        if len(ranked)>1:current['content_evidence']['mixed_groups_need_review']=ranked
        if not raw_tsv:current['content_evidence']['warning']='Content OCR unavailable: do not infer groups from positions'
        leaves.append(current)
    for zone in coarse:
        if len(leaves)>=max_leaves:
            raise ValueError('Zone refinement safety limit reached; refusing incomplete output')
        visit(zone)
    return leaves,{'method':'bounded_semantic_spatial_recursive','ocr_available':bool(raw_tsv),
                   'raw_line_count':len(text_lines),'initial_count':len(coarse),
                   'leaf_count':len(leaves),'splits':decisions,'max_depth':max_depth,
                   'stage':'PROVISIONAL_REVIEW_REQUIRED','source_pixels_changed':False,
                   'review_warnings':['Mixed or ambiguous content is not automatically split or approved.',
                                      'No OCR value may authorize accounting posting.']},text_lines
