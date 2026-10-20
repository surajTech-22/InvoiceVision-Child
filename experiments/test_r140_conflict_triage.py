#!/usr/bin/env python3
"""R140 safety regression: no phantom field approvals or altered originals."""
import unittest
from experiments.r140_conflict_triage import analyze, classify

def record(s, sha="same"):
    return {"file":"controlled_test.png","source_sha256":sha,
      "raw_texts":[s],"raw_boxes":[[[10,20],[190,20],[190,44],[10,44]]]}

class T(unittest.TestCase):
    def test_invoice_date_disagreement_is_not_silently_corrected(self):
        self.assertEqual(classify("04/09/2025","04/09/2026"),"DATE_SHAPED_CONFLICT")
    def test_money_shaped_disagreement(self):
        self.assertEqual(classify("1,430.00","1,480.00"),"DECIMAL_OR_CURRENCY_SHAPED_CONFLICT")
    def test_product_name_not_money(self):
        self.assertEqual(classify("SURFXL 60G","SURFXL 80G"),"MIXED_TEXT_OR_IDENTIFIER_DIGIT_CONFLICT")
    def test_unlabeled_integer_not_accounting_amount(self):
        self.assertEqual(classify("0826","0825"),"BARE_NUMERIC_TOKEN_CONFLICT_UNCLASSIFIED")
    def test_format_only_is_not_numeric_conflict(self):
        self.assertEqual(classify("1,430.00","1430.00"),"NO_DIGIT_DISAGREEMENT")
    def test_reject_source_hash_mismatch(self):
        with self.assertRaises(ValueError):analyze(record("100","x"),record("101","y"))
    def test_preserve_readings_and_prohibit_posting(self):
        a=record("1,430.00");b=record("1,480.00")
        before=list(a["raw_texts"]);out=analyze(a,b)
        self.assertEqual(a["raw_texts"],before)
        self.assertEqual(out["conflicts"][0]["rapid_text"],"1,430.00")
        self.assertEqual(out["conflicts"][0]["paddle_text"],"1,480.00")
        self.assertFalse(out["conflicts"][0]["transcription_verified"])
        self.assertFalse(out["conflicts"][0]["posting_eligible"])
        self.assertFalse(out["automatic_posting_enabled"])
    def test_no_geometry_promotion(self):
        r=analyze(record("100"),record("101"))
        self.assertFalse(r["conflicts"][0]["physical_border_verified"])
if __name__=="__main__":unittest.main(verbosity=2)
