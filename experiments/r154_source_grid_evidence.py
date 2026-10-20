"""InvoiceVision R154: read-only, source-ink-supported grid and token review.

Important distinctions:
  * Directional dark pixels are OCR-independent *stroke candidates*, not proof
    that a line is printed (paper edges, folds, and text can be dark too).
  * Four-sided source-supported cell candidates are NOT certified physical cells.
  * No line pixels are generated/bridged, no page ROI is cropped, no OCR tokens
    are rewritten, no semantic/accounting field is approved, no posting.

Requires CPU-only opencv-python and numpy. This module never calls a GPU.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import json
import cv2
import numpy as np
from r152_unknown_semantic_islands import propose as anchor_propose, _box
from r153_source_value_associations import associate as label_associate

PARAMETERS = {
    'adaptive_block_size':31, 'adaptive_c':12, 'clahe_clip_limit':2.0,
    'min_kernel_px':22, 'kernel_fraction':0.025,
    'min_stroke_length_px':50, 'min_stroke_length_fraction':0.05,
    'max_stroke_thickness_fraction':0.04, 'aspect_min':8,
    'merge_axis_tolerance_px':4, 'edge_perp_tolerance_px':3,
    'edge_min_source_support':0.86,
    'cell_min_width_px':20, 'cell_min_height_px':15,
    'max_axis_candidates':160,
}

def _read_source(path):
    original=Path(path).read_bytes()
    image=cv2.imdecode(np.frombuffer(original,dtype=np.uint8),cv2.IMREAD_COLOR)
    if image is None or len(image.shape)!=3:raise ValueError('Cannot decode original source photograph')
    return original,image

def _stroke_masks(image):
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    local=cv2.createCLAHE(clipLimit=PARAMETERS['clahe_clip_limit'],tileGridSize=(8,8)).apply(gray)
    dark=cv2.adaptiveThreshold(local,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV,PARAMETERS['adaptive_block_size'],PARAMETERS['adaptive_c'])
    masks={};lines={}
    for axis in ('horizontal','vertical'):
        dim=w if axis=='horizontal' else h
        kernel_len=max(PARAMETERS['min_kernel_px'],int(dim*PARAMETERS['kernel_fraction']))
        kernel=cv2.getStructuringElement(cv2.MORPH_RECT,(kernel_len,1) if axis=='horizontal' else (1,kernel_len))
        opened=cv2.morphologyEx(dark,cv2.MORPH_OPEN,kernel)
        # Explicit pixel-subset gate: even if a morphology implementation
        # interpolates a pixel, only the original thresholded source can survive.
        mask=cv2.bitwise_and(opened,dark)
        assert not np.any((mask>0)&(dark==0))
        masks[axis]=mask
        n,components,stats,_=cv2.connectedComponentsWithStats(mask,connectivity=8)
        evidence=[]
        for idx,(x,y,cw,ch,pixels) in enumerate(stats[1:],start=1):
            if axis=='horizontal':
                valid=(cw>=max(PARAMETERS['min_stroke_length_px'],w*PARAMETERS['min_stroke_length_fraction'])
                    and cw>=ch*PARAMETERS['aspect_min'] and ch<=max(18,h*PARAMETERS['max_stroke_thickness_fraction']))
            else:
                valid=(ch>=max(PARAMETERS['min_stroke_length_px'],h*PARAMETERS['min_stroke_length_fraction'])
                    and ch>=cw*PARAMETERS['aspect_min'] and cw<=max(18,w*PARAMETERS['max_stroke_thickness_fraction']))
            if not valid:continue
            yy,xx=np.nonzero(components[y:y+ch,x:x+cw]==idx)
            coordinate=(y+int(np.median(yy))) if axis=='horizontal' else (x+int(np.median(xx)))
            evidence.append({'axis':axis,'coord':int(coordinate),
                             'start':int(x if axis=='horizontal' else y),
                             'end':int(x+cw if axis=='horizontal' else y+ch),
                             'original_dark_pixel_count':int(pixels),
                             'original_source_support_bbox':[int(x),int(y),int(x+cw),int(y+ch)],
                             'printed_line_verified':False})
        lines[axis]=evidence
    return masks,lines

def _merge_coordinates(coords,tolerance=4):
    groups=[]
    for value in sorted(coords):
        if not groups or value-float(np.median(groups[-1]))>tolerance:groups.append([value])
        else:groups[-1].append(value)
    return [int(round(float(np.median(g)))) for g in groups]

def _edge_support(mask,axis,coord,start,end,tol=3):
    h,w=mask.shape
    if axis=='horizontal':
        strip=mask[max(0,coord-tol):min(h,coord+tol+1),start:end]
        return float(np.count_nonzero(np.any(strip>0,axis=0))/max(1,end-start)) if strip.size else 0.0
    strip=mask[start:end,max(0,coord-tol):min(w,coord+tol+1)]
    return float(np.count_nonzero(np.any(strip>0,axis=1))/max(1,end-start)) if strip.size else 0.0

def _side_component(lines,coord,start,end):
    return any(abs(line['coord']-coord)<=PARAMETERS['merge_axis_tolerance_px'] and
               line['start']<=start+5 and line['end']>=end-5 for line in lines)

def _cell_candidates(masks,lines):
    hmask=masks['horizontal'];vmask=masks['vertical']
    ys=_merge_coordinates([l['coord'] for l in lines['horizontal']]);xs=_merge_coordinates([l['coord'] for l in lines['vertical']])
    if len(xs)>PARAMETERS['max_axis_candidates'] or len(ys)>PARAMETERS['max_axis_candidates']:
        raise ValueError('Too many stroke axes to safely infer cells')
    cells=[]
    for col in range(len(xs)-1):
        x0,x1=xs[col:col+2]
        if x1-x0<PARAMETERS['cell_min_width_px']:continue
        for row in range(len(ys)-1):
            y0,y1=ys[row:row+2]
            if y1-y0<PARAMETERS['cell_min_height_px']:continue
            if not(_side_component(lines['horizontal'],y0,x0,x1) and
                   _side_component(lines['horizontal'],y1,x0,x1) and
                   _side_component(lines['vertical'],x0,y0,y1) and
                   _side_component(lines['vertical'],x1,y0,y1)):
                continue
            support=[_edge_support(hmask,'horizontal',y0,x0,x1),
                     _edge_support(hmask,'horizontal',y1,x0,x1),
                     _edge_support(vmask,'vertical',x0,y0,y1),
                     _edge_support(vmask,'vertical',x1,y0,y1)]
            if min(support)<PARAMETERS['edge_min_source_support']:continue
            cells.append({'cell_id':len(cells),'bounds':[x0,y0,x1,y1],
                'grid_row_axis':row,'grid_column_axis':col,
                'source_ink_support_fractions':[round(z,5) for z in support],
                'four_sides_source_supported':True,
                'physically_printed_cell_verified':False,
                'ocr_token_indices':[],'source_label_roles':[],
                'posting_eligible':False})
    return cells

def _assign_tokens(cells,case,anchor):
    """Assign OCR tokens only when uniquely enclosed; ambiguous ones remain free."""
    w=case['source_width'];h=case['source_height'];boxes=case['raw_boxes']
    categories={i:group['category'] for group in anchor['semantic_islands'] for i in group['source_indices']}
    assigned={};unassigned=[];ambiguous=[];invalid=[]
    for i,raw in enumerate(boxes):
        b=_box(raw,w,h)
        if b is None:invalid.append(i);continue
        bx0,by0,bx1,by1=b;area=(bx1-bx0)*(by1-by0)
        claims=[]
        for c in cells:
            x0,y0,x1,y1=c['bounds']
            intersection=max(0,min(bx1,x1)-max(bx0,x0))*max(0,min(by1,y1)-max(by0,y0))
            # Pixel-based OCR box is evidence, not a physical printed cell.
            if intersection/area>=.90:claims.append(c['cell_id'])
        if len(claims)==1:
            cid=claims[0];assigned[i]=cid
            cells[cid]['ocr_token_indices'].append(i)
            if i in categories:cells[cid]['source_label_roles'].append(categories[i])
        elif len(claims)>1:ambiguous.append({'source_index':i,'competing_cell_ids':claims})
        else:unassigned.append(i)
    total=sorted(list(assigned)+unassigned+[x['source_index'] for x in ambiguous]+invalid)
    if total!=list(range(len(boxes))):raise AssertionError('OCR token lost or duplicated in cell review')
    return {'assigned':assigned,'unassigned':unassigned,'ambiguous':ambiguous,'invalid':invalid}

def _adjacent(a,b):
    x0,y0,x1,y1=a['bounds'];u0,v0,u1,v1=b['bounds']
    if (x1==u0 or u1==x0) and min(y1,v1)-max(y0,v0)>=10:return True
    if (y1==v0 or v1==y0) and min(x1,u1)-max(x0,u0)>=10:return True
    return False

def _clusters(cells):
    parent=list(range(len(cells)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i in range(len(cells)):
        for j in range(i+1,len(cells)):
            if _adjacent(cells[i],cells[j]):
                ri,rj=root(i),root(j)
                if ri!=rj:parent[rj]=ri
    groups=defaultdict(list)
    for i in range(len(cells)):groups[root(i)].append(i)
    out=[]
    for ids in groups.values():
        bounds=[cells[i]['bounds'] for i in ids]
        roles=sorted({role for i in ids for role in cells[i]['source_label_roles']})
        out.append({'cluster_id':len(out),'cell_ids':ids,
                    'candidate_bbox':[min(b[0] for b in bounds),min(b[1] for b in bounds),
                                      max(b[2] for b in bounds),max(b[3] for b in bounds)],
                    'source_label_roles':roles,
                    'semantic_status':'MIXED_UNRESOLVED' if len(roles)>1 else 'ONE_LABEL_KIND_UNVERIFIED' if roles else 'UNKNOWN',
                    'printed_table_verified':False,'recursive_leaf_approved':False,
                    'posting_eligible':False})
    return out

def _conservative_child_index_groups(anchor,assoc):
    """Index-only recursive-child hypotheses, never printed or semantic zones.

    Every exact R152 anchor becomes one tentative child. A value is attached
    only when R153 has exactly one nonshared candidate; even that attachment
    remains an unverified OCR reading and may conflict with manual source proof.
    """
    by_anchor={p['source_anchor_index']:p for p in assoc['proposals']}
    shared={int(i) for i in assoc['shared_candidate_conflicts']}
    groups=[];owned=set()
    for island in anchor['semantic_islands']:
        ids=list(island['source_indices']);idx=ids[0]
        if idx in owned:raise AssertionError('Duplicate source anchor ownership')
        owned.add(idx)
        proposal=by_anchor.get(idx)
        kind='SOURCE_ANCHOR_ONLY';possible=[]
        if proposal:
            candidates=proposal['candidates']
            if len(candidates)==1:
                j=candidates[0]['source_token_index']
                if j not in shared and j not in owned and j not in {g['source_indices'][0] for g in anchor['semantic_islands']}:
                    ids.append(j);owned.add(j)
                    kind='SINGLE_UNVERIFIED_LABEL_VALUE_ASSOCIATION'
                else:possible.append(j)
            else:possible=[q['source_token_index'] for q in candidates]
        groups.append({'candidate_child_id':len(groups),'category_hint':island['category'],
                       'source_indices':ids,'candidate_kind':kind,
                       'unattached_alternative_source_indices':possible,
                       'source_text_only_no_new_geometry':True,
                       'semantic_leaf_approved':False,'physical_border_verified':False,
                       'field_value_verified':False,'posting_eligible':False})
    return groups

def analyze_case(case,original_path):
    raw,image=_read_source(original_path)
    if sha256(raw).hexdigest()!=case['source_sha256']:raise ValueError('Original photograph SHA256 mismatch: '+case['file'])
    h,w=image.shape[:2]
    if [w,h]!=[case['source_width'],case['source_height']]:raise ValueError('Original photo dimensions disagree with OCR evidence')
    if len(case['raw_texts'])!=len(case['raw_boxes']):raise ValueError('OCR arrays inconsistent')
    anchor=anchor_propose(case)
    assoc=label_associate(case)
    children=_conservative_child_index_groups(anchor,assoc)
    masks,lines=_stroke_masks(image)
    cells=_cell_candidates(masks,lines)
    assignments=_assign_tokens(cells,case,anchor)
    clusters=_clusters(cells)
    cell_to_cluster={cid:g['cluster_id'] for g in clusters for cid in g['cell_ids']}
    assoc_context=[]
    for proposal in assoc['proposals']:
        i=proposal['source_anchor_index'];anchor_cell=assignments['assigned'].get(i)
        for candidate in proposal['candidates']:
            j=candidate['source_token_index'];value_cell=assignments['assigned'].get(j)
            if anchor_cell is not None and value_cell is not None:
                if anchor_cell==value_cell:relation='SAME_UNVERIFIED_CELL_CANDIDATE'
                elif cell_to_cluster[anchor_cell]==cell_to_cluster[value_cell]:relation='SAME_UNVERIFIED_TABLE_CLUSTER'
                else:relation='SEPARATE_GRID_CLUSTERS_UNRESOLVED'
            else:relation='ONE_OR_BOTH_OUTSIDE_SUPPORTED_CELLS'
            assoc_context.append({'source_anchor_index':i,'source_value_index':j,
                                  'raw_label':proposal['source_label'],'raw_value':candidate['raw_value'],
                                  'source_anchor_cell_id':anchor_cell,'source_value_cell_id':value_cell,
                                  'geometry_context':relation,'field_verified':False,'posting_eligible':False})
    return {'file':case['file'],'original_source_sha256':case['source_sha256'],
            'original_source_bytes_unchanged':sha256(Path(original_path).read_bytes()).hexdigest()==case['source_sha256'],
            'image_dimensions':[w,h], 'original_ocr_token_count':len(case['raw_texts']),
            'original_ocr_tokens_untouched':True,
            'source_dark_pixel_masks_are_subsets_of_thresholded_original':True,
            'line_candidates':lines,'line_candidate_counts':{axis:len(items) for axis,items in lines.items()},
            'four_sided_cell_candidates':cells,'four_sided_cell_candidate_count':len(cells),
            'candidate_grid_clusters':clusters,'grid_cluster_count':len(clusters),
            'token_assignment':{'uniquely_enclosed':len(assignments['assigned']),
                 'unassigned':len(assignments['unassigned']),
                 'ambiguous':len(assignments['ambiguous']),
                 'invalid_geometry':len(assignments['invalid']),
                 'unassigned_indices':assignments['unassigned'],
                 'ambiguous_details':assignments['ambiguous'],
                 'invalid_indices':assignments['invalid']},
            'r153_field_candidate_context':assoc_context,
            'source_index_only_child_hypotheses':children,
            'source_index_only_child_hypothesis_count':len(children),
            'unverified_single_label_value_child_count':sum(len(g['source_indices'])==2 for g in children),
            'original_unknown_parent_retained':True,'semantic_leaf_approved':False,
            'physically_printed_cells_verified':False,'source_dark_stroke_is_not_print_proof':True,
            'posting_eligible':False,'release_authorized':False},masks

def audit(report,originals_dir):
    cases=report.get('cases',[])
    if len(cases)!=51 or Counter(c.get('kind') for c in cases)!=Counter({'real':15,'synthetic':36}):
        raise ValueError('Expected 51 unique cases: 15 real plus 36 synthetic')
    if len({(c['kind'],c['file']) for c in cases})!=51:raise ValueError('Duplicate unique source identity')
    for c in cases:
        if len(c.get('raw_texts',[]))!=len(c.get('raw_boxes',[])):
            raise ValueError('51-case OCR source token/geometry array mismatch')
    unknown_only=sum(all(z['category']=='unknown' for z in c.get('leaves',[]))
                     for c in cases if c['kind']=='real')
    if unknown_only!=9:raise ValueError('Expected exactly nine inherited unknown-only parents')
    rows=[];masks={}
    for c in cases:
        if c['kind']!='real':continue
        row,mask=analyze_case(c,Path(originals_dir)/c['file'])
        rows.append(row);masks[c['file']]=mask
    return {'kind':'R154_SOURCE_DARK_STROKE_AND_CLOSED_CELL_CANDIDATES_ONLY',
            'source_51_case_ocr_array_integrity_checked':True,
            'source_51_unique_cases':51,'logical_benchmark_slots_expected':52,
            'logical_benchmark_slots_verified':0,
            'real_original_photo_hashes_verified':len(rows),
            'real_source_ocr_tokens_preserved':sum(r['original_ocr_token_count'] for r in rows),
            'real_originals_untouched':all(r['original_source_bytes_unchanged'] for r in rows),
            'original_9_unknown_only_semantic_parents_preserved':True,
            'source_ink_line_candidates':sum(sum(r['line_candidate_counts'].values()) for r in rows),
            'four_sided_cell_candidates':sum(r['four_sided_cell_candidate_count'] for r in rows),
            'grid_clusters':sum(r['grid_cluster_count'] for r in rows),
            'source_anchor_only_or_unverified_pair_child_hypotheses':sum(r['source_index_only_child_hypothesis_count'] for r in rows),
            'unverified_single_label_value_child_hypotheses':sum(r['unverified_single_label_value_child_count'] for r in rows),
            'unique_ocr_tokens_inside_candidate_cells':sum(r['token_assignment']['uniquely_enclosed'] for r in rows),
            'real_cases':rows,'original_51_source_pixels_available':False,
            'physical_cell_accuracy_certified':False,'field_accuracy_certified':False,
            'native_child_ui_verified':False,'installer_rollback_verified':False,
            'auto_posting_enabled':False,'release_authorized':False},masks

def audit_r151_roi_without_cropping(report,roi_report,original_report_sha256):
    """Retain the R151 paper-ROI conflicts as evidence; never filter OCR by ROI."""
    if roi_report.get('source_ocr_report_sha256')!=original_report_sha256:
        raise ValueError('R151 ROI and original R147 OCR report provenance mismatch')
    if roi_report.get('source_tokens_partial')!=11 or roi_report.get('source_tokens_outside')!=8:
        raise ValueError('R151 unresolved 19 ROI OCR token evidence changed')
    originals={c['file']:c for c in report['cases'] if c['kind']=='real'}
    if len(roi_report.get('cases',[]))!=15:raise ValueError('R151 ROI source case count mismatch')
    conflicts=[]
    for c in roi_report['cases']:
        source=originals[c['file']]
        if c['source_sha256']!=source['source_sha256']:
            raise ValueError('R151 ROI source SHA mismatch: '+c['file'])
        for role,key in [('partial','partial_tokens'),('outside','outside_tokens')]:
            for token in c[key]:
                i=token['index']
                if not (0<=i<len(source['raw_texts'])) or token['text']!=source['raw_texts'][i]:
                    raise ValueError('R151 ROI OCR token changed: '+c['file'])
                conflicts.append({'file':c['file'],'source_sha256':source['source_sha256'],
                                  'source_index':i,'raw_text':token['text'],
                                  'roi_conflict':role,'cropped':False,'posting_eligible':False})
    if len(conflicts)!=19:raise AssertionError('Missing original ROI conflict token')
    return {'roi_source_conflicts_preserved':len(conflicts),'partial':11,'outside':8,
            'auto_crop_authorized':False,'roi_is_not_printed_border':True,
            'source_tokens_not_dropped':True,'conflicts':conflicts}

def make_visuals(report,originals_dir,masks_by_file,out_dir):
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    for row in report['real_cases']:
        name=row['file'];_,source=_read_source(Path(originals_dir)/name)
        h,w=source.shape[:2]
        overlay=source.copy()
        mask=masks_by_file[name]
        # Mark *only* source-threshold-backed pixels. Do not draw any inferred
        # rectangle or line from coordinate endpoints.
        hpx=mask['horizontal']>0;vpx=mask['vertical']>0
        overlay[hpx]=(220,120,30);overlay[vpx]=(25,80,220)
        blend=cv2.addWeighted(source,.58,overlay,.42,0)
        for c in row['four_sided_cell_candidates']:
            x0,y0,x1,y1=c['bounds'];cx=(x0+x1)//2;cy=(y0+y1)//2
            cv2.putText(blend,str(c['cell_id']),(cx-4,cy+4),cv2.FONT_HERSHEY_SIMPLEX,.25,(0,200,240),1,cv2.LINE_AA)
        # Full-resolution 1:1 left original and right source-ink overlay.
        top=np.full((70,w*2,3),245,np.uint8)
        cv2.putText(top,'ORIGINAL SOURCE PIXELS',(10,26),cv2.FONT_HERSHEY_SIMPLEX,.65,(30,30,30),2)
        cv2.putText(top,'R154 SOURCE DARK STROKE CANDIDATES (NOT PRINTED-BOX PROOF)',(w+10,26),cv2.FONT_HERSHEY_SIMPLEX,.49,(30,30,30),1)
        cv2.putText(top,f"Source supported four-sided candidates: {row['four_sided_cell_candidate_count']}; approved physical cells: 0",(w+10,53),cv2.FONT_HERSHEY_SIMPLEX,.45,(50,50,50),1)
        canvas=np.vstack([top,np.hstack([source,blend])]);cv2.imwrite(str(out_dir/(Path(name).stem+'_R154_ORIGINAL_VS_SOURCE_STROKES.png')),canvas)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',required=True);parser.add_argument('--originals',required=True);parser.add_argument('--out',required=True)
    parser.add_argument('--roi-report',default=None)
    a=parser.parse_args()
    report=json.loads(Path(a.report).read_text(encoding='utf-8'))
    result,masks=audit(report,a.originals)
    if a.roi_report:
        roi=json.loads(Path(a.roi_report).read_text(encoding='utf-8'))
        result['r151_roi_non_crop_audit']=audit_r151_roi_without_cropping(report,roi,sha256(Path(a.report).read_bytes()).hexdigest())
    Path(a.out).mkdir(parents=True,exist_ok=True)
    (Path(a.out)/'R154_REPORT.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    make_visuals(result,a.originals,masks,Path(a.out)/'visuals')
    print(json.dumps({k:v for k,v in result.items() if k!='real_cases'},indent=2))