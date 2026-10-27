"""R261 source-printed numeric cells: real geometry, no financial certification."""
import importlib.util
import unittest
from pathlib import Path
import cv2
import numpy as np

p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py"
spec=importlib.util.spec_from_file_location("_r261_columns_test",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def token(s,x,y,width=26):
    return {"original_source_text":s,"original_source_box":[x,y,x+width,y+12]}

def scene(grid=True):
    out=np.full((850,1600,3),255,dtype=np.uint8)
    if grid:
        for y in range(352,493,20):
            cv2.line(out,(200,y),(1460,y),(0,0,0),2)
    return out

def source(*,rate=True,disagreement=False):
    hdr=[token("Product",350,300,76),token("Pcs",750,309,40),
         token("Total",825,309,46),token("PKM",890,309,38),
         token("Base",955,302,45),token("Sch",1020,303,35),
         token("Taxable",1150,302,70),token("GST",1220,305,40),
         token("Rate",955,316,46)]
    if not rate:hdr=[w for w in hdr if w["original_source_text"]!="Rate"]
    body=[]
    for i in range(7):
        y=355+20*i
        body.extend([token(str(20+i),752,y),
                     token(f"{i+1}.50",956,y,40),
                     token(f"{i+100}.25",1161,y,55),
                     token("5",1240,y,10)])
    if disagreement:body.append(token("9.99",956,355,40))
    return [{"variant":"grid_removed_psm11_2x","posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":hdr+body},
            {"variant":"grid_removed_psm6_2x","posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":list(hdr)}]

def bands():
    rows=[]
    for i in range(7):
        y=345+20*i
        rows.append({"source_description_quad":[[300,y],[660,y],[660,y+20],[300,y+20]],
                     "row_number_is_proposal":i+1,
                     "source_values_verified":False,"posting_eligible":False})
    return {"status":"SOURCE_REPEATED_RULING_ROW_BANDS_REVIEW_ONLY",
            "posting_eligible":False,"verified_item_rows":0,"row_bands":rows,
            "physical_divider_y_at_amount_column":[343+20*i for i in range(8)],
            "source_table_header_boxes":{"description":[350,300,426,312],
              "quantity":[750,309,790,321],"amount":[1150,302,1220,314]}}

class R261(unittest.TestCase):
    def test_seven_original_coordinate_rows_are_unapproved(self):
        im=scene();before=im.copy()
        result=m.review(im,bands(),source(),1600,850)
        self.assertTrue(np.array_equal(im,before))
        self.assertEqual(result["source_row_count"],7)
        self.assertEqual(result["certified_financial_fields"],0)
        self.assertEqual(result["certified_item_rows"],0)
        self.assertFalse(result["posting_eligible"])
        lines=result["source_numeric_row_proposals"]
        self.assertEqual([r["original_source_numeric_fields"]["printed_pcs"]
                          ["source_observations"][0]["original_source_text"] for r in lines],
                         [str(20+i) for i in range(7)])
        self.assertTrue(all(len(r["original_source_numeric_fields"]["printed_taxable_amount"]
                                 ["source_observations"])==1 for r in lines))
        self.assertTrue(all(not r["row_completely_verified"] for r in lines))
    def test_disagreeing_source_rate_ocr_is_preserved_not_selected(self):
        r=m.review(scene(),bands(),source(disagreement=True),1600,850)
        variants=[o["original_source_text"] for o in
          r["source_numeric_row_proposals"][0]["original_source_numeric_fields"]
          ["printed_base_rate"]["source_observations"]]
        self.assertEqual(variants,["1.50","9.99"])
        self.assertEqual(r["certified_financial_fields"],0)
    def test_without_actual_rate_heading_no_rate_values(self):
        r=m.review(scene(),bands(),source(rate=False),1600,850)
        self.assertIn("printed_base_rate",r["missing_printed_headers"])
        self.assertNotIn("printed_base_rate",
              r["source_numeric_row_proposals"][0]["original_source_numeric_fields"])
    def test_without_real_rulings_no_numeric_row_assignment(self):
        r=m.review(scene(False),bands(),source(),1600,850)
        self.assertTrue(all(not q["original_source_numeric_fields"]
                         for q in r["source_numeric_row_proposals"]))
    def test_source_word_outside_row_never_assigned(self):
        v=source();v[0]["source_words"].append(token("777.00",955,371,40))
        r=m.review(scene(),bands(),v,1600,850)
        texts=[x["original_source_text"] for x in
            r["source_numeric_row_proposals"][0]["original_source_numeric_fields"]
              ["printed_base_rate"]["source_observations"]]
        self.assertNotIn("777.00",texts)
    def test_malformed_geometry_or_approved_row_fails_closed(self):
        bad=bands();bad["row_bands"][0]["posting_eligible"]=True
        with self.assertRaises(ValueError):
            m.review(scene(),bad,source(),1600,850)
        bad=bands();v=source();v[0]["source_words"][0]["original_source_box"][0]=-4
        with self.assertRaises(ValueError):
            m.review(scene(),bad,v,1600,850)
    def test_unprinted_hsn_does_not_become_a_guessed_column(self):
        r=m.review(scene(),bands(),source(),1600,850)
        self.assertIn("printed_hsn",r["missing_printed_headers"])
        self.assertNotIn("printed_hsn",r["printed_numeric_headers_found"])

if __name__=="__main__":
    unittest.main(verbosity=2)
