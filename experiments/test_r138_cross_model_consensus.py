#!/usr/bin/env python3
"""R138 source-hash and cross-engine disagreement safety tests."""
import unittest
from experiments.r138_cross_model_consensus import fuse

def record(values,sha="same-source-sha"):
    return {"file":"synthetic-evidence.jpg","source_sha256":sha,
      "source_width":1000,"source_height":1000,
      "raw_texts":[s for s,x,y in values],
      "raw_boxes":[[[x,y],[x+max(35,len(s)*8),y],[x+max(35,len(s)*8),y+20],[x,y+20]]
                   for s,x,y in values]}
class R138CrossSafety(unittest.TestCase):
    def test_amount_equal_with_trailing_zero(self):
        a=record([("Grand Total",100,300),("1431",300,300)])
        b=record([("Total",100,300),("1431.00",300,300)])
        x=fuse(a,b)
        self.assertEqual(x["fields"]["grand_total"][0]["support_status"],
                         "CROSS_ENGINE_TEXT_SUPPORTED_UNVERIFIED")
    def test_different_amounts_are_conflict(self):
        a=record([("Grand Total",100,300),("1431",300,300)])
        b=record([("Total",100,300),("1481",300,300)])
        x=fuse(a,b)
        self.assertEqual(x["fields"]["grand_total"][0]["support_status"],
                         "CROSS_ENGINE_TEXT_CONFLICT_REVIEW_REQUIRED")
    def test_source_hash_mismatch_refused(self):
        with self.assertRaises(ValueError):
            fuse(record([("To",20,50)],"hash-a"),record([("To",20,50)],"hash-b"))
    def test_unmatched_model_kept_for_review(self):
        a=record([("Net Payable",100,300),("800.00",300,300)])
        b=record([("Tax Summary",100,600),("100.00",300,600)])
        x=fuse(a,b)
        self.assertEqual(x["fields"]["grand_total"][0]["support_status"],
                         "INDEPENDENT_RECHECK_REQUIRED")
        self.assertFalse(x["posting_eligible"])
    def test_no_field_can_be_posted(self):
        a=record([("Net Payable",100,300),("800.00",300,300)])
        x=fuse(a,a)
        self.assertFalse(x["posting_eligible"])
        self.assertFalse(x["physical_layout_approved"])
        self.assertTrue(all(not t["posting_eligible"] for rows in x["fields"].values() for t in rows))
if __name__=="__main__":unittest.main(verbosity=2)
