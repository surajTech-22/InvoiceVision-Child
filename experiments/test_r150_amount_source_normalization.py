#!/usr/bin/env python3
import unittest
from experiments.r150_amount_source_normalization import parse_source_amount,compare_to_reference
class T(unittest.TestCase):
 def test_colon_keeps_digits(self):self.assertEqual(parse_source_amount(':5181.00')['candidate_exact_decimal'],'5181.00')
 def test_duplicate_colon_invalid(self):self.assertFalse(parse_source_amount('::5181.00')['accepted_numeric_syntax'])
 def test_r149_source_example(self):self.assertTrue(compare_to_reference(':5181.00','5181.00')['exact_amount_candidate_match'])
 def test_do_not_round_close_values(self):self.assertFalse(compare_to_reference('24254.85','24255.00')['exact_amount_candidate_match'])
 def test_never_confuse_amount_and_tax(self):self.assertFalse(parse_source_amount('GST 5181.00')['accepted_numeric_syntax'])
 def test_glued_values_invalid(self):self.assertFalse(parse_source_amount('5181.00 120.00')['accepted_numeric_syntax'])
 def test_no_missing_digits(self):self.assertFalse(compare_to_reference('8840.47','8840.00')['exact_amount_candidate_match'])
 def test_negative_and_thousands(self):self.assertEqual(parse_source_amount('Rs. -1,230.00')['candidate_exact_decimal'],'-1230.00')
 def test_all_outputs_unapproved(self):
  for s in (':5181.00','₹ 8840.00','24254.85','no amount'):
   self.assertFalse(parse_source_amount(s)['posting_eligible'])
if __name__=='__main__':unittest.main(verbosity=2)
