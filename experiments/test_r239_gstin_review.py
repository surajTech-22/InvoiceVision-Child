"""R239: independent GSTIN check digit source-review regressions."""
import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('r239',Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_GSTIN_REVIEW_R239.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
class TestGstin(unittest.TestCase):
    def test_valid_source_examples(self):
        for s in ('29AAQFM2308H1Z3','29ABZPB5530G1ZE','29DEZPR3879Q2ZN'):
            with self.subTest(gstin=s):self.assertEqual(g.check_digit(s[:14]),s[-1])
    def test_bad_ocr_letter_detected_and_not_replaced(self):
        t=['GSTIN:29AAOFM2308H1Z3','GSTIN:29AAQFM2308H1Z3']
        b=[[0,0,210,24],[0,35,210,59]]
        result=g.review(t,b)
        self.assertEqual([c['checksum_valid'] for c in result['candidates']],[False,True])
        self.assertEqual(result['checksum_disagreements'],1)
        self.assertEqual(result['approved_gstin_values'],0)
        self.assertFalse(result['posting_eligible'])
        self.assertEqual(t[0],'GSTIN:29AAOFM2308H1Z3')
    def test_metro_invoice_id_not_mistaken_for_gstin(self):
        self.assertEqual(g.review(['29M13100002925281'],[[0,0,160,26]])['total_observed'],0)
    def test_untrusted_source_geometry_rejected(self):
        with self.assertRaises(ValueError):g.review(['29AAQFM2308H1Z3'],[[-1,0,160,25]])
    def test_absent_source_gstin_is_not_approved(self):
        self.assertEqual(g.review(['NO SOURCE GSTIN'],[[1,1,190,30]])['approved_gstin_values'],0)
if __name__=='__main__':unittest.main(verbosity=2)
