"""R246: invoice grid-line removal and source-bound table-column regressions."""
import importlib.util
from pathlib import Path
import unittest
import cv2,numpy as np

p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_GRID_TABLE_R246.py"
spec=importlib.util.spec_from_file_location("_r246_test_module",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
HEAD="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"

def invoice():
    frame=np.full((800,600,3),255,np.uint8)
    for y in (250,320,395):
        cv2.line(frame,(28,y),(565,y),(0,0,0),3)
    for x in (28,330,410,485,565):
        cv2.line(frame,(x,250),(x,395),(0,0,0),2)
    return frame

def synthetic_tsv():
    words=[("INVOICE",42,45,78),("NO",132,45,25),("SYN-2026-14",176,45,115),
           ("DESCRIPTION",40,284,165),("QTY",335,284,45),
           ("RATE",417,284,50),("AMOUNT",494,284,70),
           ("SAMPLE",42,350,75),("PART",125,350,65),
           ("20",338,350,30),("57.00",418,350,60),
           ("1140.00",498,350,65)]
    rows=[HEAD,"1\t1\t0\t0\t0\t0\t0\t0\t1200\t1600\t-1\t"]
    for i,(name,x,y,w) in enumerate(words,1):
        rows.append(f"5\t1\t1\t1\t1\t{i}\t{2*x}\t{2*y}\t{2*w}\t{44}\t97\t{name}")
    return "\n".join(rows)+"\n"

class RulingLines(unittest.TestCase):
    def test_ruling_lines_removed_but_source_identical(self):
        img=invoice();before=img.copy()
        view,meta=m.remove_long_ruling_lines(img)
        self.assertTrue(meta["detected_long_ruling_lines"])
        self.assertGreater(meta["ruling_line_pixel_fraction"],0)
        self.assertTrue(np.array_equal(img,before))
        self.assertEqual(view.shape[:2],(1600,1200))
    def test_two_grid_views_keep_source_boxes_and_no_accounting(self):
        img=invoice();before=img.copy()
        out=m.review(img,lambda _view,_psm:synthetic_tsv())
        self.assertEqual(out["status"],"GRID_RULING_SOURCE_REVIEW_ONLY")
        self.assertEqual(len(out["source_views"]),2)
        self.assertGreaterEqual(out["provisional_table_rows"],1)
        self.assertEqual(out["source_unique_item_row_count"],1)
        self.assertEqual(out["physical_row_duplicate_evidence_count"],1)
        self.assertEqual(len(out["source_unique_item_rows"][0]["source_variants"]),2)
        self.assertFalse(out["source_unique_item_rows"][0]["conflicting_ocr_alternatives"])
        rows=out["source_field_row_anchors"]["table_header_anchored_row_proposals"]
        self.assertEqual(rows[0]["quantity_original_ocr"],"20")
        self.assertEqual(rows[0]["amount_original_ocr"],"1140.00")
        self.assertFalse(out["posting_eligible"])
        self.assertEqual(out["accepted_item_rows"],0)
        self.assertTrue(np.array_equal(img,before))
    def test_source_row_conflicting_readings_are_not_silently_resolved(self):
        base={"posting_eligible":False,
              "source_view":"grid_removed_psm11_2x",
              "row_box":[35,300,590,344],
              "quantity_source_box":[330,305,365,333],
              "amount_source_box":[500,309,568,338],
              "description_original_ocr":"TEST PART",
              "quantity_original_ocr":"20",
              "amount_original_ocr":"1140.00"}
        alt={**base,"source_view":"grid_removed_psm6_2x",
             "quantity_original_ocr":"30"}
        groups=m.distinct_source_rows([base,alt])
        self.assertEqual(len(groups),1)
        self.assertTrue(groups[0]["conflicting_ocr_alternatives"])
        self.assertEqual([x["original_quantity"] for x in groups[0]["source_variants"]],
                         ["20","30"])
        self.assertFalse(groups[0]["distinct_row_certified"])

    def test_grey_phone_photo_background_does_not_delete_image(self):
        # A photographed receipt can have broad grey vignetting. A global
        # Otsu mask incorrectly treated 14-19% of real source as long ruling.
        frame=invoice()
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        yy,xx=np.indices(gray.shape)
        background=(20*(xx/gray.shape[1])).astype(np.uint8)
        shaded=np.clip(gray.astype(np.int16)-background,0,255).astype(np.uint8)
        shaded=cv2.cvtColor(shaded,cv2.COLOR_GRAY2BGR)
        original=shaded.copy()
        cleaned,meta=m.remove_long_ruling_lines(shaded)
        self.assertTrue(meta["detected_long_ruling_lines"])
        self.assertLess(meta["ruling_line_pixel_fraction"],.12)
        self.assertTrue(np.array_equal(shaded,original))
        self.assertEqual(cleaned.shape[:2],(1600,1200))

    def test_blank_page_cannot_invent_item_rows(self):
        img=np.full((500,500,3),255,np.uint8)
        result=m.review(img,lambda _view,_psm:synthetic_tsv())
        self.assertEqual(result["status"],"NO_LONG_RULING_LINES_FOUND")
        self.assertEqual(result["accepted_item_rows"],0)
    def test_malformed_image_does_not_launch_ocr(self):
        with self.assertRaises(ValueError):
            m.review(np.zeros((20,20,3),np.uint8),lambda _v,_p:synthetic_tsv())
    def test_invalid_tsv_cannot_approve_row(self):
        with self.assertRaises(ValueError):
            m.review(invoice(),lambda _v,_p:"not valid TSV")
    def test_no_source_pixels_changed_if_reader_fails(self):
        frame=invoice();before=frame.copy()
        with self.assertRaises(RuntimeError):
            m.review(frame,lambda _v,_p: (_ for _ in ()).throw(RuntimeError("OCR unavailable")))
        self.assertTrue(np.array_equal(frame,before))
    def test_source_line_fraction_bounded(self):
        frame=np.zeros((500,500,3),np.uint8)
        with self.assertRaises(ValueError):
            m.remove_long_ruling_lines(frame)
if __name__=="__main__":
    unittest.main(verbosity=2)
