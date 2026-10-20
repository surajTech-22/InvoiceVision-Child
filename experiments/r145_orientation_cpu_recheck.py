"""Fresh quarter-turn OCR when token geometry suggests a sideways page.

Preserves competing directions and maps every polygon back to original source.
No reference filenames or expected accounting values influence the candidates.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from rapidocr import RapidOCR
from .r138_field_evidence import box_of
from .r143_orientation_evidence import point


def run(report_path,source_dir,out):
    original=json.loads(report_path.read_text())
    out.mkdir(parents=True,exist_ok=True)
    reader=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,
        'EngineConfig.onnxruntime.inter_op_num_threads':1,'EngineConfig.onnxruntime.use_cuda':False})
    report={'cases':[],'orientation_verified':False,'release_verified':False}
    for case in original['cases']:
        if case.get('kind')!='real':continue
        ratios=[]
        for text,poly in zip(case['raw_texts'],case['raw_boxes']):
            b=box_of(poly)
            if b and len(text)>8:ratios.append((b[2]-b[0])/(b[3]-b[1]))
        if not ratios or float(np.median(ratios))>=.6:continue
        image=cv2.imread(str(source_dir/case['file']))
        h,w=image.shape[:2]
        for turns in (1,3):
            view=cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE if turns==1 else cv2.ROTATE_90_CLOCKWISE)
            result=reader(view)
            polygons=result.boxes.tolist() if result.boxes is not None else []
            rw,rh=view.shape[1],view.shape[0]
            mapped=[[point(x,y,rw,rh,-turns) for x,y in poly] for poly in polygons]
            row={**case,'raw_texts':list(result.txts) if result.txts is not None else [],
                 'raw_boxes':mapped,'recognition_quarter_turns_ccw':turns,'orientation_verified':False}
            report['cases'].append(row)
            (out/'REPORT.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
            print(case['file'],turns,len(row['raw_texts']),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True)
    p.add_argument('--sources',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.report,a.sources,a.out)
