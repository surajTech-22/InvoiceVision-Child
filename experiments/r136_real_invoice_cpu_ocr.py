#!/usr/bin/env python3
"""R136 independent CPU recognition evidence on 15 REAL source photographs.
All results are research-only; raw model data retained, no AAH posting.
"""
import hashlib, importlib.util, io, json, re, sys, zipfile
from pathlib import Path
from .r147_utf8_evidence import write_utf8
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'source/INVOICE_OCR_CHILD_R113_R4_R2_VERIFIED_UPDATE.zip'
PIN='ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59'
def norm(s):return re.sub(r'[^a-z0-9]+','',str(s).casefold())
def extract_box(b):
    try:
        v=b.tolist() if hasattr(b,'tolist') else b
        if len(v)==4 and isinstance(v[0],(list,tuple)):
            xs=[p[0] for p in v];ys=[p[1] for p in v]
            return [float(min(xs)),float(min(ys)),float(max(xs)),float(max(ys))]
        if len(v)==4 and all(isinstance(x,(float,int)) for x in v):
            return list(map(float,v))
    except (TypeError,ValueError,IndexError):pass
    return None
def annotate(im, lines, boxes, engine, case):
    sheet=im.copy().convert('RGB')
    d=ImageDraw.Draw(sheet)
    for b in boxes or []:
        q=extract_box(b)
        if q:
            d.rectangle(q,outline=(230,64,74),width=max(1,int(im.width/700)))
    title='OCR boxes / unverified: '+engine+' | '+case
    W=sheet.width
    cap=Image.new('RGB',(W,66),'white')
    ImageDraw.Draw(cap).text((10,16),title,fill=(18,30,55))
    z=Image.new('RGB',(W,sheet.height+66),'white')
    z.paste(cap,(0,0));z.paste(sheet,(0,66))
    return z
def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--engine',choices=['rapidocr','paddleocr'],required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    assert hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()==PIN,'Source ZIP checksum mismatch'
    py=ROOT/'scripts/benchmark-ocr.py'
    spec=importlib.util.spec_from_file_location('benchmark',py)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    reader=module.read_rapid if a.engine=='rapidocr' else module.read_paddle
    output={'engine':a.engine,'status':'INDEPENDENT_REAL_IMAGE_INFERENCE',
            'posting_authorized':False,'physical_boxes_approved':False,
            'source_archive_sha256':PIN,'cases':[]}
    with zipfile.ZipFile(ARCHIVE) as outer:
        pack=outer.read('InvoiceVisionChild/Engine/VISUAL_BENCHMARK_15_PHOTOS.zip')
    with zipfile.ZipFile(io.BytesIO(pack)) as inner:
        truth=json.loads(inner.read('ground_truth.json'))
        refs={}
        for entry in truth.get('invoices',[]):
            for name in entry.get('image_files',[]):
                refs[Path(name).name]=entry
        inputs=sorted(x for x in inner.namelist() if x.startswith('images/') and x.lower().endswith(('.jpg','.jpeg','.png')))
        assert len(inputs)==15, ('Wrong source count',len(inputs))
        for index,name in enumerate(inputs):
            raw=inner.read(name); im=Image.open(io.BytesIO(raw)).convert('RGB')
            outfile=a.out/(Path(name).stem+'_input.jpg')
            outfile.write_bytes(raw)  # exact original compressed bytes; no recompression
            try:
                lines,boxes=reader(outfile)
                lines=list(map(str,lines))
                ref=refs.get(Path(name).name,{})
                joined=norm(' '.join(lines))
                # These are ONLY unlinked string-presence cues; not semantic accuracy.
                checks={}
                for field in ['supplier','buyer','invoice_number','grand_total']:
                    expected=ref.get(field)
                    if expected in (None,'REVIEW_REQUIRED'):continue
                    checks[field]=norm(expected) in joined
                record={'file':Path(name).name,'source_sha256':hashlib.sha256(raw).hexdigest(),
                        'status':'OCR_COMPLETED_UNVERIFIED','ocr_text_lines':len(lines),
                        'reference_string_presence_not_field_accuracy':checks,
                        'raw_texts':lines,'raw_boxes':boxes,
                        'source_width':im.width,'source_height':im.height,
                        'ground_truth_reference_id':ref.get('id'),
                        'posting_eligible':False,'has_verified_geometry':False}
                annotate(im,lines,boxes,a.engine,Path(name).name).save(
                    a.out/(Path(name).stem+'_comparison.png'))
            except Exception as e:
                record={'file':Path(name).name,'source_sha256':hashlib.sha256(raw).hexdigest(),
                        'status':'FAILED','error':type(e).__name__+': '+str(e),
                        'posting_eligible':False}
            output['cases'].append(record)
            write_utf8(a.out/'REPORT.json',json.dumps(output,indent=2,ensure_ascii=False,default=str))
            print(Path(name).name,record['status'],record.get('ocr_text_lines'),flush=True)
    output['num_source_images']=15
    output['completed_inference']=sum(x['status']=='OCR_COMPLETED_UNVERIFIED' for x in output['cases'])
    output['source_based_field_accuracy_certified']=False
    write_utf8(a.out/'REPORT.json',json.dumps(output,indent=2,ensure_ascii=False,default=str))
    return 0 if output['completed_inference']==15 else 1
if __name__=='__main__':sys.exit(main())
