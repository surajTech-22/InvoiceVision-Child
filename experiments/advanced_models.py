#!/usr/bin/env python3
"""Isolated, evidence-preserving document-model comparisons. Does not alter Child."""
from __future__ import annotations
import argparse, importlib.util, json, os, re, sys, time, traceback
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
def norm(x): return re.sub(r'[^a-z0-9]+',' ',str(x).casefold()).strip()
def init_cases(out):
    sp=importlib.util.spec_from_file_location('ivsynthetic', ROOT/'scripts/benchmark-ocr.py')
    mod=importlib.util.module_from_spec(sp); sp.loader.exec_module(mod)
    return mod.generate(out/'images')
def emit(out, payload, code=0):
    out.mkdir(parents=True, exist_ok=True)
    (out/'REPORT.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,default=str),encoding='utf8')
    print(json.dumps({k:v for k,v in payload.items() if k!='cases'},default=str),flush=True)
    return code

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model',required=True,choices=('docling','uie','layoutlmv3','paddleocr-vl','qwen3-vl','pp-chatocrv4'))
    ap.add_argument('--out',type=Path,required=True)
    x=ap.parse_args(); x.out.mkdir(parents=True, exist_ok=True)
    report={'model':x.model,'status':'STARTED','basis':'SYNTHETIC_DOCS_NOT_REAL_CUSTOMER_INVOICES',
        'promoted_to_child':False,'accurate_on_real_invoices':None,'cases':[]}
    t0=time.monotonic()
    try:
        cases=init_cases(x.out)
        if x.model=='docling':
            from docling.document_converter import DocumentConverter
            converter=DocumentConverter()
            for c in cases:
                begin=time.monotonic()
                doc=converter.convert(c['path']).document
                struct=doc.export_to_dict()
                (x.out/(c['name']+'.docling.json')).write_text(json.dumps(struct,default=str),encoding='utf8')
                md=doc.export_to_markdown()
                cue={a:norm(a) in norm(md) for a in c['expected']}
                report['cases'].append({'image':c['name'],'source_sha256':c['sha256'],
                    'seconds':round(time.monotonic()-begin,2),'detected_tables':len(struct.get('tables',[])),
                    'text_items':len(struct.get('texts',[])),'cue_presence':cue,
                    'cue_recall':round(sum(cue.values())/max(len(cue),1),3)})
        elif x.model=='uie':
            from paddlenlp import Taskflow
            engine=Taskflow('information_extraction',model='uie-base-en',
                schema=['Supplier','Buyer','Invoice Number','Invoice Date','Grand Total','Tax Amount'])
            texts=[
                'SUPPLIER: SUNRISE TRADERS. BUYER: GENERAL STORES. Invoice No: INV-0724. Date: 20-10-2026. TOTAL 500.',
                'Sold by MARKET SUPPLIES; Billed to GREEN ENTERPRISES; Ref No CN-104; Dated 20/10/2026; Value 200.',
                'From BLUE SERVICES. Ship To TRADING COMPANY. Invoice # A00168. Invoice Date 18 OCT 2026. Line Total 600.']
            for c,source in zip(cases,texts):
                begin=time.monotonic();pred=engine(source)
                report['cases'].append({'image':c['name'],'source_text':source,
                    'seconds':round(time.monotonic()-begin,2),'prediction':pred})
        elif x.model=='layoutlmv3':
            import torch
            from transformers import AutoProcessor, AutoModelForTokenClassification
            mid='nielsr/layoutlmv3-finetuned-funsd'
            proc=AutoProcessor.from_pretrained(mid,apply_ocr=False)
            model=AutoModelForTokenClassification.from_pretrained(mid).eval()
            label_counts={}
            for c in cases:
                begin=time.monotonic();im=Image.open(c['path']).convert('RGB')
                texts=c['expected']
                # These are deliberately approximate normalized coordinates,
                # not an observation-based word alignment or field ground truth.
                boxes=[[40,40+70*i,700,68+70*i] for i,_ in enumerate(texts)]
                encoding=proc(im,texts,boxes=boxes,return_tensors='pt',truncation=True)
                with torch.no_grad(): z=model(**encoding).logits.argmax(-1)[0].tolist()
                counts={}
                for index in z:
                    label=model.config.id2label[index]
                    counts[label]=counts.get(label,0)+1
                report['cases'].append({'image':c['name'],'seconds':round(time.monotonic()-begin,2),
                     'labels':counts,'note':'FUNSD model labels are NOT invoice field labels; word boxes approximate'})
        elif x.model=='paddleocr-vl':
            from paddleocr import PaddleOCRVL
            model=PaddleOCRVL(device='cpu',use_doc_orientation_classify=False,use_doc_unwarping=False)
            for c in cases[:1]:
                begin=time.monotonic(); output=list(model.predict(input=c['path']))
                for j,obj in enumerate(output):
                    raw=getattr(obj,'json',None)
                    if callable(raw):raw=raw()
                    (x.out/f'{c["name"]}.{j}.raw.json').write_text(json.dumps(raw,default=str),encoding='utf8')
                report['cases'].append({'image':c['name'],'seconds':round(time.monotonic()-begin,2),
                   'pages':len(output),'note':'No validated field or zone accuracy from one synthetic sample'})
        elif x.model=='qwen3-vl':
            import torch
            if not torch.cuda.is_available():
                report.update(status='SKIPPED_NO_GPU',reason='GitHub standard CPU runners do not have CUDA; no >2B model downloaded')
                return emit(x.out,report)
            from transformers import AutoProcessor,AutoModelForImageTextToText
            mid='Qwen/Qwen3-VL-2B-Instruct'
            proc=AutoProcessor.from_pretrained(mid)
            m=AutoModelForImageTextToText.from_pretrained(mid,torch_dtype='auto',device_map='auto')
            im=Image.open(cases[0]['path']).convert('RGB')
            prompts=[{'role':'user','content':[{'type':'image','image':im},{'type':'text',
              'text':'List supplier, buyer and invoice date. Only use visible text and say unknown otherwise.'}]}]
            inp=proc.apply_chat_template(prompts,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to(m.device)
            with torch.no_grad(): gen=m.generate(**inp,max_new_tokens=160,do_sample=False)
            val=proc.batch_decode(gen[:,inp['input_ids'].shape[-1]:],skip_special_tokens=True)[0]
            report['cases'].append({'image':cases[0]['name'],'prediction':val})
        elif x.model=='pp-chatocrv4':
            # Cannot honestly call this end-to-end without an available local LLM.
            from paddleocr import PPChatOCRv4Doc
            report.update(status='SKIPPED_NO_LOCAL_LLM_ENDPOINT',
                reason='PP-ChatOCRv4 requires an authorized, configured LLM endpoint for full document information extraction. Import alone is not an accuracy benchmark.')
            return emit(x.out,report)
        report['status']='COMPLETED_UNVERIFIED_ACCURACY'
    except Exception as exc:
        report.update(status='FAILED',error=f'{type(exc).__name__}: {exc}',
          traceback=traceback.format_exc()[-10000:])
    report['total_seconds']=round(time.monotonic()-t0,2)
    return emit(x.out,report,1 if report['status']=='FAILED' else 0)
if __name__=='__main__':
    sys.exit(main())
