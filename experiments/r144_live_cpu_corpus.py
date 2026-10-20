"""Fresh CPU OCR on pinned test inputs; outputs are unverified evidence."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from .r147_utf8_evidence import write_json
import time
import zipfile
import cv2
import numpy as np
from rapidocr import RapidOCR


def run(baseline,out):
    engine=baseline/'InvoiceVisionChild/Engine'
    cases=[(p.name,p.read_bytes(),'synthetic') for p in sorted((engine/'InvoiceFormatExamples_R2').glob('*.png'))]
    with zipfile.ZipFile(engine/'VISUAL_BENCHMARK_15_PHOTOS.zip') as z:
        cases += [(Path(n).name,z.read(n),'real') for n in sorted(z.namelist())
                  if n.startswith('images/') and n.lower().endswith(('.png','.jpg','.jpeg'))]
    assert len(cases)==51
    out.mkdir(parents=True,exist_ok=True)
    reader=RapidOCR(params={'EngineConfig.onnxruntime.intra_op_num_threads':2,
                            'EngineConfig.onnxruntime.inter_op_num_threads':1,
                            'EngineConfig.onnxruntime.use_cuda':False})
    report={'kind':'FRESH_RAPIDOCR_CPU_INFERENCE','packages':{
                n:importlib.metadata.version(n) for n in ('rapidocr','onnxruntime','opencv-python-headless')},
            'cases':[],'release_verified':False,'posting_eligible':False}
    for name,raw,kind in cases:
        start=time.monotonic()
        try:
            image=cv2.imdecode(np.frombuffer(raw,np.uint8),1)
            result=reader(image)
            texts=list(result.txts) if result.txts is not None else []
            boxes=result.boxes.tolist() if result.boxes is not None else []
            record={'file':name,'kind':kind,'source_sha256':hashlib.sha256(raw).hexdigest(),
                    'source_width':image.shape[1],'source_height':image.shape[0],
                    'raw_texts':texts,'raw_boxes':boxes,'status':'OCR_COMPLETED_UNVERIFIED',
                    'seconds':round(time.monotonic()-start,3),'posting_eligible':False}
        except Exception as exc:
            record={'file':name,'status':'FAILED','error':type(exc).__name__+': '+str(exc)}
        report['cases'].append(record)
        write_json(out/'REPORT.json',report)
        print(name,record['status'],len(record.get('raw_texts',[])),flush=True)
    return 0 if all(c['status']=='OCR_COMPLETED_UNVERIFIED' for c in report['cases']) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();raise SystemExit(run(a.baseline,a.out))
