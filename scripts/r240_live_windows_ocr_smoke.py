"""R240: actual offline CPU OCR through staged Child analyze AND approved-region OCR.

This fixture has no customer information. Live Tesseract text extraction must
occur; a source geometry-only synthetic unit test does not meet this gate.
The run never changes installed programs or writes to AAH/Tally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import cv2
import numpy as np

CASE="R240_FAKE_INVOICE_SYNTHETIC_ONLY"
TEXT={
    "invoice_number":"TEST2026A17",
    "supplier":"SYNTHETIC SOURCES LTD",
    "customer":"EXAMPLE BUYER ONLY",
    "item":"PACKAGED SAMPLE",
    "quantity":"20",
    "amount":"1140.00",
}

def _run(args,cwd,timeout=160):
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=timeout,
                     env={**os.environ,"INVOICEVISION_SOURCE_REVIEW_R226":"1"},
                     check=False)
    if p.returncode:
        raise RuntimeError("Actual OCR engine failed, return=%d, stderr=%s, stdout_tail=%s"%
                           (p.returncode,p.stderr[-1600:],p.stdout[-1600:]))
    return p

def _draw(path):
    source=np.full((1450,1030,3),255,dtype=np.uint8)
    line=cv2.LINE_AA
    texts=[
        ("TAX INVOICE",(70,90),1.25,3),
        ("SYNTHETIC SOURCES LTD",(70,150),.85,2),
        ("GSTIN 29AAQFM2308H1Z3",(70,190),.72,2),
        ("INVOICE NO  TEST2026A17",(70,260),.90,2),
        ("INVOICE DATE  17/09/2026",(70,310),.86,2),
        ("BILL TO  EXAMPLE BUYER ONLY",(70,370),.78,2),
        ("ITEM DESCRIPTION",(72,535),.78,2),
        ("QTY",(630,535),.78,2),
        ("RATE",(740,535),.78,2),
        ("AMOUNT",(845,535),.78,2),
        ("PACKAGED SAMPLE",(72,600),.73,2),
        ("20",(640,600),.76,2),
        ("57.00",(745,600),.76,2),
        ("1140.00",(850,600),.76,2),
        ("GRAND TOTAL  1140.00",(535,770),.90,2),
        ("SYNTHETIC TEST: NOT A REAL INVOICE",(70,1240),.67,2),
    ]
    for text,pt,size,thick in texts:
        cv2.putText(source,text,pt,cv2.FONT_HERSHEY_SIMPLEX,size,(0,0,0),thick,line)
    # Printed border cues and grid need to be real source pixels.
    for y in (485,550,630):
        cv2.line(source,(60,y),(980,y),(0,0,0),2,line)
    for x in (60,620,730,840,980):
        cv2.line(source,(x,485),(x,630),(0,0,0),1,line)
    if not cv2.imwrite(str(path),source):
        raise RuntimeError("Cannot create source synthetic invoice")
    return hashlib.sha256(path.read_bytes()).hexdigest(),(source.shape[1],source.shape[0])

def _ensure(cond,message):
    if not cond:raise AssertionError(message)

def run(engine,out,python_executable=None):
    engine=Path(engine).resolve()
    out=Path(out).resolve()
    python_executable=(Path(python_executable).resolve()
                       if python_executable else Path(sys.executable).resolve())
    _ensure(python_executable.is_file(),"Specific offline Python runtime is missing")
    runtime_dir=python_executable.parent.parent
    bundled_runtime=(
        runtime_dir.name.lower()=="runtime" and
        (runtime_dir/"R241_RUNTIME_VERIFICATION.json").is_file() and
        (runtime_dir/"Tesseract"/"tesseract.exe").is_file() and
        (runtime_dir/"Tesseract"/"tessdata"/"eng.traineddata").is_file() and
        os.path.normcase(os.path.abspath(os.environ.get("TESSERACT_EXE",""))) ==
        os.path.normcase(os.path.abspath(str(runtime_dir/"Tesseract"/"tesseract.exe")))
    )
    _ensure((engine/"INVOICE_OCR_CATEGORY_FIRST_R101.py").is_file(),
            "Actual Child category-first entrypoint absent")
    out.mkdir(parents=True,exist_ok=True)
    image=out/"synthetic_invoice.png"
    sha,(width,height)=_draw(image)
    initial=image.read_bytes()
    analyze=out/"synthetic_analysis.zip"
    script=engine/"INVOICE_OCR_CATEGORY_FIRST_R101.py"
    print("R240 invoking actual Child analyze with synthetic source",flush=True)
    _run([str(python_executable),str(script),"analyze",str(image),"--rotation","0",
          "--output",str(analyze)],engine)
    with zipfile.ZipFile(analyze) as archive:
        summary=json.loads(archive.read("SUMMARY.json"))
        folders=[name.split("/")[0] for name in archive.namelist()
                 if name.endswith("/ANALYSIS.json")]
        _ensure(len(folders)==1,"Expected one analyzed synthetic document")
        analysis=json.loads(archive.read(folders[0]+"/ANALYSIS.json"))
        _ensure(summary["status"]=="PROVISIONAL_REVIEW_REQUIRED",
                "Actual analysis was erroneously approved")
        _ensure(summary.get("ocr_engine_candidate")=="TESSERACT",
                "Actual locally available Tesseract runtime was not selected")
        _ensure(not summary.get("accounting_posting_enabled"),"Accounting automatically enabled")
        _ensure(analysis["source_sha256"]==sha,"Original synthetic image hash mismatch")
        _ensure(analysis.get("source_pixels_changed") is False or
                analysis.get("source_pixels_changed") is None,
                "Analyzer mutated original image")
        # R243 must actually execute the two high-resolution views, and
        # preserve all alternative OCR boxes in original source dimensions.
        alt=analysis.get("zone_refinement",{}).get("alternate_multiscale_source_review")
        _ensure(isinstance(alt,dict) and
                alt.get("status")=="SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
                "R243 live Child did not emit multiscale source review")
        variants=alt.get("variants",[])
        print("R243_ACTUAL_SOURCE_VARIANT_STATUS",
              [(v.get("variant"),v.get("status"),v.get("error_type"),
                v.get("source_ocr_words_total")) for v in variants],flush=True)
        _ensure(len(variants)==2 and
                set(v.get("variant") for v in variants)=={"gray_2x","clahe_2x"},
                "R243 two source views missing")
        _ensure(all(v.get("source_ocr_words_total",0)>0 and
                    v.get("source_boxes_are_original_pixels") is True and
                    not v.get("posting_eligible") for v in variants),
                "R243 Tesseract did not produce source-box alternatives")
        for variant in variants:
            for token in variant.get("source_words",[]):
                x0,y0,x1,y1=token["original_source_box"]
                _ensure(0<=x0<x1<=width and 0<=y0<y1<=height,
                        "R243 unscaled OCR rectangle outside original pixels")
        _ensure(not alt["original_OCR_text_overwritten"] and
                alt["accepted_field_values"]==0,
                "R243 wrongly replaced original source or approved a field")
        print("R243_REAL_CHILD_MULTISCALE_SOURCE_BOXES_PASS",
              [v["source_ocr_words_total"] for v in variants],flush=True)
        review=analysis.get("zone_refinement",{}).get("source_row_and_date_review")
        print("R240_SYNTHETIC_ANALYSIS_REVIEW_STATUS",
              {"review_status":review.get("status") if isinstance(review,dict) else None,
               "review_error":review.get("error_type") if isinstance(review,dict) else None,
               "ocr_engine_status":analysis.get("zone_refinement",{}).get("ocr_engine_status"),
               "ocr_error":analysis.get("zone_refinement",{}).get("ocr_error"),
               "raw_ocr_lines":analysis.get("zone_refinement",{}).get("raw_line_count")},
              flush=True)
        _ensure(isinstance(review,dict) and
                review.get("status")=="UNVERIFIED_SOURCE_GEOMETRY_REVIEW_ONLY",
                "Actual staged Child failed to emit source-locked OCR review")
        for field in ("manual_review_queue","field_consistency_review",
                      "source_field_associations","qr_invoice_crosscheck",
                      "source_gstin_checkdigit_review"):
            _ensure(field in review,"Native review missing "+field)
    print("R240 live Child analysis pass, OCR backend TESSERACT",flush=True)
    # Only synthetic image has known rendered field geometry; in production an
    # actual reviewer MUST approve regions. Do NOT auto-approve real invoices.
    reviewed={
        "version":"R112_PADDLE_PRIMARY_RECURSIVE_ZONE_V1",
        "case":CASE,
        "source_sha256":sha,
        "image_size":[width,height],
        "orientation_ccw":0,
        "reviewer_confirmation":
            "I checked approved regions against the original invoice photograph",
        "regions":[
           {"id":"R001","category":"invoice_meta","zone_name":"Synthetic header",
            "xyxy":[63,205,980,332],"approved":True},
           {"id":"R002","category":"item_table","zone_name":"Synthetic source line",
            "xyxy":[64,493,976,625],"approved":True}
        ]}
    reviewfile=out/"synthetic_review.json"
    reviewfile.write_text(json.dumps(reviewed,indent=2),encoding="utf-8")
    recognized=out/"synthetic_approved_ocr.zip"
    print("R240 invoking actual Child approved-region OCR",flush=True)
    _run([str(python_executable),str(script),"ocr","--review",str(reviewfile),
          "--image",str(image),"--output",str(recognized)],engine)
    with zipfile.ZipFile(recognized) as archive:
        result=json.loads(archive.read("CATEGORY_OCR_RESULTS.json"))
        raw=archive.read("RAW_OCR_BY_CATEGORY.txt").decode("utf-8")
        _ensure(result["source_sha256"]==sha,"Approved OCR lost source identity")
        _ensure(len(result["regions"])==2,"Reviewed-region OCR ignored selection")
        _ensure(result.get("accounting_authorized") is False and
                result.get("posting_authorized") is False,
                "Approved zones unlocked accounting posting")
        words=re.sub(r"[^A-Z0-9]","",raw.upper())
        for cue in ("INVOICE","TEST2026A17","PACKAGEDSAMPLE","114000"):
            _ensure(cue in words,"Actual OCR did not recognize clear synthetic source cue: "+cue)
    _ensure(image.read_bytes()==initial,"Actual OCR changed original source photo")
    report={
       "status":"LIVE_OFFLINE_WINDOWS_CHILD_CPU_ANALYZE_AND_APPROVED_OCR_PASS",
       "synthetic_case_only":True,
       "original_photo_sha256":sha,
       "source_pixels_preserved":True,
       "ocr_engine":"TESSERACT",
       "actual_analysis_executed":True,
       "actual_approved_region_ocr_executed":True,
       "clear_source_text_recognized":True,
       "customer_invoices_tested":0,
       "offline_python_runtime_bundled":bool(bundled_runtime),
       "ocr_runtime_execution_kind":(
           "relocated_published_application_runtime" if bundled_runtime else
           "runner_provisioned_local_ocr"),
       "printed_character_accuracy_certified":False,
       "production_installer_authorized":False,
       "accounting_write_permitted":False
    }
    (out/"R240_LIVE_OCR_VERIFICATION.json").write_text(json.dumps(report,indent=2),
                                                      encoding="utf-8")
    print("R240_LIVE_OFFLINE_CHILD_SYNTHETIC_ANALYZE_AND_OCR_PASS",flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--engine",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--python-executable",type=Path,default=None)
    a=p.parse_args()
    run(a.engine,a.out,a.python_executable)
