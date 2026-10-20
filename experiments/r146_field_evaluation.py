"""Exact reference-candidate coverage, with alternatives exposed, not accuracy certification."""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from .r143_source_evidence import inspect


def canonical(field,value):
    s=str(value).strip()
    if field=='invoice_date':
        for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d.%m.%Y','%d-%b-%Y','%d/%b/%Y'):
            try:return datetime.strptime(s,fmt).date().isoformat()
            except ValueError:pass
        return s
    if field=='grand_total':
        s=re.sub(r'^(?:INR|Rs\.?|₹)\s*','',s,flags=re.I).replace(',','')
        try:return str(Decimal(s).quantize(Decimal('.01')))
        except InvalidOperation:return s
    return re.sub(r'[^a-z0-9]','',s.casefold())


def run(report,reference,out):
    source=json.loads(report.read_text());ref=json.loads(reference.read_text())
    byfile={Path(f).name:r for r in ref['invoices'] for f in r.get('image_files',[])}
    rows=[];counts=Counter()
    fields={'supplier':'supplier','buyer':'buyer','invoice_number':'invoice_number','date':'invoice_date','grand_total':'grand_total'}
    for case in source['cases']:
        if case['file'] not in byfile or case.get('status')=='FAILED':continue
        candidates=inspect(case,'saved_ocr')['candidates'];expected=byfile[case['file']]
        for refkey,field in fields.items():
            if expected.get(refkey) is None:continue
            relevant=[c for c in candidates if c['field']==field or (field=='supplier' and c['field']=='supplier_fragments')]
            values=sorted({c['raw_value'] for c in relevant})
            matching=[v for v in values if canonical(field,v)==canonical(field,expected[refkey])]
            alternatives=[v for v in values if v not in matching]
            status='matching_candidate_with_alternatives' if matching and alternatives else 'matching_candidate_only' if matching else 'wrong_candidates_only' if values else 'no_candidate'
            counts[status]+=1;counts['reference_slots']+=1
            rows.append({'file':case['file'],'source_sha256':case['source_sha256'],'field':field,'manual_reference':expected[refkey],'candidates':values,'matches':matching,'alternatives':alternatives,'status':status,'evidence':relevant})
    result={'metric':'exact_reference_candidate_coverage_not_accuracy','counts':dict(counts),'rows':rows,'field_accuracy_verified':False,'posting_eligible':False,'normalization':'case/punctuation for identifiers and names; calendar date; decimal amount; no fuzzy or vendor aliases'}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2,ensure_ascii=False));print(json.dumps(result['counts']))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for arg in ('report','reference','out'):p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();run(a.report,a.reference,a.out)
