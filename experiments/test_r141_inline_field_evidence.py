#!/usr/bin/env python3
import unittest
from experiments.r141_inline_field_evidence import parse_inline
class EvidenceTests(unittest.TestCase):
 def values(self,s,field):
    return [x['raw_value'] for x in parse_inline(s) if x['field']==field]
 def test_supplier(self):self.assertEqual(self.values('Supplier: Sri Rama Enterprises','supplier'),['Sri Rama Enterprises'])
 def test_buyer(self):self.assertEqual(self.values('Bill To: Balaji Trading Co.','buyer'),['Balaji Trading Co.'])
 def test_invoice_number(self):self.assertEqual(self.values('Bill No: E55409','invoice_number'),['E55409'])
 def test_invoice_date_2026(self):self.assertEqual(self.values('Date: 04/09/2026 14:37:09','invoice_date'),['04/09/2026'])
 def test_net_payable(self):self.assertEqual(self.values('Net Payable: INR 13365','grand_total'),['INR 13365'])
 def test_tax_total_rejected(self):self.assertFalse(self.values('Total GST: 180.00','grand_total'))
 def test_discount_rejected(self):self.assertFalse(self.values('Discount Total: 75.00','grand_total'))
 def test_address_rejected(self):self.assertFalse(self.values('Bill To: State: Karnataka','buyer'))
 def test_missing_date_not_guessed(self):self.assertFalse(self.values('Date: illegible','invoice_date'))
 def test_tax_invoice_not_buyer(self):self.assertFalse(self.values('To: Tax Invoice','buyer'))
 def test_never_post(self):
    for c in parse_inline('Grand Total: 1430.00'):self.assertFalse(c['posting_eligible'])
if __name__=="__main__":unittest.main(verbosity=2)
