"""Re-evaluate zone changes against immutable saved OCR, without rerunning OCR."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import zipfile
import cv2
import numpy as np
from .r146_child_cpu_corpus import module, comparison


def run(report,baseline,engine,out):
    zones=module(engine,'rezone_child');data=json.loads(report.read_text())
    root=baseline/'InvoiceVisionChild/Engine'
    sources={p.name:p.read_bytes() for p in (root/'InvoiceFormatExamples_R2').glob('*.png')}
    with zipfile.ZipFile(root/'VISUAL_BENCHMARK_15_PHOTOS.zip') as z:
        sources.update({Path(n).name:z.read(n) for n in z.namelist() if n.startswith('images/') and not n.endswith('/')})
    result=copy.deepcopy(data);result['cases']=[]
    result['source_ocr_report_sha256']=hashlib.sha256(report.read_bytes()).hexdigest()
    result['zone_overlay_sha256']=hashlib.sha256(engine.read_bytes()).hexdigest()
    out.mkdir(parents=True,exist_ok=True)
    for case in data['cases']:
        if case['status']=='FAILED':result['cases'].append(case);continue
        raw=sources[case['file']]
        assert hashlib.sha256(raw).hexdigest()==case['source_sha256']
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),1);h,w=image.shape[:2]
        tsv=(report.parent/(Path(case['file']).stem+'.tsv')).read_text()
        leaves,meta,lines=zones.refine_regions(image,[dict(id='R001',xyxy=[0,0,w,h],category='unknown')],tsv)
        assert all(any(z['xyxy'][0]<=l['xyxy'][0] and z['xyxy'][1]<=l['xyxy'][1] and z['xyxy'][2]>=l['xyxy'][2] and z['xyxy'][3]>=l['xyxy'][3] for z in leaves) for l in lines)
        record=copy.deepcopy(case);record.update(leaves=leaves,zone_meta=meta,uncovered_lines=0)
        result['cases'].append(record)
        comparison(image,lines,leaves,out/(Path(case['file']).stem+'_comparison.png'))
    (out/'REPORT.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print('REZONE',len(result['cases']),'sources; zero cropped text lines')

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for arg in ('report','baseline','engine','out'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();run(a.report,a.baseline,a.engine,a.out)
