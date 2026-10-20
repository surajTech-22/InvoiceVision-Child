"""One-source nonposting replay smoke: real source bytes / UTF-8 / no new OCR."""
import hashlib
import json
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from experiments.r146_rezone import run as replay
from experiments.r146_field_evaluation import run as evaluate, canonical
from experiments.r138_cross_model_consensus import same_value
from experiments.r147_utf8_evidence import write_json,write_utf8,read_json

UNICODE="中文 Ω 心 ₹ 04/09/2026"

class SourceLinkedReplay(unittest.TestCase):
    def make_fixture(self,root):
        root=Path(root)
        engine=root/"baseline"/"InvoiceVisionChild"/"Engine"
        images=engine/"InvoiceFormatExamples_R2";images.mkdir(parents=True)
        im=np.full((32,70,3),240,dtype=np.uint8)
        cv2.rectangle(im,(3,3),(66,26),(0,0,0),1)
        self.assertTrue(cv2.imwrite(str(images/"sample.png"),im))
        with zipfile.ZipFile(engine/"VISUAL_BENCHMARK_15_PHOTOS.zip","w"):pass
        raw=(images/"sample.png").read_bytes()
        sha=hashlib.sha256(raw).hexdigest()
        output=root/"captured";output.mkdir()
        write_json(output/"REPORT.json",{"cases":[{"file":"sample.png","status":"COMPLETED_UNVERIFIED","source_sha256":sha}]})
        write_utf8(output/"sample.tsv","header\n5\t1\t1\t1\t1\t1\t3\t3\t20\t8\t90\t"+UNICODE)
        overlay=root/"zone_engine.py";overlay.write_text("research only",encoding="utf-8")
        return output/"REPORT.json",root/"baseline",overlay

    def test_rezone_preserves_nonlatin_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,baseline,overlay=self.make_fixture(tmp)
            seen=[]
            def zones(image,parents,tsv):
                seen.append(tsv)
                h,w=image.shape[:2]
                return ([{"id":"R001","xyxy":[0,0,w,h],"category":"unknown"}],
                        {"source_note":UNICODE},
                        [{"xyxy":[3,3,23,11],"text":UNICODE}])
            with patch("experiments.r146_rezone.module",return_value=types.SimpleNamespace(refine_regions=zones)):
                replay(report,baseline,overlay,Path(tmp)/"results")
            result=read_json(Path(tmp)/"results"/"REPORT.json")
            self.assertEqual(result["cases"][0]["zone_meta"]["source_note"],UNICODE)
            self.assertIn(UNICODE,seen[0])
            self.assertEqual(result["cases"][0]["uncovered_lines"],0)
            self.assertFalse(result["cases"][0].get("posting_eligible",False))
            self.assertTrue((Path(tmp)/"results"/"sample_comparison.png").is_file())

    def test_field_review_retains_currency_as_verbatim_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,_,_=self.make_fixture(tmp)
            reference=Path(tmp)/"ref.json"
            write_json(reference,{"invoices":[{"image_files":["sample.png"],
                 "grand_total":"₹1,413.00"}]})
            with patch("experiments.r146_field_evaluation.inspect",
                       return_value={"candidates":[{"field":"grand_total","raw_value":"₹1,413.00"}]}):
                evaluate(report,reference,Path(tmp)/"result"/"fields.json")
            result=read_json(Path(tmp)/"result"/"fields.json")
            self.assertEqual(result["rows"][0]["matches"],["₹1,413.00"])
            self.assertFalse(result["field_accuracy_verified"])
            self.assertFalse(result["posting_eligible"])

    def test_cross_engine_nonlatin_with_same_digits_must_disagree(self):
        self.assertFalse(same_value("北京贸易123","上海贸易123"))
        self.assertFalse(same_value("شركة التجارة ۱۲۳","北京贸易 ۱۲۳"))
        self.assertTrue(same_value("北京-贸易123","北京贸易 123"))
        self.assertTrue(same_value("Grand Total ₹ 1,413.00","Grand Total ₹ 1,413.00"))
    def test_nonlatin_names_are_not_equal_after_normalization(self):
        self.assertNotEqual(canonical("supplier","شركة التجارة"),canonical("supplier","北京贸易公司"))
        self.assertEqual(canonical("buyer","北京-贸易 公司"),canonical("buyer","北京贸易公司"))
        self.assertNotEqual(canonical("supplier","MÉTRO"),canonical("supplier","METRO"))

    def test_foreign_party_and_absent_reference_cannot_false_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            report,_,_=self.make_fixture(tmp)
            reference=Path(tmp)/"ref.json"
            write_json(reference,{"invoices":[{"image_files":["sample.png"],
                "buyer":"شركة التجارة","supplier":"REVIEW_REQUIRED","invoice_number":""}]})
            with patch("experiments.r146_field_evaluation.inspect",
                return_value={"candidates":[{"field":"buyer","raw_value":"北京贸易公司"}]}):
                evaluate(report,reference,Path(tmp)/"result"/"fields.json")
            output=read_json(Path(tmp)/"result"/"fields.json")
            self.assertEqual(output["counts"]["reference_slots"],1)
            self.assertEqual(output["rows"][0]["status"],"wrong_candidates_only")
            self.assertEqual(output["rows"][0]["matches"],[])
            self.assertFalse(output["field_accuracy_verified"])

if __name__=="__main__":unittest.main(verbosity=2)
