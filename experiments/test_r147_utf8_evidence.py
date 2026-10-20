"""R147: original Unicode text must survive real Windows evidence serialization."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from experiments.r147_utf8_evidence import write_utf8, write_json

SAMPLE="Invoice 04/09/2026 — श्री राम € ₹ عربي 中文 漢字 Ω ω 心 ） ： \t\nsecond row"

class EvidencePersistence(unittest.TestCase):
    def test_exact_unicode_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"source.tsv"
            write_utf8(path,SAMPLE)
            self.assertEqual(path.read_bytes(),SAMPLE.encode("utf-8"))
            self.assertEqual(path.read_text(encoding="utf-8"),SAMPLE)
    def test_json_retains_raw_unicode_and_structured_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"REPORT.json"
            v={"raw_texts":[SAMPLE],"sha256":"a"*64,"posting_eligible":False}
            write_json(path,v)
            self.assertEqual(json.loads(path.read_bytes()),v)
            self.assertIn("心".encode("utf-8"),path.read_bytes())
    def test_prior_result_preserved_on_invalid_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"REPORT.json"
            path.write_text("verified baseline",encoding="utf-8")
            with self.assertRaises(UnicodeEncodeError):
                write_utf8(path,"\ud800")
            self.assertEqual(path.read_text(encoding="utf-8"),"verified baseline")
            self.assertEqual(list(Path(tmp).glob("*.incomplete")),[])
    def test_no_temp_files_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"a.tsv"
            write_utf8(p,SAMPLE)
            self.assertEqual([f.name for f in Path(tmp).iterdir()],["a.tsv"])
    def test_atomic_replace_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"a.tsv";path.write_text("original",encoding="utf-8")
            with patch("experiments.r147_utf8_evidence.os.replace",side_effect=OSError("simulated disk failure")):
                with self.assertRaisesRegex(OSError,"simulated disk failure"):write_utf8(path,SAMPLE)
            self.assertEqual(path.read_text(encoding="utf-8"),"original")
            self.assertEqual([f.name for f in Path(tmp).iterdir()],["a.tsv"])
    def test_nonfinite_json_does_not_replace_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"REPORT.json";write_json(p,{"status":"old"})
            with self.assertRaises(ValueError):write_json(p,{"bad":float("nan")})
            self.assertEqual(json.loads(p.read_bytes()),{"status":"old"})
    def test_newlines_match_cross_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"line.tsv";write_utf8(p,"first\nsecond\n")
            self.assertEqual(p.read_bytes(),b"first\nsecond\n")

if __name__=="__main__":unittest.main(verbosity=2)
