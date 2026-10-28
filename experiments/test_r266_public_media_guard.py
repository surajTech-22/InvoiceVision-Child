"""R266 guards newly added private user files, not pre-existing repo history."""
import importlib.util
from pathlib import Path
import unittest
root=Path(__file__).resolve().parents[1]
p=root/"scripts/r266_reject_new_private_source_assets.py"
spec=importlib.util.spec_from_file_location("_r266_public_guard",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class R266Guard(unittest.TestCase):
    def test_private_photo_and_pdf_blocked(self):
        for name in ("source_15/user-original.jpg","evidence/customer.pdf",
                     "real_invoice_photos/raw.png",
                     "assets/invoice_scan.jpeg","samples/invoice_test.zip"):
            with self.subTest(name=name):
                self.assertIsNotNone(m.violation(name))
    def test_safe_research_source_and_synthetic_text(self):
        for name in ("integration/Engine/READ_ONLY.py",
                     "research/R262_UNRELEASED.md",
                     "experiments/synthetic_table.py",
                     "experiments/fixture_synthetic.json"):
            with self.subTest(name=name):
                self.assertIsNone(m.violation(name))
    def test_private_source_path_blocked_even_for_text(self):
        self.assertIsNotNone(m.violation("private_originals/ocr.txt"))
    def test_backslash_and_case_variants_blocked(self):
        self.assertIsNotNone(m.violation(r"Source_15\invoice.JPG"))
        self.assertIsNotNone(m.violation(r"Data\PRIVATE_INVOICE_EVIDENCE\words.json"))

if __name__=="__main__":
    unittest.main(verbosity=2)
