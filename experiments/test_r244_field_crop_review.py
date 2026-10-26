"""R244 synthetic uncertainty-triggered printed source crop OCR safety tests."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

source=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_FIELD_CROP_REVIEW_R244.py"
spec=importlib.util.spec_from_file_location("_r244_crop_source_review",source)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
HEAD="\t".join(m.HEADER)
def tsv(conf=35,text="2"):
    return HEAD+"\r\n"+(
        "1\t1\t0\t0\t0\t0\t0\t0\t300\t200\t-1\t\r\n"
        "5\t1\t1\t1\t1\t1\t110\t44\t20\t18\t%s\t%s\r\n"%(conf,text)
    )

class FieldCropReview(unittest.TestCase):
    def setUp(self):
        self.image=np.full((200,300,3),255,dtype=np.uint8)
    def test_uncertain_number_priority_and_source_pixel_protection(self):
        before=self.image.copy()
        z=m.review(self.image,tsv(),lambda _crop,psm:"20")
        self.assertEqual(z["source_tokens_selected"],1)
        item=z["review_items"][0]
        self.assertEqual(item["raw_source_text"],"2" if len("2")>=2 else item["raw_source_text"])
        self.assertEqual(len(item["reread_observations"]),4)
        self.assertFalse(z["release_approved"])
        self.assertFalse(z["posting_eligible"])
        self.assertTrue(np.array_equal(before,self.image))
    def test_numeric_source_recheck_candidate_bounded(self):
        words=m.uncertain_tokens(tsv(text="2x"),300,200)
        self.assertEqual(words[0]["source_box"],[110,44,130,62])
        self.assertEqual(words[0]["raw_source_text"],"2x")
    def test_good_confidence_skipped(self):
        self.assertEqual(m.uncertain_tokens(tsv(conf=99,text="200"),300,200),[])
    def test_source_tsv_outside_image_fails_closed(self):
        with self.assertRaises(ValueError):
            m.uncertain_tokens(tsv(text="999").replace("\t110\t44\t","\t290\t44\t"),300,200)
    def test_missing_header_refused(self):
        with self.assertRaises(ValueError):
            m.uncertain_tokens("bad TSV",300,200)
    def test_backend_disagreement_never_auto_corrects(self):
        reads=lambda _crop,psm:("20" if psm==7 else "30")
        z=m.review(self.image,tsv(text="2x"),reads)
        self.assertFalse(z["review_items"][0]["field_value_certified"])
        self.assertEqual(z["accepted_field_values"],0)
        self.assertEqual({x["reading"] for x in z["review_items"][0]["reread_observations"]},{"20","30"})
    def test_source_zero_crops_do_not_escape_boundary(self):
        s=tsv(text="3x").replace("\t110\t44\t","\t0\t0\t")
        z=m.review(self.image,s,lambda _crop,_psm:"33")
        a,b,c,d=z["review_items"][0]["reread_original_source_crop"]
        self.assertEqual(a,0);self.assertEqual(b,0)
        self.assertLessEqual(c,300);self.assertLessEqual(d,200)
    def test_maximum_candidate_limit_protects_runtime(self):
        s=HEAD+"\n"+"".join(
            f"5\t1\t1\t1\t1\t{i+1}\t10\t{10+i*15}\t30\t12\t28\tA{i}\n" for i in range(8))
        z=m.uncertain_tokens(s,300,200,max_candidates=3)
        self.assertEqual(len(z),3)
    def test_invalid_reader_does_not_approve(self):
        z=m.review(self.image,tsv(text="2x"),lambda _crop,_psm:None)
        self.assertEqual(z["source_tokens_selected"],1)
        self.assertTrue(all(x["status"]=="RECHECK_UNAVAILABLE" for x in z["review_items"][0]["reread_observations"]))
        self.assertFalse(z["posting_eligible"])
if __name__=="__main__":unittest.main(verbosity=2)
