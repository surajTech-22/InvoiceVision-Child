"""Run the actual Child adapter and recursive engine on all pinned sources."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import time
import zipfile
import cv2
import numpy as np
from PIL import Image, ImageDraw
from .r147_utf8_evidence import write_utf8, write_json


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def comparison(image,lines,leaves,out):
    source=Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    scale=min(600/source.width,1000/source.height)
    size=(round(source.width*scale),round(source.height*scale))
    canvas=Image.new('RGB',(size[0]*3,size[1]+42),'white');d=ImageDraw.Draw(canvas)
    for i,label in enumerate(('Original source','Actual Paddle CPU text boxes','Logical zones - UNVERIFIED')):
        canvas.paste(source.resize(size),(i*size[0],42));d.text((i*size[0]+5,8),label,fill='black')
    for line in lines:
        b=line['xyxy'];d.rectangle((size[0]+b[0]*scale,42+b[1]*scale,size[0]+b[2]*scale,42+b[3]*scale),outline='#00aaff',width=1)
    for leaf in leaves:
        b=leaf['xyxy'];d.rectangle((2*size[0]+b[0]*scale,42+b[1]*scale,2*size[0]+b[2]*scale-1,42+b[3]*scale-1),outline='#f00050',width=2)
        d.text((2*size[0]+b[0]*scale+3,42+b[1]*scale+3),leaf['id']+' '+leaf['category'],fill='#a00030')
    canvas.save(out)


def run(baseline,overlay,out):
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    os.environ['INVOICEVISION_OCR_DEVICE']='auto'
    adapter=module(overlay/'INVOICE_OCR_PADDLE_ADAPTER_R112.py','actual_child_adapter')
    zones=module(overlay/'INVOICE_OCR_RECURSIVE_ZONES_R109.py','actual_child_zones')
    engine=baseline/'InvoiceVisionChild/Engine'
    cases=[(p.name,p.read_bytes(),'synthetic') for p in sorted((engine/'InvoiceFormatExamples_R2').glob('*.png'))]
    with zipfile.ZipFile(engine/'VISUAL_BENCHMARK_15_PHOTOS.zip') as z:
        cases += [(Path(n).name,z.read(n),'real') for n in sorted(z.namelist()) if n.startswith('images/') and n.lower().endswith(('.jpg','.jpeg','.png'))]
    assert len(cases)==51
    out.mkdir(parents=True,exist_ok=True)
    report={'kind':'ACTUAL_CHILD_PADDLE_AUTO_CPU_FALLBACK_CORPUS','cases':[],
            'packages':{n:importlib.metadata.version(n) for n in ('paddlepaddle','paddleocr','paddlex')},
            'overlay_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in overlay.glob('*.py')},
            'field_accuracy_verified':False,'gpu_hardware_verified':False,'release_authorized':False}
    for name,raw,kind in cases:
        start=time.monotonic();events=[]
        record={'file':name,'kind':kind,'source_sha256':hashlib.sha256(raw).hexdigest()}
        try:
            image=cv2.imdecode(np.frombuffer(raw,np.uint8),1);original=image.copy()
            h,w=image.shape[:2];record.update(source_width=w,source_height=h)
            tsv=adapter.image_to_tsv(image,lambda event,**kw:events.append({'event':event,**kw}))
            assert np.array_equal(image,original),'Source pixels mutated'
            leaves,meta,lines=zones.refine_regions(image,[{'id':'R001','xyxy':[0,0,w,h],'category':'unknown'}],tsv)
            uncovered=[l for l in lines if not any(z['xyxy'][0]<=l['xyxy'][0] and z['xyxy'][1]<=l['xyxy'][1] and z['xyxy'][2]>=l['xyxy'][2] and z['xyxy'][3]>=l['xyxy'][3] for z in leaves)]
            assert not uncovered,'Source text cropped'
            write_utf8(out/(Path(name).stem+'.tsv'),tsv)
            record.update(status='COMPLETED_UNVERIFIED',source_pixels_changed=False,raw_texts=[l['text'] for l in lines],raw_boxes=[l['xyxy'] for l in lines],leaves=leaves,zone_meta=meta,uncovered_lines=0)
            comparison(image,lines,leaves,out/(Path(name).stem+'_comparison.png'))
        except Exception as exc:
            record.update(status='FAILED',error=type(exc).__name__+': '+str(exc))
        record.update(events=events,seconds=round(time.monotonic()-start,3));report['cases'].append(record)
        write_json(out/'REPORT.json',report)
        print(name,record['status'],len(record.get('raw_texts',[])),record['seconds'],record.get('error',''),flush=True)
    models=Path.home()/'.paddlex/official_models'
    report['model_hashes']={str(p.relative_to(models)):hashlib.sha256(p.read_bytes()).hexdigest() for name in ('PP-OCRv5_mobile_det','PP-OCRv5_mobile_rec') for p in (models/name).glob('inference.*')}
    write_json(out/'REPORT.json',report)
    return int(any(c['status']=='FAILED' for c in report['cases']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--overlay',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();raise SystemExit(run(a.baseline,a.overlay,a.out))
