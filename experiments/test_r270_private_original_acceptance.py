"""R270 private-source gate: synthetic proof without customer data."""
import importlib.util
import copy
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[0]/"r270_private_original_acceptance.py"
spec=importlib.util.spec_from_file_location("_r270_private_acceptance",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def pair():
    truth={"status":"PRIVATE_INDEPENDENT_PRINTED_TRANSCRIPTION_V1",
           "required_case_count":3,"cases":[]}
    result={"status":"CHILD_UNAPPROVED_ORIGINAL_SOURCE_REPLAY_V1","cases":[]}
    def expected(text,box):
        return {"printed_literal":text,"source_box":box}
    def observation(text,box):
        return {"original_ocr_literal":text,"source_box":box,
                "posting_eligible":False}
    for i in range(3):
        h=chr(ord("a")+i)*64
        field={"invoice_date":expected("10/11/2026",[20,50,115,72]),
               "net_total":expected("120.00",[350,700,445,730])}
        if i!=2:
            field["invoice_number"]=expected("SYN-000"+str(i),
                                             [200,50,310,75])
        item={"description":expected("SAMPLE PACKAGE",[30,250,180,275]),
              "quantity":expected("2",[235,250,260,275]),
              "amount":expected("120.00",[350,250,445,275])}
        found_field={key:observation(x["printed_literal"],x["source_box"])
                     for key,x in field.items()}
        found_item={key:observation(x["printed_literal"],x["source_box"])
                    for key,x in item.items()}
        truth["cases"].append({
            "case_id":f"synthetic_{i}","original_image_sha256":h,
            "source_dimensions":[600,800],
            "independently_source_transcribed":True,
            "document_fields":field,
            "required_document_fields":["invoice_number","invoice_date","net_total"],
            "required_item_fields":["description","quantity","amount"],
            "excluded_unreadable_fields":(
                {"invoice_number":"Source identifier is genuinely unreadable"}
                if i==2 else {}),
            "items":[item]})
        result["cases"].append({
            "case_id":f"synthetic_{i}","original_image_sha256":h,
            "source_dimensions":[600,800],
            "accounting_write_permitted":False,
            "posting_eligible":False,
            "document_fields":found_field,
            "items":[found_item]})
    return truth,result

class PrivatePrintedAcceptance(unittest.TestCase):
    def test_all_three_source_verified_still_cannot_release_setup(self):
        t,r=pair();out=m.audit(t,r)
        self.assertTrue(out["all_originals_exactly_matched"])
        self.assertEqual(out["checked_original_fields"],17)
        self.assertEqual(out["failed_checks"],0)
        self.assertFalse(out["production_release_authorized"])
        self.assertFalse(out["accounting_write_permitted"])
        self.assertFalse(out["verified_release_build_or_rollback"])

    def test_one_digit_or_source_position_error_blocks_acceptance(self):
        t,r=pair()
        r["cases"][1]["items"][0]["quantity"]["original_ocr_literal"]="3"
        d=m.audit(t,r)
        self.assertFalse(d["all_originals_exactly_matched"])
        self.assertGreater(d["failed_checks"],0)
        t,r=pair()
        r["cases"][1]["items"][0]["amount"]["source_box"]=[20,30,90,50]
        self.assertFalse(m.audit(t,r)["all_originals_exactly_matched"])

    def test_one_missing_item_or_photo_hash_blocks_all(self):
        t,r=pair()
        r["cases"][0]["items"]=[]
        d=m.audit(t,r)
        self.assertFalse(d["all_originals_exactly_matched"])
        self.assertIn("printed_item_row_count_mismatch",d["case_reports"][0]["mismatch_codes"])
        t,r=pair()
        r["cases"][2]["original_image_sha256"]="f"*64
        self.assertFalse(m.audit(t,r)["all_originals_exactly_matched"])

    def test_no_unapproved_source_truth_or_arbitrary_exclusion(self):
        t,r=pair()
        t["cases"][1]["independently_source_transcribed"]=False
        with self.assertRaises(ValueError):m.audit(t,r)
        t,r=pair()
        t["cases"][0]["excluded_unreadable_fields"]={"net_total":"Ignore entire total printed"}
        with self.assertRaises(ValueError):m.audit(t,r)
        t,r=pair()
        t["cases"][0]["required_item_fields"]=["description","amount"]
        with self.assertRaises(ValueError):m.audit(t,r)
        t,r=pair()
        del t["cases"][0]["document_fields"]["invoice_number"]
        with self.assertRaises(ValueError):m.audit(t,r)
        t,r=pair()
        t["cases"][0]["required_document_fields"]=["invoice_date","net_total"]
        with self.assertRaises(ValueError):m.audit(t,r)

    def test_unauthorized_accounting_write_or_missing_case_refused(self):
        t,r=pair()
        r["cases"][0]["accounting_write_permitted"]=True
        with self.assertRaises(ValueError):m.audit(t,r)
        t,r=pair()
        r["cases"].pop()
        with self.assertRaises(ValueError):m.audit(t,r)

    def test_audit_summary_does_not_expose_source_literals(self):
        t,r=pair()
        report=str(m.audit(t,r))
        self.assertNotIn("SAMPLE PACKAGE",report)
        self.assertNotIn("120.00",report)
        self.assertNotIn("10/11/2026",report)

if __name__=="__main__":
    unittest.main(verbosity=2)
