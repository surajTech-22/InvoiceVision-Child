import unittest
from experiments.r148_glued_datetime import read_glued_datetime
from experiments.r141_inline_field_evidence import parse_inline
from experiments.r138_field_evidence import reconstruct
from experiments.r143_source_evidence import inspect

class StrictJoinedDate(unittest.TestCase):
    def test_actual_real_photo_ocr_string(self):
        x=read_glued_datetime("03/09/202602:08PM")
        self.assertEqual(x["date"],"03/09/2026")
        self.assertEqual(x["clock_text"],"02:08PM")
        self.assertEqual(x["raw_source_text"],"03/09/202602:08PM")
        self.assertFalse(x["transcription_verified"])
        self.assertFalse(x["posting_eligible"])
    def test_calendar_impossibility_and_clock_errors(self):
        for s in ("31/02/202602:08PM","03/09/202613:08PM","03/09/202602:68PM",
                  "03/09/202600:08PM","03/09/202602:08XY","03/09/20260208PM",
                  "03/09/202602:08PM invoice","invoice 03/09/202602:08PM","99/99/202601:01PM"):
            with self.subTest(s=s):self.assertIsNone(read_glued_datetime(s))
    def test_existing_separated_date_not_changed(self):
        self.assertIsNone(read_glued_datetime("04/09/2026 14:37:09"))
        self.assertEqual([r['raw_value'] for r in parse_inline("Date: 04/09/2026 14:37:09") if r['field']=='invoice_date'],["04/09/2026"])
    def test_same_line_date_exact_source_slice(self):
        result=parse_inline("Date: 03/09/202602:08PM")
        self.assertEqual([x["raw_value"] for x in result if x["field"]=="invoice_date"],["03/09/2026"])
        self.assertTrue(all(x["source_line"]=="Date: 03/09/202602:08PM" for x in result))
        self.assertTrue(all(not x["posting_eligible"] for x in result))
    def test_invoice_number_cannot_steal_joined_date(self):
        self.assertFalse([x for x in parse_inline("Bill No: 03/09/202602:08PM") if x["field"]=="invoice_number"])
    def test_adjacent_label_finds_date_without_modifying_ocr(self):
        source={"file":"source.jpg","source_sha256":"a"*64,"source_width":900,"source_height":1200,
            "raw_texts":["Date","03/09/202602:08PM"],
            "raw_boxes":[[[100,100],[150,100],[150,125],[100,125]],
                         [[165,100],[385,100],[385,125],[165,125]]]}
        original=list(source["raw_texts"])
        candidates=reconstruct(source)["fields"]["invoice_date"]
        self.assertEqual(candidates[0]["value"],"03/09/2026")
        self.assertEqual(candidates[0]["raw_source_value"],"03/09/202602:08PM")
        self.assertEqual(source["raw_texts"],original)
        result=inspect(source,"review")
        review=[p for p in result["candidates"] if p["field"]=="invoice_date"]
        self.assertEqual([c["raw_value"] for c in review],["03/09/2026"])
        self.assertEqual(review[0]["raw_source_text"],["Date","03/09/202602:08PM"])
        self.assertFalse(result["posting_eligible"])
        self.assertFalse(result["field_accuracy_verified"])

if __name__=="__main__":unittest.main(verbosity=2)
