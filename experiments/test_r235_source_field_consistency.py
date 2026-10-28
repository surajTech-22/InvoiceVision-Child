"""R235 synthetic OCR-source consistency regressions; no customer invoices."""
import importlib.util
import hashlib
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'integration/Engine/INVOICE_OCR_FIELD_CONSISTENCY_R235.py'
s=importlib.util.spec_from_file_location('_r235_source_field_consistency',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def sample(*words):
    return list(words),[[10,20+i*25,250,40+i*25] for i in range(len(words))]

class SourceFieldSafety(unittest.TestCase):
    def test_two_differently_printed_years_are_not_corrected(self):
        t,b=sample('Bill Date 04/09/2024 14:37:09','e-Inv Dt:04/09/2025')
        r=m.inspect(t,b)
        self.assertEqual(r['source_date_strings'],2)
        self.assertEqual(sum(w['issue']=='SOURCE_DATE_YEAR_DIFFERENCE_REQUIRES_CONTEXT'
                             for w in r['warnings']),2)
        self.assertFalse(r['automatic_field_replacement'])
        self.assertFalse(r['posting_eligible'])

    def test_valid_dates_do_not_become_invalid_calendar_errors(self):
        t,b=sample('Invoice 17/09/2026','25/09/2026')
        r=m.inspect(t,b)
        self.assertEqual(r['source_date_strings'],2)
        self.assertEqual(r['warnings_count'],0)

    def test_glued_8_digit_hsn_preserves_exact_ocr_and_box(self):
        t,b=sample('433051090 SOAP BAR AND SHAMPOO')
        r=m.inspect(t,b)
        self.assertEqual(r['warnings'][0]['candidate_hsn_for_review'],'33051090')
        self.assertEqual(r['warnings'][0]['raw_ocr_text'],t[0])
        self.assertEqual(r['warnings'][0]['original_source_box'],b[0])
        self.assertFalse(r['warnings'][0]['source_value_not_replaced'] is False)

    def test_joined_numeric_columns_require_review(self):
        t,b=sample('210.49210.49')
        r=m.inspect(t,b)
        self.assertEqual(r['warnings'][0]['issue'],'TWO_DECIMAL_AMOUNTS_JOINED_IN_OCR')
        self.assertEqual(r['warnings'][0]['two_original_source_substrings'],
                         ['210.49','210.49'])
        self.assertFalse(r['automatic_field_replacement'])

    def test_invalid_calendar_date_is_review_only(self):
        t,b=sample('31/00/2026')
        r=m.inspect(t,b)
        self.assertEqual(r['warnings'][0]['issue'],'INVALID_SOURCE_DATE')
        self.assertFalse(r['posting_eligible'])

    def test_quantity_arithmetic_disagreement_proposes_not_fixes(self):
        r=m.check_line_amount('2','50.00','1000.00')
        self.assertFalse(r['arithmetic_plausible'])
        self.assertEqual(r['quantity_candidate_for_human_review'],'20')
        self.assertFalse(r['original_field_value_replaced'])
        self.assertFalse(r['posting_eligible'])

    def test_rounding_residual_does_not_certify(self):
        r=m.check_line_amount('3','7.33','21.98')
        self.assertTrue(r['arithmetic_plausible'])
        self.assertFalse(r['field_accuracy_certified'])
        self.assertIsNone(r['quantity_candidate_for_human_review'])

    def test_refuse_unmapped_or_negative_values(self):
        for a,b,c in [('2 pcs','30','60'),('-2','30','60'),('2','free','60')]:
            with self.subTest(a=a):
                with self.assertRaises(ValueError):m.check_line_amount(a,b,c)

    def test_malformed_geometry_fails_closed(self):
        with self.assertRaises(ValueError):m.inspect(['HELLO'],[[-1,0,100,20]])
        with self.assertRaises(ValueError):m.inspect(['ONE'],[])

    def test_all_review_fields_explicitly_disable_posting(self):
        t,b=sample('2025/09/04','433051090 PRODUCT','210.49210.49')
        r=m.inspect(t,b)
        self.assertFalse(r['accounting_write_permitted'])
        self.assertFalse(r['field_accuracy_certified'])
        self.assertFalse(r['release_approved'])
        self.assertTrue(all(not w['posting_eligible'] for w in r['warnings']))

if __name__=='__main__':
    unittest.main(verbosity=2)
