"""R248: source-amount OCR alternatives, geometry and safety tests."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_ITEM_AMOUNT_REREAD_R248.py"
spec=importlib.util.spec_from_file_location("_r248_test",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def row():
    return [{"posting_eligible":False,"source_variants":[
        {"original_amount":"1.75","amount_source_box":[130,65,175,86],
         "posting_eligible":False}]}]

class AmountSourceReread(unittest.TestCase):
    def setUp(self):
        self.image=np.full((250,360,3),180,dtype=np.uint8)
    def test_correlated_alternatives_never_replace_original(self):
        before=self.image.copy()
        result=m.reread(self.image,row(),lambda v,psm:
                        "81.75" if psm==6 else "1.75")
        self.assertEqual(result["source_item_rows_reviewed"],1)
        item=result["row_amount_rereads"][0]
        self.assertEqual(item["original_amount_ocr"],"1.75")
        self.assertEqual({s for v in item["alternate_readings"]
                          for s in v["decimal_candidates_unverified"]},
                         {"81.75","1.75"})
        self.assertFalse(item["candidate_selected_automatically"])
        self.assertEqual(result["accepted_amount_values"],0)
        self.assertFalse(result["posting_eligible"])
        self.assertTrue(np.array_equal(self.image,before))
    def test_negative_source_box_fails_closed(self):
        x=row();x[0]["source_variants"][0]["amount_source_box"]=[-2,10,80,20]
        with self.assertRaises(ValueError):m.reread(self.image,x,lambda v,psm:"9")
    def test_empty_rows_do_not_create_money(self):
        self.assertEqual(m.reread(self.image,[],lambda v,psm:"81.75")
                         ["source_item_rows_reviewed"],0)
    def test_callback_error_no_accepted_amount(self):
        z=m.reread(self.image,row(),lambda v,psm:None)
        self.assertEqual(z["accepted_amount_values"],0)
        self.assertTrue(all(x["status"]=="RECHECK_UNAVAILABLE" for
                            x in z["row_amount_rereads"][0]["alternate_readings"]))
    def test_crop_extends_left_but_inside_original(self):
        z=m.reread(self.image,row(),lambda v,psm:"81.75")
        a,b,c,d=z["row_amount_rereads"][0]["temporary_context_crop_original_coordinates"]
        self.assertLess(a,130)
        self.assertTrue(0<=a<c<=360 and 0<=b<d<=250)
if __name__=="__main__":
    unittest.main(verbosity=2)
