"""R243 synthetic source image multiscale safety tests, never customer OCR."""
import importlib.util
import pathlib
import unittest
import numpy as np

path=pathlib.Path(__file__).resolve().parents[1]/'integration/Engine/INVOICE_OCR_MULTISCALE_REVIEW_R243.py'
spec=importlib.util.spec_from_file_location('r243_multiscale',path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

H=mod.HEADER
def tsv(text='20',box=(100,50,40,24)):
    x,y,w,h=box
    return H+'\n'+'1\t1\t0\t0\t0\t0\t0\t0\t400\t200\t-1\t\n'+(
      '5\t1\t1\t1\t1\t1\t%d\t%d\t%d\t%d\t89\t%s\n'%(x,y,w,h,text))

class MultiscaleReview(unittest.TestCase):
    def setUp(self):
        self.image=np.full((200,300,3),245,dtype=np.uint8)
    def test_original_coordinate_mapping_and_source_immutability(self):
        before=self.image.copy()
        result=mod.review(self.image,lambda _img,psm:tsv(),max_words=4)
        self.assertEqual(len(result['variants']),2)
        for item in result['variants']:
            self.assertEqual(item['source_words'][0]['original_source_box'],[50,25,70,37])
            self.assertEqual(item['source_words'][0]['original_source_text'],'20')
            self.assertFalse(item['posting_eligible'])
            self.assertFalse(item['source_words'][0]['field_value_verified'])
        self.assertFalse(result['release_approved'])
        self.assertFalse(result['original_OCR_text_overwritten'])
        self.assertTrue(np.array_equal(self.image,before))
    def test_hierarchy_rows_not_confused_for_words(self):
        x=mod.source_words(tsv(),300,200)
        self.assertEqual(len(x),1)
        self.assertEqual(x[0]['source_tsv_row_number'],3)
    def test_reject_out_of_frame_source_boxes(self):
        with self.assertRaises(ValueError):
            mod.source_words(tsv(box=(580,20,30,15)),300,200)
    def test_invalid_or_missing_original_header_fails(self):
        with self.assertRaises(ValueError):mod.source_words('non-tsv',300,200)
    def test_bad_variant_remains_unapproved(self):
        report=mod.review(self.image,lambda _img,p:tsv(box=(580,20,30,15)))
        self.assertTrue(all(x['status']=='REVIEW_UNAVAILABLE' for x in report['variants']))
        self.assertFalse(report['posting_eligible'])
    def test_two_views_have_alternative_ink(self):
        v=mod.views(self.image)
        self.assertEqual(set(v),{'gray_2x','clahe_2x'})
        self.assertEqual(v['gray_2x'].shape,(400,600))
    def test_zero_length_bbox_never_corrected(self):
        with self.assertRaises(ValueError):mod.source_words(tsv(box=(100,50,0,24)),300,200)
    def test_refuse_unexpected_scale(self):
        with self.assertRaises(ValueError):mod.source_words(tsv(),300,200,scale=0)
    def test_no_private_data_logged_to_source_file(self):
        d=mod.review(self.image,lambda _img,p:tsv('TEST-SYNTHETIC'))
        self.assertEqual(d['accepted_field_values'],0)
        self.assertTrue(d['source_original_pixels_unchanged'])
if __name__=='__main__':unittest.main(verbosity=2)
