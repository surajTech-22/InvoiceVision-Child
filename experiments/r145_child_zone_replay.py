"""Replay source OCR geometry through the actual staged Child recursive engine.

TSV confidence is a fixed replay inclusion flag, not a measured model score.
No semantic or accounting accuracy is certified by these geometry checks.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
from .r138_field_evidence import box_of


def run(report,engine,out):
    spec=importlib.util.spec_from_file_location('child_recursive_replay',engine)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=json.loads(report.read_text())
    result={'cases':[],'semantic_accuracy_verified':False,'posting_eligible':False,
            'replay_tsv_confidence_is_not_model_confidence':True}
    for case in data['cases']:
        width,height=case['source_width'],case['source_height']
        rows=['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext']
        for i,(text,poly) in enumerate(zip(case['raw_texts'],case['raw_boxes']),1):
            b=box_of(poly)
            if b is None:continue
            x,y,x1,y1=map(round,b)
            if x<0 or y<0 or x1>width or y1>height:raise ValueError('Invalid source geometry')
            text=str(text).replace('\t',' ').replace('\n',' ')
            rows.append(f'5\t1\t{i}\t1\t1\t1\t{x}\t{y}\t{x1-x}\t{y1-y}\t50\t{text}')
        leaves,meta,lines=module.refine_regions(np.zeros((height,width,3),dtype='uint8'),
            [{'id':'R001','xyxy':[0,0,width,height],'category':'unknown'}],'\n'.join(rows))
        cuts=[]
        for decision in meta['splits']:
            axis=0 if decision['axis']=='vertical' else 1
            cut=decision['split_coordinate']
            # Descendant cuts need only protect text intersecting that parent;
            # the engine enforces that scope. Leaf containment below detects
            # source text lost across any emitted descendant boundary.
            cuts.append({'axis':axis,'coordinate':cut})
        uncovered=[l for l in lines if not any(
            z['xyxy'][0]<=l['xyxy'][0] and z['xyxy'][1]<=l['xyxy'][1] and
            z['xyxy'][2]>=l['xyxy'][2] and z['xyxy'][3]>=l['xyxy'][3] for z in leaves)]
        if uncovered:raise ValueError('Child split crops source text: '+case['file'])
        assert all(not z['ocr_authorized'] and not z['proposed_approved'] for z in leaves)
        result['cases'].append({'file':case['file'],'source_sha256':case['source_sha256'],
            'source_lines':len(lines),'leaves':len(leaves),'splits':len(cuts),
            'uncovered_lines':len(uncovered),'semantic_accuracy_verified':False})
    out.write_text(json.dumps(result,indent=2))
    print('CHILD_SOURCE_GEOMETRY_REPLAY',len(result['cases']),'ZERO_CROPPED_TEXT_LINES')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True)
    p.add_argument('--engine',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.report,a.engine,a.out)
