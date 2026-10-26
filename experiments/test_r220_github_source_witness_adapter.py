import copy,hashlib,unittest
from r220_github_source_witness_adapter import *

PHOTO=b'original-photo-test-fixture'
def make():
 return {'file':'fixture.jpg','source_sha256':hashlib.sha256(PHOTO).hexdigest(),
  'source_width':902,'source_height':2048,
  'raw_texts':['Amount in Words','RUPEES SIX THOUSAND NINE HUNDRED SIXTY SIX',
      'Net Amount after TAX','0.00','6966,00','6966.0C'],
  'raw_boxes':[[21,1115,133,1139],[138,1128,420,1161],
      [456,1171,620,1199],[808,1158,849,1185],[779,1184,848,1210],[779,1080,848,1105]]}

class SourceWitnessTests(unittest.TestCase):
 def test_real_case_geometry_proposal_only(self):
  c=make();r=propose(c,PHOTO)
  self.assertEqual(r['candidate_for_human_review'],'6966.00')
  self.assertEqual(r['witness_indices'],[2,4,0,1]);self.assertFalse(r['posting_eligible'])
 def test_original_tokens_never_replaced(self):
  c=make();before=copy.deepcopy(c);propose(c,PHOTO);self.assertEqual(c,before)
 def test_refuse_other_invoice_bytes(self):
  with self.assertRaises(ValueError):propose(make(),PHOTO+b'changed')
 def test_ambiguity_blocks(self):
  c=make();c['raw_texts'].append('6966.00');c['raw_boxes'].append([780,1200,848,1220])
  self.assertEqual(propose(c,PHOTO)['status'],'insufficient_witnesses')
 def test_conflicting_amount_blocks(self):
  c=make();c['raw_texts'][4]='6966,01'
  self.assertEqual(propose(c,PHOTO)['status'],'conflicting_printed_witnesses')
 def test_malformed_words_block(self):
  c=make();c['raw_texts'][1]='RUPEES SIX THOUSAND PAISA'
  self.assertNotEqual(propose(c,PHOTO)['status'],'matching_unverified_printed_witnesses')
 def test_money_grammar(self):
  self.assertEqual(money('6,966.00'),Decimal('6966.00'))
  self.assertIsNone(money('6966.0C'))
 def test_words_grammar(self):
  self.assertEqual(words_value('RUPEES FIFTY ONE THOUSAND ONLY'),51000)
 def test_zero_certifications(self):
  r=propose(make(),PHOTO)
  self.assertEqual(r['certified_characters'],0);self.assertFalse(r['accounting_write_permitted'])

if __name__=='__main__':unittest.main(verbosity=2)
