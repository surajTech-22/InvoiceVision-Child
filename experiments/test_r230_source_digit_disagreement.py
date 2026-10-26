"""R230 synthetic safety checks, no customer invoices or cloud OCR."""
import unittest
from experiments.r230_source_digit_disagreement import review
SHA='f'*64
BOX=[10,20,140,42]
class SourceDigitSafety(unittest.TestCase):
    def test_disagreement_never_auto_replaces(self):
        a=review('33051090',['33051000','3011090'],SHA,BOX)
        self.assertEqual(a['status'],'SECOND_ENGINE_CONFLICT_REVIEW')
        self.assertFalse(a['source_text_replaced'])
        self.assertFalse(a['posting_eligible'])
        self.assertEqual(a['source_characters_certified'],0)
    def test_correlated_full_agreement_never_certifies(self):
        a=review('33051090',['33051090','33051090'],SHA,BOX)
        self.assertEqual(a['matching_secondary_variants'],2)
        self.assertEqual(a['source_characters_certified'],0)
        self.assertFalse(a['automatic_value_correction'])
    def test_mixed_agreement_is_a_review_flag(self):
        a=review('33051090',{'a':'33051090','b':'33059040','c':''},SHA,BOX)
        self.assertEqual(a['matching_secondary_variants'],1)
        self.assertEqual(a['conflicting_secondary_variants'],1)
    def test_no_second_engine_ocr(self):
        self.assertEqual(review('33051090',[],SHA,BOX)['status'],'SECOND_ENGINE_NO_READINGS_REVIEW')
    def test_reject_untrusted_non_digit_input(self):
        with self.assertRaises(ValueError):review('Rupees Four Thousand',[],SHA,BOX)
    def test_reject_image_identity_or_geometry_errors(self):
        with self.assertRaises(ValueError):review('33051090',[],'wrong',BOX)
        with self.assertRaises(ValueError):review('33051090',[],SHA,[-1,2,3,4])
    def test_reject_unbounded_variant_stream(self):
        with self.assertRaises(ValueError):review('33051090',['X']*65,SHA,BOX)
    def test_input_collections_never_modified(self):
        v=['33051090'];b=list(BOX);review('33051090',v,SHA,b)
        self.assertEqual(v,['33051090'])
        self.assertEqual(b,BOX)
if __name__=='__main__':unittest.main(verbosity=2)
