import copy
import unittest
from r220_github_source_witness_adapter import propose
from test_r220_github_source_witness_adapter import PHOTO, make

class R221WitnessIntegrationTests(unittest.TestCase):
    def test_paise_match_remains_review_only(self):
        c=make()
        c['raw_texts'][1]='RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX AND FIFTY PAISE ONLY'
        c['raw_texts'][4]='6966.50'
        before=copy.deepcopy(c)
        result=propose(c,PHOTO)
        self.assertEqual(result['candidate_for_human_review'],'6966.50')
        self.assertEqual(result['status'],'matching_unverified_printed_witnesses')
        self.assertFalse(result['posting_eligible'])
        self.assertFalse(result['accounting_write_permitted'])
        self.assertEqual(result['approved_training_labels'],0)
        self.assertEqual(result['certified_characters'],0)
        self.assertEqual(c,before)

    def test_invalid_and_conflicting_printed_witnesses(self):
        for words, status in (
            ('RUPEES SIX SIX ONLY','unparseable_words'),
            ('RUPEES SIX THOUSAND NINE HUNDRED SIXTY FIVE ONLY','conflicting_printed_witnesses'),
            ('RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX AND FIFTY PAISE ONLY','conflicting_printed_witnesses'),
        ):
            c=make(); c['raw_texts'][1]=words
            with self.subTest(words=words):
                result=propose(c,PHOTO)
                self.assertEqual(result['status'],status)
                self.assertIsNone(result['candidate_for_human_review'])

    def test_untrusted_bbox_and_page_extent_rejected(self):
        for bad in (float('nan'),float('inf'),float('-inf'),True):
            c=make();c['raw_boxes'][4][0]=bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                propose(c,PHOTO)
        for bad in (float('nan'),float('inf'),0,True):
            c=make();c['source_width']=bad
            with self.subTest(width=bad), self.assertRaises(ValueError):
                propose(c,PHOTO)

    def test_original_hash_provenance_required(self):
        c=make(); c['source_sha256']='0'*64
        with self.assertRaises(ValueError):
            propose(c,PHOTO)

if __name__=='__main__':unittest.main(verbosity=2)
