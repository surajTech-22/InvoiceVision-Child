"""R148: audit saved ACTUAL Child OCR report against ORIGINAL source bytes.

No OCR run, no generated text, no acceptance of printed borders or posting.
"""
import argparse
from datetime import datetime
import hashlib
import io
from pathlib import Path
import zipfile

from PIL import Image

from .r143_source_evidence import inspect
from .r146_field_evaluation import run as evaluate, canonical
from .r147_utf8_evidence import read_json, write_json, write_utf8

SOURCE_SHA="ad4720d1037558e637fd42abf8e40bce34b505f6cfa73f29dcc3a67816a9ac59"
RAW_ORIGINAL="03/09/202602:08PM"
EXPECTED="2026-09-03"
SOURCE_FILE="1000258308.jpg"

def run(report_path,source_zip,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    report_path=Path(report_path);source_zip=Path(source_zip)
    source_hash=hashlib.sha256(source_zip.read_bytes()).hexdigest()
    if source_hash!=SOURCE_SHA:raise ValueError("Original baseline source ZIP checksum mismatch")
    report=read_json(report_path)
    if len(report.get("cases",[]))!=51 or len({c["file"] for c in report["cases"]})!=51:
        raise ValueError("51 unique source OCR cases required")
    with zipfile.ZipFile(source_zip) as z:
        originals={}
        for name in z.namelist():
            if name.startswith("InvoiceVisionChild/Engine/InvoiceFormatExamples_R2/") and name.endswith(".png"):
                originals[Path(name).name]=z.read(name)
        inner=z.read("InvoiceVisionChild/Engine/VISUAL_BENCHMARK_15_PHOTOS.zip")
    with zipfile.ZipFile(io.BytesIO(inner)) as iz:
        manual_raw=iz.read("ground_truth.json")
        for name in iz.namelist():
            if name.startswith("images/") and name.lower().endswith((".jpg",".jpeg",".png")):
                originals[Path(name).name]=iz.read(name)
    if len(originals)!=51:raise ValueError("Original corpus source count mismatch")
    for case in report["cases"]:
        name=case["file"]
        if name not in originals or case.get("status")!="COMPLETED_UNVERIFIED":
            raise ValueError("Missing original or unsuccessful OCR case: "+name)
        raw=originals[name]
        if hashlib.sha256(raw).hexdigest()!=case["source_sha256"]:
            raise ValueError("Wrong original pixels source SHA: "+name)
        with Image.open(io.BytesIO(raw)) as im:
            if list(im.size)!=[case["source_width"],case["source_height"]]:
                raise ValueError("Source coordinate extent mismatch: "+name)
        if case.get("source_pixels_changed") is not False or case.get("uncovered_lines")!=0:
            raise ValueError("Unsafe image mutation or cut recognized text: "+name)
    date_case=next(c for c in report["cases"] if c["file"]==SOURCE_FILE)
    if RAW_ORIGINAL not in date_case["raw_texts"]:
        raise ValueError("Required original exact OCR token missing")
    inspected=inspect(date_case,"actual_staged_child_paddle_cpu",originals[SOURCE_FILE])
    relevant=[c for c in inspected["candidates"] if
              c["field"]=="invoice_date" and canonical("invoice_date",c["raw_value"])==EXPECTED
              and RAW_ORIGINAL in c["raw_source_text"]
              and c["source_sha256"]==date_case["source_sha256"]]
    if not relevant:raise ValueError("No source-linked date field recovered from joined date-time OCR")
    if any(c.get("posting_eligible") is not False or c.get("validated_against_pixels") is not False for c in relevant):
        raise ValueError("Unverified date candidate accidentally promoted to posting")
    ref_file=out/"manual_reference_readonly.json"
    write_utf8(ref_file,manual_raw.decode("utf-8"))
    field_file=out/"reference_field_candidate_review.json"
    evaluate(report_path,ref_file,field_file)
    field_report=read_json(field_file)
    result={"status":"SOURCE_LINKED_OCR_REPLAY_NOT_ACCURACY_CERTIFIED",
        "source_count":51,"real_source_count":15,"synthetic_source_count":36,
        "source_archive_sha256":source_hash,
        "actual_child_report_sha256":hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "joined_date_image":SOURCE_FILE,"original_ocr_token":RAW_ORIGINAL,
        "original_source_sha256":date_case["source_sha256"],
        "date_candidate":EXPECTED,"source_linked_date_proposals":relevant,
        "reference_candidate_coverage":field_report["counts"],
        "physical_layout_certified":False,"posting_eligible":False,
        "field_accuracy_verified":False,"production_installer_authorized":False}
    write_json(out/"REPORT.json",result)
    print("Verified 51 original source hashes and dimensions. One joined date source-linked candidate; no posting.")
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    run(a.report,a.source,a.out)
