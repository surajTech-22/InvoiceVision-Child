import unittest
from .r143_source_evidence import inspect
from .r141_inline_field_evidence import parse_inline
from .test_r143_continuation import case


class FieldRegression(unittest.TestCase):
    def test_administrative_expiry_and_credit_note_dates_are_not_invoice_dates(self):
        for text in ['DL Exp Date:22-Jun-2027','FSSAI Exp Date:15-May-2027','CN Date:25/09/2026','Expiry Date:04/09/2026']:
            with self.subTest(text=text):
                self.assertFalse([c for c in inspect(case([text]),'cpu')['candidates'] if c['field']=='invoice_date'])

    def test_multiple_fields_keep_original_source_evidence(self):
        text='Invoice No: AB123 Invoice Date: 04/09/2026'
        result=inspect(case([text]),'cpu')['candidates']
        self.assertIn(('invoice_number','AB123'),[(r['field'],r['raw_value']) for r in result])
        self.assertIn(('invoice_date','04/09/2026'),[(r['field'],r['raw_value']) for r in result])
        for r in result:self.assertEqual(r['raw_source_text'],[text]);self.assertEqual(r['source_tokens'],[0])

    def test_inline_invoice_and_credit_note_do_not_share_date_authority(self):
        text='Invoice No: AB123 CN Date: 04/09/2026'
        self.assertFalse([r for r in parse_inline(text) if r['field']=='invoice_date'])

if __name__=='__main__':unittest.main()
