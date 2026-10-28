"""R274 HSN source-only cropped evidence regressions."""
import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[0]/"test_r261_column_bands.py"
spec=importlib.util.spec_from_file_location("r274_fixture",p)
f=importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
class R274(unittest.TestCase):
    def test_hsn_crop_does_not_become_a_approved_field(self):
        views=f.source()
        for view in views:
            view["source_words"].append(f.token("HSN",221,308,40))
        head="level"+chr(9)+"text"+chr(10)
        text=head+"5"+chr(9)+"33051090"+chr(10)
        out=f.m.review(f.scene(),f.bands(),views,1600,850,
                       reader=lambda *_:text,numeric_reader=lambda *_:text)
        hsn=out["source_numeric_row_proposals"][0]["original_source_numeric_fields"]["printed_hsn"]
        trimmed=[x for x in hsn["source_crop_ocr_alternatives"] if x["source"]=="TEMP_SOURCE_HSN_LEFT_SERIAL_EXCLUSION_R274"]
        self.assertEqual(len(trimmed),1)
        self.assertTrue(trimmed[0]["may_exclude_true_leading_hsn_digit"])
        self.assertFalse(trimmed[0]["posting_eligible"])
        self.assertEqual(out["certified_item_rows"],0)
    def test_without_hsn_header_no_candidate(self):
        out=f.m.review(f.scene(),f.bands(),f.source(),1600,850)
        self.assertIn("printed_hsn",out["missing_printed_headers"])
        self.assertFalse(out["accounting_write_permitted"])
if __name__=="__main__":
    unittest.main()
