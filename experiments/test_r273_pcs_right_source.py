"""R273 right-side source Pcs crop is provisional, never a posted quantity."""
import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py"
spec=importlib.util.spec_from_file_location("_r273",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class RightCropGate(unittest.TestCase):
    def test_source_crop_flags(self):
        self.assertIn("numeric_reader",m.review.__code__.co_varnames)
        self.assertIn("right_aligned_crop_assumption_only",
                      p.read_text())
        self.assertIn("may_exclude_leading_quantity_digits",
                      p.read_text())

if __name__=="__main__":
    unittest.main()
