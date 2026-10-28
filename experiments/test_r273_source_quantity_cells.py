"""R273 original-coordinate quantity crop safety."""
import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[0]/"test_r261_column_bands.py"
spec=importlib.util.spec_from_file_location("source_fixtures",p)
f=importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
class R273(unittest.TestCase):
    def test_source_amounts_never_accepted(self):
        hdr="level"+chr(9)+"text"+chr(10)
        word=hdr+"5"+chr(9)+"60"+chr(10)
        result=f.m.review(f.scene(),f.bands(),f.source(),1600,850,
            reader=lambda *_:word,numeric_reader=lambda *_:word)
        self.assertFalse(result["accounting_write_permitted"])
        self.assertEqual(result["certified_item_rows"],0)
        pcs=result["source_numeric_row_proposals"][0]["original_source_numeric_fields"]["printed_pcs"]
        alt=[v for v in pcs["source_crop_ocr_alternatives"]
            if v["source"]=="TEMP_SOURCE_PCS_RIGHT_ALIGNMENT_R273"]
        self.assertEqual(len(alt),1)
        self.assertFalse(alt[0]["posting_eligible"])
        self.assertTrue(alt[0]["may_exclude_leading_quantity_digits"])
if __name__=="__main__":unittest.main()
