"""R149: reconcile independent RapidOCR and actual Child PaddleOCR source evidence.

Read-only. Neither OCR agreement nor reference-string presence certifies source
characters, printed physical boxes, semantic correctness or posting permission.
"""
import argparse
from collections import Counter
import hashlib, io
from pathlib import Path
import zipfile
from PIL import Image

from .r143_source_evidence import inspect
from .r146_field_evaluation import canonical
from .r147_utf8_evidence import read_json, write_json
from .r148_saved_corpus_replay import SOURCE_SHA

FIELDS={"supplier":"supplier","buyer":"buyer",
        "invoice_number":"invoice_number","date":"invoice_date",
        "grand_total":"grand_total"}
INVALID=(None,"","REVIEW_REQUIRED")

def run(rapid_report,child_report,source_zip,out):
    source_zip=Path(source_zip);rapid_report=Path(rapid_report);child_report=Path(child_report)
    if hashlib.sha256(source_zip.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise ValueError("Untrusted original source ZIP")
    rapid=read_json(rapid_report)
    child=read_json(child_report)
    if len(rapid["cases"])!=15 or len(child["cases"])!=51:
        raise ValueError("Independent Rapid 15 / actual Child 51 counts required")
    by_rapid={c["file"]:c for c in rapid["cases"]}
    by_child={c["file"]:c for c in child["cases"]}
    if len(by_rapid)!=15 or len(by_child)!=51:raise ValueError("Duplicate source case names")
    with zipfile.ZipFile(source_zip) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read("InvoiceVisionChild/Engine/VISUAL_BENCHMARK_15_PHOTOS.zip"))) as realzip:
            expected=read_json_bytes(realzip.read("ground_truth.json"))
            originals={Path(n).name:realzip.read(n) for n in realzip.namelist()
                       if n.startswith("images/") and n.lower().endswith((".jpg",".jpeg",".png"))}
    if len(originals)!=15 or set(by_rapid)!=set(originals):
        raise ValueError("Exact 15 original source set required")
    manual={Path(s).name:m for m in expected["invoices"] for s in m["image_files"]}
    rows=[];counts=Counter()
    for filename,raw in sorted(originals.items()):
        sha=hashlib.sha256(raw).hexdigest()
        r=by_rapid[filename];p=by_child[filename]
        if r.get("status")!="OCR_COMPLETED_UNVERIFIED" or p.get("status")!="COMPLETED_UNVERIFIED":
            raise ValueError("Engine did not complete source "+filename)
        if sha!=r["source_sha256"] or sha!=p["source_sha256"]:
            raise ValueError("Cross-engine source hash mismatch: "+filename)
        with Image.open(io.BytesIO(raw)) as im:
            for case in (r,p):
                if [case["source_width"],case["source_height"]]!=list(im.size):
                    raise ValueError("Cross-engine image coordinate mismatch: "+filename)
        interpreted=[
            ("rapidocr",inspect(r,"rapidocr",raw)),
            ("actual_child_paddleocr",inspect(p,"actual_child_paddleocr",raw))]
        for ref_field,field in FIELDS.items():
            truth=manual[filename].get(ref_field)
            if truth in INVALID:continue
            proposals=[]
            for engine,result in interpreted:
                for item in result["candidates"]:
                    if item["field"]!=field and not (field=="supplier" and item["field"]=="supplier_fragments"):
                        continue
                    proposals.append({"engine":engine,"value":item["raw_value"],
                        "source_tokens":item["source_tokens"],
                        "source_regions":item["source_regions"],
                        "source_text":item["raw_source_text"],
                        "source_sha256":sha,
                        "source_linked":True,
                        "physically_verified":False,"posting_eligible":False})
            vals=sorted({x["value"] for x in proposals})
            matches=[x for x in proposals if canonical(field,x["value"])==canonical(field,truth)]
            alternatives=[x for x in proposals if canonical(field,x["value"])!=canonical(field,truth)]
            matching_engines=sorted({x["engine"] for x in matches})
            if matches:
                status="MATCH_WITH_ALTERNATIVES" if alternatives else "MATCH_CANDIDATE_ONLY"
            else:
                status="WRONG_CANDIDATES_ONLY" if vals else "NO_CANDIDATE"
            counts[status]+=1;counts["reference_slots"]+=1
            if len(matching_engines)==2:counts["two_engine_reference_match"]+=1
            rows.append({"file":filename,"field":field,"manual_reference":truth,
                         "source_sha256":sha,"status":status,
                         "matching_engine_names":matching_engines,
                         "matching_evidence":matches,"alternatives":alternatives,
                         "posting_eligible":False,"verified_field_mapping":False})
    result={
        "kind":"R149_INDEPENDENT_TWO_CPU_ENGINES_SOURCE_LINKED_REVIEW",
        "source_archive_sha256":SOURCE_SHA,
        "actual_child_report_sha256":hashlib.sha256(child_report.read_bytes()).hexdigest(),
        "independent_rapid_report_sha256":hashlib.sha256(rapid_report.read_bytes()).hexdigest(),
        "original_real_sources":15,"unique_child_corpus_sources":51,
        "counts":dict(counts),"rows":rows,
        "field_accuracy_certified":False,"printed_physical_boxes_certified":False,
        "model_agreement_is_not_ground_truth":True,
        "auto_posting_enabled":False,"release_authorized":False}
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    write_json(out,result)
    print("R149 source hash matched on 15 originals; 2-engine REVIEW only:",dict(counts),flush=True)
    return result

def read_json_bytes(raw):
    import json
    return json.loads(raw.decode("utf-8",errors="strict"))

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("rapid_report","child_report","source_zip","out"):
        parser.add_argument("--"+name.replace("_","-"),type=Path,required=True)
    x=parser.parse_args()
    run(x.rapid_report,x.child_report,x.source_zip,x.out)
