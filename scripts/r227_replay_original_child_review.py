"""R227: replay the ACTUAL staged Child review hook on user-owned original photos.

Inputs are the PRIVATE R153 evidence ZIP, and a SHA-verified, isolated staged
Child Engine folder. Neither images nor raw OCR texts are sent to GitHub.
Only hashes, aggregate counts and review status are written to the output.

The R147 report contains OCR text and image boxes but NOT the original OCR
confidence values. Therefore the constructed TSV uses a constant 99 as a
REPLAY INCLUSION PLACEHOLDER, never a model confidence or accuracy statistic.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import zipfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

HEADER='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'


def _module(engine, filename):
    path=(engine/filename).resolve()
    if not path.is_file() or path.parent != engine.resolve():
        raise ValueError('Missing staged Child module: '+filename)
    spec=importlib.util.spec_from_file_location('r227_'+filename.split('.')[0],path)
    if spec is None or spec.loader is None:
        raise ValueError('Cannot load Child source module')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tsv(case):
    texts=case['raw_texts']; boxes=case['raw_boxes']
    w=case['source_width']; h=case['source_height']
    if len(texts)!=len(boxes):
        raise ValueError('Saved source OCR observation/geometry count mismatch')
    lines=[HEADER]
    for i,(text,box) in enumerate(zip(texts,boxes),1):
        if (not isinstance(text,str) or not text.strip() or
            any(c in text for c in '\t\r\n') or
            not isinstance(box,(list,tuple)) or len(box)!=4 or
            any(type(x) is not int for x in box) or
            not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h)):
            raise ValueError('Unreplayable original OCR token %d' % (i-1))
        x0,y0,x1,y1=box
        lines.append('5\t1\t%d\t1\t1\t1\t%d\t%d\t%d\t%d\t99\t%s'%
                     (i,x0,y0,x1-x0,y1-y0,text))
    return '\n'.join(lines)+'\n'


def run(checkpoint, engine, out, compare_zones=True):
    """Fail the entire replay on provenance, mutation, mismatch or partial run."""
    checkpoint=Path(checkpoint); engine=Path(engine)
    review=_module(engine,'INVOICE_OCR_SOURCE_REVIEW_R226.py')
    zones=_module(engine,'INVOICE_OCR_RECURSIVE_ZONES_R109.py') if compare_zones else None
    with zipfile.ZipFile(checkpoint) as z:
        saved=json.loads(z.read('R147_ACTUAL_CHILD_REPORT.json'))
        cases=[c for c in saved['cases'] if c['kind']=='real']
        if len(cases)!=15 or len({c['file'] for c in cases})!=15:
            raise ValueError('Exact original 15-photo corpus not available')
        output=[]
        for case in sorted(cases,key=lambda x:x['file']):
            name=case['file']
            if name!=Path(name).name or not name.lower().endswith(('.jpg','.jpeg','.png')):
                raise ValueError('Unsafe saved source filename')
            photo=z.read('source_15/'+name)
            if hashlib.sha256(photo).hexdigest()!=case['source_sha256']:
                raise ValueError('Original source photograph SHA mismatch: '+name)
            image=cv2.imdecode(np.frombuffer(photo,np.uint8),cv2.IMREAD_COLOR)
            if image is None or (image.shape[1],image.shape[0]) != (case['source_width'],case['source_height']):
                raise ValueError('Original image coordinates mismatch: '+name)
            source_pixels=image.tobytes(order='C')
            tsv=_tsv(case)
            proposal=review.review(image,tsv)
            rows=proposal['row_hypotheses']
            if (proposal['source_observations']!=len(case['raw_texts']) or
                proposal['original_jpeg_sha256_verified'] or
                proposal['decoded_frame_sha256']!=hashlib.sha256(source_pixels).hexdigest() or
                not proposal['unmodified_tsv'] or
                proposal['posting_eligible'] or proposal['release_approved'] or
                rows['posting_eligible'] or rows['release_approved']):
                raise ValueError('Review provenance or posting invariant violated')
            if sorted(rows['unassigned_source_indices']+
                      [i for table in rows['tables'] for i in table['header_source_indices']]+
                      [i for table in rows['tables'] for row in table['rows'] for i in row['source_indices']])!=list(range(len(case['raw_texts']))):
                raise ValueError('Source OCR token duplicated or lost in item groups')
            if compare_zones:
                coarse=[{'id':'R001','xyxy':[0,0,image.shape[1],image.shape[0]],'category':'unknown'}]
                with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'0'}):
                    baseline_leaves,baseline_meta,baseline_lines=zones.refine_regions(image,coarse,tsv)
                with patch.dict(os.environ,{'INVOICEVISION_SOURCE_REVIEW_R226':'1'}):
                    live_leaves,live_meta,live_lines=zones.refine_regions(image,coarse,tsv)
                if (baseline_leaves!=live_leaves or baseline_lines!=live_lines or
                    'source_row_and_date_review' in baseline_meta or
                    live_meta['source_row_and_date_review']['status'] !=
                        'UNVERIFIED_SOURCE_GEOMETRY_REVIEW_ONLY'):
                    raise ValueError('Child zone behavior changed or review not attached')
            if image.tobytes(order='C')!=source_pixels:
                raise ValueError('Source image modified')
            output.append({
                'file':name, 'original_jpeg_sha256_verified':True,
                'source_image_sha256':case['source_sha256'],
                'decoded_frame_sha256':proposal['decoded_frame_sha256'],
                'raw_original_ocr_observations':len(case['raw_texts']),
                'proposed_item_rows':rows['proposed_row_count'],
                'proposed_tables':rows['proposed_table_count'],
                'date_anomalies':len(proposal['date_flags']),
                'unassigned_observations':len(rows['unassigned_source_indices']),
                'replayed_with_original_OCR_confidences':False,
                'zone_behavior_unchanged':bool(compare_zones),
                'physical_cell_truth_certified':False,
                'posting_eligible':False,
            })
    result={
        'status':'R227_REAL_ORIGINAL_READONLY_CHILD_REPLAY',
        'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        'original_jpeg_sha256_verified':len(output),
        'saved_ocr_observations_replayed':sum(x['raw_original_ocr_observations'] for x in output),
        'proposed_item_rows':sum(x['proposed_item_rows'] for x in output),
        'invoices_without_item_row_proposals':sum(x['proposed_item_rows']==0 for x in output),
        'date_anomalies':sum(x['date_anomalies'] for x in output),
        'raw_OCR_confidence_available':False,
        'physical_cells_certified':0,
        'character_accuracy_certified':False,
        'posting_eligible':False,
        'release_authorized':False,
        'cases':output,
    }
    if (result['original_jpeg_sha256_verified']!=15 or
        result['saved_ocr_observations_replayed']!=2361 or
        result['proposed_item_rows']!=26 or
        result['invoices_without_item_row_proposals']!=6 or
        result['date_anomalies']!=7):
        raise ValueError('Original-corpus regression mismatch; do not substitute inferred data')
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('R227_15_ORIGINAL_JPEG_HASH_PASS_2361_SOURCE_LINES_26_ROWS_7_DATE_FLAGS')
    print('FULL_INVOICE_ACCURACY_NOT_CERTIFIED_AND_NO_INSTALLER')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--checkpoint',required=True,type=Path)
    p.add_argument('--engine',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--no-zone-compare',action='store_true')
    args=p.parse_args()
    run(args.checkpoint,args.engine,args.out,not args.no_zone_compare)
