#!/usr/bin/env python3
import importlib.util, pathlib, unittest
p=pathlib.Path(__file__).parent/"r138_field_evidence.py"
spec=importlib.util.spec_from_file_location("r138",p)
m=importlib.util.module_from_spec(spec)
import sys
sys.modules["r138"]=m
spec.loader.exec_module(m)

def record(values):
    return {"file":"synthetic-control.png","source_sha256":"fixed-test-hash",
      "source_width":1000,"source_height":1200,
      "raw_texts":[a for a,x,y in values],
      "raw_boxes":[[[x,y],[x+max(30,len(a)*9),y],[x+max(30,len(a)*9),y+24],[x,y+24]] for a,x,y in values]}

class ReviewOnlySafety(unittest.TestCase):
 def test_currency_preserves_digits(self):
    self.assertEqual(m.amount("1431"),1431.0)
    self.assertEqual(m.amount(":5181.00"),5181.0)
    self.assertIsNone(m.amount("Grand Total"))
 def test_from_to(self):
    x=m.reconstruct(record([("From",20,350),("GENERAL ENTERPRISES",30,377),("To",430,350),("BUYER TRADING",440,377)]))
    self.assertEqual(x["fields"]["supplier"][0]["value"],"GENERAL ENTERPRISES")
    self.assertEqual(x["fields"]["buyer"][0]["value"],"BUYER TRADING")
 def test_signature_never_supplier(self):
    x=m.reconstruct(record([("For GENERAL ENTERPRISES",430,900),("Authorised Signatory",400,930)]))
    self.assertFalse(x["fields"]["supplier"])
 def test_document_title_not_buyer(self):
    x=m.reconstruct(record([("To",50,300),("Tax Invoice",70,335),("ORIGINAL FOR RECIPIENT",50,352)]))
    self.assertFalse(x["fields"]["buyer"])
 def test_total_excludes_savings_and_tax(self):
    x=m.reconstruct(record([("Total Savings",150,450),("1000.00",290,450),
        ("Grand Total",500,780),("1431",700,780),("77.38",450,780)]))
    self.assertEqual([a["value"] for a in x["fields"]["grand_total"]],["1431"])
 def test_invoice_number_not_date(self):
    x=m.reconstruct(record([("INVOICE NO:",100,120),("ABC123",250,120),("INVOICE DATE:",100,152),("29-Aug-2026",250,152)]))
    self.assertEqual(x["fields"]["invoice_number"][0]["value"],"ABC123")
 def test_explicitly_unverified(self):
    x=m.reconstruct(record([("TAX INVOICE",40,60),("2026-10-20",200,300)]))
    self.assertFalse(x["posting_eligible"])
    self.assertFalse(x["physical_boundaries_verified"])
 def test_header_pair_without_names_dictionary(self):
    x=m.reconstruct(record([("SUNDAE",40,60),("Cash and Carry India Ltd.",50,91)]))
    self.assertIn("SUNDAE Cash and Carry India Ltd.",[a["value"] for a in x["fields"]["supplier_fragments"]])
 def test_no_overwrite_of_raw_text(self):
    d=record([("To",40,300),("BALAJI TRDING CO",50,325)])
    before=list(d["raw_texts"]);m.reconstruct(d)
    self.assertEqual(before,d["raw_texts"])
if __name__=="__main__":unittest.main(verbosity=2)
