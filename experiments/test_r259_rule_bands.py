"""R259 printed-source ruling-band regressions: geometry only, no posting."""
import unittest
import importlib.util
from pathlib import Path
import numpy as np,cv2
p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_RULED_ROW_BANDS_R259.py"
spec=importlib.util.spec_from_file_location("r259",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def token(t,x,y,ww=60):
    return {"original_source_text":t,"original_source_box":[x,y,x+ww,y+15],
            "posting_eligible":False}
def src():
    words=[token("Product",350,302,76),token("Pcs",750,309,52),
           token("Taxable",1150,308,100),token("Total",190,498,67)]
    return [{"variant":v,"posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":words}
            for v in ("grid_removed_psm11_2x","grid_removed_psm6_2x")]
def scene(with_lines=True):
    im=np.full((850,1600,3),255,np.uint8)
    if with_lines:
        for y in (362,382,402,422,442,462,482):
            cv2.line(im,(200,y),(1450,y),(0,0,0),2)
    return im

class PrintedRuleBands(unittest.TestCase):
    def test_seven_source_ruled_bands_no_accounting(self):
        image=scene();before=image.copy();out=m.review(image,src())
        self.assertEqual(out["status"],"SOURCE_REPEATED_RULING_ROW_BANDS_REVIEW_ONLY")
        self.assertEqual(out["detected_physical_row_bands"],7)
        self.assertEqual(out["verified_item_rows"],0)
        self.assertFalse(out["posting_eligible"])
        self.assertTrue(out["first_divider_top_extrapolated"])
        self.assertTrue(np.array_equal(before,image))
        self.assertEqual(out["row_bands"][0]["row_number_is_proposal"],1)
        self.assertFalse(any(row["source_values_verified"] for row in out["row_bands"]))
    def test_without_source_rulings_no_rows(self):
        self.assertEqual(m.review(scene(False),src())["detected_physical_row_bands"],0)
    def test_missing_source_column_header_is_no_rows(self):
        v=src()
        for variant in v:
            variant["source_words"]=[s for s in variant["source_words"]
                if s["original_source_text"]!="Pcs"]
        self.assertEqual(m.review(scene(),v)["detected_physical_row_bands"],0)
    def test_invalid_source_box_refused(self):
        v=src();v[0]["source_words"][0]["original_source_box"][0]=-5
        with self.assertRaises(ValueError):m.review(scene(),v)
    def test_only_source_crop_ocr_remains_review_only(self):
        def ocr(image,psm):
            self.assertEqual(psm,7)
            self.assertTrue(image.shape[1]>100)
            return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                    "5\t1\t1\t1\t1\t1\t4\t4\t18\t10\t66\tSAMPLE\n")
        out=m.review(scene(),src(),ocr)
        self.assertEqual(out["detected_physical_row_bands"],7)
        self.assertTrue(all(row["text_view_alternatives"][0]["original_description_ocr"]=="SAMPLE"
                       for row in out["row_bands"]))
        self.assertTrue(all(row["posting_eligible"] is False for row in out["row_bands"]))
        self.assertFalse(out["accounting_write_permitted"])
    def test_unbounded_crop_output_fails_closed(self):
        with self.assertRaises(ValueError):m.review(scene(),src(),lambda *_:"A"*100001)
if __name__=="__main__":unittest.main(verbosity=2)
