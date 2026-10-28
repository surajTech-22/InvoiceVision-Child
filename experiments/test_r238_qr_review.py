import importlib.util,unittest
from pathlib import Path
import cv2,numpy as np
spec=importlib.util.spec_from_file_location('r238',Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_QR_REVIEW_R238.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)

class TestQrReview(unittest.TestCase):
    def test_synthetic_doc_number(self):
        im=np.full((800,600,3),255,dtype=np.uint8)
        qr=cv2.QRCodeEncoder_create().encode('{"DocNo":"IV-1007"}')
        qr=cv2.resize(qr,(192,192),interpolation=cv2.INTER_NEAREST)
        im[100:292,355:547]=cv2.cvtColor(qr,cv2.COLOR_GRAY2BGR)
        orig=im.copy();result=q.review(im)
        self.assertEqual(result['qr_invoice_id_candidates'],['IV-1007'])
        self.assertTrue(np.array_equal(orig,im))
        self.assertFalse(result['invoice_number_certified'])
        self.assertFalse(result['posting_eligible'])

    def test_unstructured_number_rejected(self):
        self.assertEqual(q._explicit_ids('29M13100002925281'),[])

    def test_nested_key_and_no_irn_guessing(self):
        self.assertEqual(q._explicit_ids('{"data":{"document_number":"ABC/19"}}'),['ABC/19'])
        self.assertEqual(q._explicit_ids('{"Irn":"987654321"}'),[])

    def test_disagreeing_qr_labels_fail_closed(self):
        r=q._result(['{"DocNo":"AAA1"}','{"DocNo":"BBB2"}'],'a'*64)
        self.assertEqual(r['status'],'SOURCE_QR_MULTIPLE_IDS_REVIEW_REQUIRED')
        self.assertFalse(r['release_approved'])

    def test_unreadable_qr_never_posts(self):
        r=q.review(np.full((200,300,3),255,dtype=np.uint8))
        self.assertEqual(r['status'],'SOURCE_QR_UNREADABLE_REVIEW_REQUIRED')
        self.assertEqual(r['qr_invoice_id_candidates'],[])
        self.assertFalse(r['posting_eligible'])

    def test_decoded_personal_information_not_disclosed(self):
        r=q._result(['{"DocNo":"AB12","SellerGstin":"29ABCDE1234F1Z5"}'],'a'*64)
        self.assertNotIn('29ABCDE1234F1Z5',str(r))

if __name__=='__main__':unittest.main(verbosity=2)
