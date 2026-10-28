"""R270: private-original acceptance auditor, never a release or posting action.

Caller supplies private independently transcribed source fields and exact
source hashes. No customer data is embedded in the public repository.
"""
from __future__ import annotations
import re

_SHA=re.compile(r"[0-9a-f]{64}\Z")
_MANDATORY_ITEM=("description","quantity","amount")

def _rectangle(box,width,height):
    if (not isinstance(box,list) or len(box)!=4
        or any(type(v)!=int for v in box)
        or not (0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height)):
        raise ValueError("Untrusted original coordinate box")
    return box

def _source_overlap(reference,observation):
    ax1,ay1,ax2,ay2=reference
    bx1,by1,bx2,by2=observation
    overlap=max(0,min(ax2,bx2)-max(ax1,bx1))*max(
        0,min(ay2,by2)-max(ay1,by1))
    smallest=min((ax2-ax1)*(ay2-ay1),(bx2-bx1)*(by2-by1))
    return overlap>=.45*smallest

def _check_field(expected,observed,width,height):
    if (not isinstance(expected,dict) or
        not isinstance(expected.get("printed_literal"),str) or
        not expected["printed_literal"].strip() or
        not isinstance(observed,dict) or
        not isinstance(observed.get("original_ocr_literal"),str) or
        observed.get("posting_eligible") is not False):
        return False
    want=_rectangle(expected.get("source_box"),width,height)
    have=_rectangle(observed.get("source_box"),width,height)
    return (expected["printed_literal"]==observed["original_ocr_literal"]
            and _source_overlap(want,have))

def audit(truth,results):
    if (not isinstance(truth,dict) or
        truth.get("status")!="PRIVATE_INDEPENDENT_PRINTED_TRANSCRIPTION_V1" or
        not isinstance(results,dict) or
        results.get("status")!="CHILD_UNAPPROVED_ORIGINAL_SOURCE_REPLAY_V1"):
        raise ValueError("Private original source truth and Child replay required")
    cases=truth.get("cases");observed=results.get("cases")
    expected_number=truth.get("required_case_count")
    if (type(expected_number)!=int or not (1<=expected_number<=50) or
        not isinstance(cases,list) or len(cases)!=expected_number or
        not isinstance(observed,list) or len(observed)!=expected_number):
        raise ValueError("Missing or extra original-source test cases")
    by_id={}
    for r in observed:
        if (not isinstance(r,dict) or
            not isinstance(r.get("case_id"),str) or
            r.get("case_id") in by_id or
            r.get("posting_eligible") is not False or
            r.get("accounting_write_permitted") is not False):
            raise ValueError("Invalid or unsafe observed Child case")
        by_id[r["case_id"]]=r
    seen=set();case_reports=[];total_checked=0;total_failed=0
    for case in cases:
        if (not isinstance(case,dict) or
            not isinstance(case.get("case_id"),str) or
            case["case_id"] in seen or
            case.get("independently_source_transcribed") is not True):
            raise ValueError("Private visual transcription missing or duplicated")
        seen.add(case["case_id"])
        actual=by_id.get(case["case_id"])
        if actual is None:raise ValueError("Missing observed source case")
        sh=case.get("original_image_sha256")
        dim=case.get("source_dimensions")
        if (not isinstance(sh,str) or not _SHA.fullmatch(sh) or
            not isinstance(dim,list) or len(dim)!=2 or
            any(type(v)!=int for v in dim) or
            not (180<=dim[0]<=6000 and 180<=dim[1]<=6000)):
            raise ValueError("Missing source photo hash or dimensions")
        same_source=(actual.get("original_image_sha256")==sh and
                     actual.get("source_dimensions")==dim)
        expected_fields=case.get("document_fields")
        actual_fields=actual.get("document_fields")
        expected_rows=case.get("items")
        actual_rows=actual.get("items")
        excluded=case.get("excluded_unreadable_fields",{})
        if (not isinstance(expected_fields,dict) or
            not isinstance(actual_fields,dict) or
            not isinstance(expected_rows,list) or len(expected_rows)>100 or
            not isinstance(actual_rows,list) or len(actual_rows)>100 or
            not isinstance(excluded,dict) or
            not set(excluded)<={"invoice_number"} or
            any(not isinstance(v,str) or len(v.strip())<8 for v in excluded.values())):
            raise ValueError("Unsafe acceptance source schema or exclusions")
        required_docs=case.get("required_document_fields")
        if (not isinstance(required_docs,list) or not
            all(isinstance(x,str) for x in required_docs) or
            len(required_docs)!=len(set(required_docs)) or
            len(required_docs)>40 or
            not {"invoice_number","invoice_date","net_total"}<=set(required_docs)):
            raise ValueError("Unspecified mandatory printed invoice metadata")
        if (not set(required_docs)<=set(expected_fields)|set(excluded) or
            set(expected_fields)&set(excluded)):
            raise ValueError("Missing document truth or contradictory exclusion")
        required_items=case.get("required_item_fields")
        if (not isinstance(required_items,list) or
            not all(isinstance(x,str) for x in required_items) or
            len(required_items)!=len(set(required_items)) or
            len(required_items)>40 or
            not set(_MANDATORY_ITEM)<=set(required_items)):
            raise ValueError("Missing required description, quantity or amount")
        defects=[];field_checks=0
        if not same_source:defects.append("source_photo_sha_or_dimensions_mismatch")
        if len(expected_rows)!=len(actual_rows):
            defects.append("printed_item_row_count_mismatch")
        for key,value in expected_fields.items():
            field_checks+=1
            if key in excluded:
                defects.append("field_cannot_be_both_expected_and_excluded")
            elif not _check_field(value,actual_fields.get(key),*dim):
                defects.append("incorrect_document_field:"+str(key))
        for idx,reference in enumerate(expected_rows):
            if (not isinstance(reference,dict) or
                not set(case["required_item_fields"])<=set(reference)):
                raise ValueError("Incomplete private independent item truth")
            counterpart=actual_rows[idx] if idx<len(actual_rows) else {}
            if not isinstance(counterpart,dict):counterpart={}
            for key in case["required_item_fields"]:
                field_checks+=1
                if not _check_field(reference[key],counterpart.get(key),*dim):
                    defects.append("item_source_mismatch:"+str(idx+1)+":"+str(key))
        total_checked+=field_checks
        total_failed+=len(defects)
        # Output never includes raw customer OCR strings or expected values.
        case_reports.append({"case_id":case["case_id"],
            "source_hash_matched":same_source,
            "expected_item_rows":len(expected_rows),
            "observed_item_rows":len(actual_rows),
            "source_field_checks":field_checks,
            "mismatch_count":len(defects),
            "mismatch_codes":defects,
            "original_source_complete":not defects})
    if set(by_id)!=seen:raise ValueError("Unaccounted original source observations")
    all_cases_ok=not total_failed
    return {
        "status":("PRIVATE_ORIGINAL_PRINTED_FIELDS_MATCH"
                  if all_cases_ok else "PRIVATE_ORIGINAL_SOURCE_MISMATCH"),
        "case_reports":case_reports,
        "checked_original_fields":total_checked,
        "failed_checks":total_failed,
        "all_originals_exactly_matched":all_cases_ok,
        "verified_release_build_or_rollback":False,
        "production_release_authorized":False,
        "accounting_write_permitted":False,
        "posting_eligible":False}
