"""R245 source-aligned label-value and physical table-column synthetic tests."""
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py"
spec=importlib.util.spec_from_file_location("_child_r245_fields",p)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def token(text,x,y,w=58):
    return {"original_source_text":text,
            "original_source_box":[x,y,x+w,y+20],
            "field_value_verified":False,"posting_eligible":False}
def source(*,conflict=False,missing_headers=False):
    words=[token("INVOICE",35,32),token("NO",114,32,w=32),
           token("TEST2026A17" if not conflict else "TEST2026A18",164,32,w=142),
           token("INVOICE",35,80),token("DATE",116,80,w=47),
           token("17/09/2026",185,80,w=130),
           token("GRAND",34,129),token("TOTAL",100,129),
           token("1140.00",205,129,w=104),
           token("DESCRIPTION",35,255,w=140),
           token("QTY",250,255,w=45),
           token("AMOUNT",400,255,w=90),
           token("PACKAGED",34,310,w=90),token("SAMPLE",133,310,w=77),
           token("20",251,310,w=35),token("1140.00",412,310,w=75)]
    if missing_headers:words=[x for x in words if x["original_source_text"]!="AMOUNT"]
    return words
def fixture(*,other_conflict=False,missing_headers=False):
    return {"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
            "posting_eligible":False,
            "variants":[
                {"variant":"gray_2x","posting_eligible":False,
                 "source_boxes_are_original_pixels":True,
                 "source_words":source(missing_headers=missing_headers)},
                {"variant":"clahe_2x","posting_eligible":False,
                 "source_boxes_are_original_pixels":True,
                 "source_words":source(conflict=other_conflict,
                                       missing_headers=missing_headers)}
            ]}

class SourceAnchoredFieldRows(unittest.TestCase):
    def test_invoice_meta_and_row_fields_kept_separate(self):
        result=mod.propose(fixture(),600,700)
        types=[x["category"] for x in result["field_label_anchored_proposals"]]
        self.assertIn("invoice_number",types)
        self.assertIn("invoice_date",types)
        self.assertIn("net_total",types)
        self.assertGreaterEqual(len(result["table_header_anchored_row_proposals"]),1)
        first=result["table_header_anchored_row_proposals"][0]
        self.assertEqual(first["quantity_original_ocr"],"20")
        self.assertEqual(first["amount_original_ocr"],"1140.00")
        self.assertEqual(first["description_original_ocr"],"PACKAGED SAMPLE")
        self.assertFalse(first["row_complete_certified"])
        self.assertEqual(result["verified_invoice_fields"],0)
        self.assertFalse(result["posting_eligible"])
    def test_conflicting_invoice_identifiers_kept_as_disagreements(self):
        result=mod.propose(fixture(other_conflict=True),600,700)
        ids=[x["candidate_text"] for x in result["field_label_anchored_proposals"]
             if x["category"]=="invoice_number"]
        self.assertEqual(set(ids),{"TEST2026A17","TEST2026A18"})
        self.assertEqual(result["verified_invoice_fields"],0)
    def test_two_line_product_pcs_net_amt_headings(self):
        # Table heading OCR comes from multiple print baselines, including
        # a conservative 'Pes' alias for the heading 'Pcs' and 'Ant' for 'Amt'.
        header=[
            token("Product",90,110,w=95),
            token("Name",189,114,w=55),
            token("Pes",315,123,w=42),
            token("Net",460,128,w=36),
            token("Ant",503,133,w=39),
            token("SAMPLE",90,185,w=85),
            token("BAR",180,188,w=45),
            token("60",317,185,w=28),
            token("164.95",495,192,w=63)
        ]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,
             "variants":[
                 {"variant":"grid_removed_psm11_2x","posting_eligible":False,
                  "source_boxes_are_original_pixels":True,
                  "source_words":list(header)},
                 {"variant":"grid_removed_psm6_2x","posting_eligible":False,
                  "source_boxes_are_original_pixels":True,
                  "source_words":list(header)}
             ]}
        result=mod.propose(src,700,500)
        self.assertEqual(result["row_proposals_count"],2)
        row=result["table_header_anchored_row_proposals"][0]
        self.assertEqual(row["quantity_original_ocr"],"60")
        self.assertEqual(row["amount_original_ocr"],"164.95")
        self.assertFalse(row["row_complete_certified"])
    def test_unanchored_amounts_cannot_be_assumed_final_total(self):
        src=fixture()
        for v in src["variants"]:
            v["source_words"]=[token("PES",315,110),token("NET",460,110),
                               token("ANT",500,110),token("20",317,180),
                               token("1140.00",500,180)]
        self.assertEqual(mod.propose(src,700,500)["row_proposals_count"],0)

    def test_missing_amount_header_blocks_row_proposals(self):
        result=mod.propose(fixture(missing_headers=True),600,700)
        self.assertEqual(result["row_proposals_count"],0)
    def test_unlabeled_number_does_not_become_invoice_field(self):
        f=fixture()
        for v in f["variants"]:
            v["source_words"]=[token("2026X0099",90,40),token("1300.00",210,65)]
        z=mod.propose(f,600,700)
        self.assertEqual(z["field_proposals_count"],0)
        self.assertEqual(z["row_proposals_count"],0)
    def test_invalid_box_rejected_and_source_values_unmodified(self):
        f=fixture()
        t=f["variants"][0]["source_words"][0]
        t["original_source_box"]=[-2,35,90,60]
        with self.assertRaises(ValueError):mod.propose(f,600,700)
    def test_duplicate_view_rejected(self):
        f=fixture();f["variants"][1]["variant"]="gray_2x"
        with self.assertRaises(ValueError):mod.propose(f,600,700)
    def test_numerical_row_must_have_source_description(self):
        f=fixture()
        for v in f["variants"]:
            v["source_words"]=[w for w in v["source_words"] if
                w["original_source_text"] not in ("PACKAGED","SAMPLE")]
        self.assertEqual(mod.propose(f,600,700)["row_proposals_count"],0)
    def test_posting_false_even_if_both_views_agree(self):
        z=mod.propose(fixture(),600,700)
        self.assertFalse(z["accounting_write_permitted"])
        self.assertFalse(z["release_approved"])
        self.assertTrue(all(x["posting_eligible"] is False for x in
                            z["field_label_anchored_proposals"]))
    def test_bounded_word_count_fail_closed(self):
        f=fixture()
        f["variants"][1]["source_words"]=[token("ITEM",10,10)]*601
        with self.assertRaises(ValueError):mod.propose(f,600,700)
if __name__=="__main__":
    unittest.main(verbosity=2)
