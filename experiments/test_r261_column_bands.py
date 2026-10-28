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

    def test_r262_original_source_numeric_cell_crop_is_not_certified(self):
        im=scene();before=im.copy();seen=[]
        def reader(crop,psm):
            self.assertEqual(psm,7)
            seen.append(tuple(crop.shape))
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t2\t2\t11\t8\t52\t12.50\n")
        data=m.review(im,bands(),source(),1600,850,reader=reader)
        self.assertTrue(seen)
        self.assertTrue(np.array_equal(im,before))
        self.assertEqual(data["certified_item_rows"],0)
        for row in data["source_numeric_row_proposals"]:
            for field in row["original_source_numeric_fields"].values():
                self.assertEqual(len(field["source_crop_ocr_alternatives"]),1)
                evidence=field["source_crop_ocr_alternatives"][0]
                self.assertEqual(evidence["ocr_literal_text"],"12.50")
                self.assertEqual(evidence["source"],"TEMP_ORIGINAL_NUMERIC_CELL_PSM7")
                self.assertEqual(len(evidence["original_crop_sha256"]),64)
                self.assertFalse(evidence["source_text_verified"])
                self.assertFalse(evidence["posting_eligible"])
        self.assertFalse(data["accounting_write_permitted"])

    def test_r262_blank_crop_uses_distinct_psm6_unverified_fallback(self):
        psms=[]
        def reader(crop,psm):
            psms.append(psm)
            header=("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
            if psm==7:return header
            return header+"5\t1\t1\t1\t1\t1\t1\t1\t20\t12\t50\tRECOVERED\n"
        data=m.review(scene(),bands(),source(),1600,850,reader=reader)
        self.assertGreater(psms.count(6),0)
        for row in data["source_numeric_row_proposals"]:
            for cell in row["original_source_numeric_fields"].values():
                evidence=cell["source_crop_ocr_alternatives"]
                self.assertEqual([o["source"] for o in evidence],
                  ["TEMP_ORIGINAL_NUMERIC_CELL_PSM7",
                   "TEMP_PADDED_ORIGINAL_NUMERIC_CELL_PSM7",
                   "TEMP_ORIGINAL_NUMERIC_CELL_PSM6_FALLBACK"])
                self.assertEqual(evidence[2]["ocr_literal_text"],"RECOVERED")
                self.assertEqual(evidence[0]["original_crop_sha256"],
                                 evidence[2]["original_crop_sha256"])
                self.assertTrue(evidence[1]["may_contain_adjacent_source_ink"])
                self.assertFalse(evidence[1]["source_text_verified"])
                self.assertFalse(evidence[2]["posting_eligible"])

    def test_r262_malformed_or_unbounded_crop_tsv_fails_closed(self):
        for reader in (lambda _crop,_psm:"bad-header\nvalue",
                       lambda _crop,_psm:"x"*100001):
            with self.assertRaises(ValueError):
                m.review(scene(),bands(),source(),1600,850,reader=reader)
        with self.assertRaises(ValueError):
            m.review(scene(),bands(),source(),1600,850,reader="not callable")

    def test_r263_pcs_not_discount_per_piece_when_source_column_bracketed(self):
        v=source()
        for variant in v:
            ws=variant["source_words"]
            ws.extend([token("CS)",680,309,35),
                       token("/Pes",1390,309,48)])
        out=m.review(scene(),bands(),v,1600,850)
        self.assertIn("printed_pcs",out["printed_numeric_headers_found"])
        self.assertNotIn("printed_pcs",out["ambiguous_printed_headers"])
        x=out["column_geometry"]["printed_pcs"]["heading_x"]
        self.assertLess(x,800)
        self.assertGreater(x,700)
        self.assertFalse(out["posting_eligible"])

    def test_r263_two_bracketed_quantity_headings_remain_ambiguous(self):
        v=source()
        for variant in v:
            variant["source_words"].extend(
              [token("CS",680,309,35),token("Pcs",790,309,40),
               token("Total",850,309,40),
               token("CS",880,309,35),token("Pcs",940,309,40),
               token("Total",990,309,48)])
        out=m.review(scene(),bands(),v,1600,850)
        self.assertIn("printed_pcs",out["ambiguous_printed_headers"])
        self.assertNotIn("printed_pcs",out["printed_numeric_headers_found"])
        self.assertEqual(out["certified_item_rows"],0)

    def test_r264_noisy_nonempty_original_crop_gets_independent_fallback(self):
        called=[]
        def reader(_crop,psm):
            called.append(psm)
            header=("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
            value="12.50|" if psm==7 else "12.50"
            return header+f"5\t1\t1\t1\t1\t1\t1\t1\t20\t10\t80\t{value}\n"
        result=m.review(scene(),bands(),source(),1600,850,reader=reader)
        first=result["source_numeric_row_proposals"][0]
        pcs=first["original_source_numeric_fields"]["printed_pcs"]
        self.assertEqual(len(pcs["source_crop_ocr_alternatives"]),3)
        self.assertEqual([q["ocr_literal_text"] for q in pcs["source_crop_ocr_alternatives"]],
                         ["12.50|","12.50|","12.50"])
        self.assertTrue(pcs["source_crop_ocr_alternatives"][1]
                        ["may_contain_adjacent_source_ink"])
        self.assertFalse(pcs["source_crop_ocr_alternatives"][1]["source_text_verified"])
        self.assertIn(6,called)
        self.assertEqual(result["certified_financial_fields"],0)
        self.assertFalse(result["release_approved"])

    def test_r265_wider_source_crop_has_bounded_separate_hash(self):
        dimensions=[]
        def reader(crop,psm):
            dimensions.append((crop.shape[1],psm))
            hdr=("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n")
            word="2|" if psm==7 else "2"
            return hdr+f"5\t1\t1\t1\t1\t1\t1\t1\t9\t9\t70\t{word}\n"
        im=scene();unchanged=im.copy()
        r=m.review(im,bands(),source(),1600,850,reader=reader)
        first=r["source_numeric_row_proposals"][0]["original_source_numeric_fields"]["printed_pcs"]
        a,b,c=first["source_crop_ocr_alternatives"]
        self.assertEqual(b["source"],"TEMP_PADDED_ORIGINAL_NUMERIC_CELL_PSM7")
        self.assertLess(b["original_source_pixel_rect"][0],a["original_source_pixel_rect"][0])
        self.assertGreater(b["original_source_pixel_rect"][2],a["original_source_pixel_rect"][2])
        self.assertNotEqual(a["original_crop_sha256"],b["original_crop_sha256"])
        self.assertEqual(c["original_crop_sha256"],a["original_crop_sha256"])
        self.assertTrue(np.array_equal(im,unchanged))
        self.assertFalse(r["accounting_write_permitted"])

    def test_r267_source_vertical_borders_offer_unverified_crop(self):
        base=m.review(scene(),bands(),source(),1600,850)
        col=base["column_geometry"]["printed_pcs"]
        left=int(col["left"])+1
        right=int(col["right"])-1
        self.assertGreater(right-left,14)
        img=scene()
        cv2.line(img,(left,337),(left,505),(0,0,0),2)
        cv2.line(img,(right,337),(right,505),(0,0,0),2)
        original=img.copy()
        def reader(_crop,psm):
            h="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
            return h+"5\t1\t1\t1\t1\t1\t2\t2\t12\t9\t35\t12.5|\n"
        result=m.review(img,bands(),source(),1600,850,reader=reader)
        field=result["source_numeric_row_proposals"][0]["original_source_numeric_fields"]["printed_pcs"]
        variants=field["source_crop_ocr_alternatives"]
        interior=[e for e in variants if e["source"]=="TEMP_VERTICAL_RULING_INTERIOR_PSM7"]
        self.assertEqual(len(interior),1)
        box=interior[0]["original_source_pixel_rect"]
        self.assertGreater(box[0],variants[0]["original_source_pixel_rect"][0])
        self.assertLess(box[2],variants[0]["original_source_pixel_rect"][2])
        self.assertEqual(len(interior[0]["source_vertical_rule_x"]),2)
        self.assertNotEqual(interior[0]["original_crop_sha256"],variants[0]["original_crop_sha256"])
        self.assertFalse(interior[0]["posting_eligible"])
        self.assertFalse(interior[0]["source_text_verified"])
        self.assertEqual(result["certified_financial_fields"],0)
        self.assertTrue(np.array_equal(img,original))

    def test_r267_single_vertical_border_does_not_justify_trimming(self):
        base=m.review(scene(),bands(),source(),1600,850)
        col=base["column_geometry"]["printed_pcs"]
        img=scene()
        x=int(col["left"])+1
        cv2.line(img,(x,337),(x,505),(0,0,0),2)
        def reader(_crop,_psm):
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t1\t1\t15\t9\t35\t12.5|\n")
        result=m.review(img,bands(),source(),1600,850,reader=reader)
        for row in result["source_numeric_row_proposals"]:
            for cell in row["original_source_numeric_fields"].values():
                self.assertFalse(any(e["source"]=="TEMP_VERTICAL_RULING_INTERIOR_PSM7"
                                     for e in cell["source_crop_ocr_alternatives"]))
        self.assertFalse(result["accounting_write_permitted"])

    def test_r272_numeric_whitelist_is_separate_unapproved_source_witness(self):
        im=scene();unchanged=im.copy();psm_calls=[]
        def ordinary(_crop,psm):
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
                    "\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t1\t1\t20\t10\t60\t12.5|\n")
        def numeric(crop,psm):
            psm_calls.append(psm)
            self.assertEqual(psm,7)
            self.assertEqual(crop.dtype,np.uint8)
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
                    "\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t1\t1\t20\t10\t60\t125\n")
        result=m.review(im,bands(),source(),1600,850,reader=ordinary,numeric_reader=numeric)
        self.assertGreater(len(psm_calls),0)
        cell=result["source_numeric_row_proposals"][0]["original_source_numeric_fields"]["printed_pcs"]
        new=[x for x in cell["source_crop_ocr_alternatives"]
             if x["source"]=="TEMP_NUMERIC_WHITELIST_PSM7_R272"]
        self.assertEqual(len(new),1)
        self.assertEqual(new[0]["ocr_literal_text"],"125")
        self.assertTrue(new[0]["numeric_only_ocr_char_whitelist"])
        self.assertTrue(new[0]["cannot_resolve_decimal_or_digit_conflicts"])
        self.assertFalse(new[0]["source_text_verified"])
        self.assertFalse(new[0]["posting_eligible"])
        self.assertFalse(cell["field_value_certified"])
        self.assertFalse(result["accounting_write_permitted"])
        self.assertTrue(np.array_equal(im,unchanged))

    def test_r272_numeric_reader_requires_standard_original_pixel_reader(self):
        with self.assertRaises(ValueError):
            m.review(scene(),bands(),source(),1600,850,
                     reader=None,numeric_reader=lambda _im,_psm:"")
        with self.assertRaises(ValueError):
            m.review(scene(),bands(),source(),1600,850,
                     reader=lambda _im,_psm:"",numeric_reader="not callable")

if __name__=="__main__":
    unittest.main(verbosity=2)
