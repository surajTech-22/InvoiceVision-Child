"""R272 offline original-pixel numeric-only Tesseract security and provenance."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import cv2
import numpy as np

p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_NUMERIC_ONLY_R272.py"
spec=importlib.util.spec_from_file_location("_r272_numericonly",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def sample():
    im=np.full((80,280,3),255,dtype=np.uint8)
    cv2.putText(im,"123.45",(12,51),cv2.FONT_HERSHEY_SIMPLEX,1.2,(0,0,0),2)
    return im
TSV=("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop"
     "\twidth\theight\tconf\ttext\n"
     "5\t1\t1\t1\t1\t1\t2\t2\t20\t10\t60\t123.45\n").encode()

class NumericOnlySource(unittest.TestCase):
    def fake_executable(self,folder):
        f=Path(folder)/"tesseract.exe"
        f.write_bytes(b"MZfake")
        os.chmod(f,0o755)
        return f

    def test_stdin_only_png_no_private_disk_files_or_financial_write(self):
        with tempfile.TemporaryDirectory() as folder:
            f=self.fake_executable(folder)
            source=sample();unchanged=source.copy()
            def fake_run(cmd,**kwargs):
                self.assertEqual(cmd[0],str(f))
                self.assertEqual(cmd[1:4],["stdin","stdout","--psm"])
                self.assertIn("tessedit_char_whitelist=0123456789.,-",cmd)
                self.assertEqual(cmd[-1],"tsv")
                self.assertTrue(kwargs["input"].startswith(b"\x89PNG\r\n"))
                self.assertNotIn("shell",kwargs)
                self.assertLessEqual(kwargs["timeout"],15)
                return SimpleNamespace(returncode=0,stdout=TSV,stderr=b"")
            with patch.object(m.subprocess,"run",side_effect=fake_run) as proc:
                response=m.reader_for(f)(source,7)
            self.assertEqual(response,TSV.decode())
            self.assertEqual(proc.call_count,1)
            self.assertTrue(np.array_equal(source,unchanged))
            self.assertEqual([x.name for x in Path(folder).iterdir()],["tesseract.exe"])

    def test_never_run_untrusted_path_or_unsupported_psm(self):
        for exe in ("tesseract","python.exe","/does/not/exist/tesseract"):
            with self.assertRaises(ValueError):m.read_numeric_source(exe,sample(),7)
        with tempfile.TemporaryDirectory() as folder:
            f=self.fake_executable(folder)
            with self.assertRaises(ValueError):m.read_numeric_source(f,sample(),6)
            with self.assertRaises(ValueError):m.read_numeric_source(f,sample(),8)
            with self.assertRaises(ValueError):
                m.read_numeric_source(f,np.full((3,3),255,np.uint8),7)

    def test_subprocess_error_oversize_and_bad_unicode_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            f=self.fake_executable(folder)
            for response in (SimpleNamespace(returncode=1,stdout=b"",stderr=b"bad"),
                             SimpleNamespace(returncode=0,stdout=b"a"*100001,stderr=b""),
                             SimpleNamespace(returncode=0,stdout=b"\xff",stderr=b"")):
                with patch.object(m.subprocess,"run",return_value=response):
                    with self.assertRaises(ValueError):
                        m.read_numeric_source(f,sample(),7)
            with patch.object(m.subprocess,"run",side_effect=OSError("no local executable")):
                with self.assertRaises(ValueError):
                    m.read_numeric_source(f,sample(),7)

if __name__=="__main__":
    unittest.main(verbosity=2)
