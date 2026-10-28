"""R268 synthetic source-literal OCR evidence conflict and accounting safety."""
import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_NUMERIC_WITNESS_R268.py"
spec=importlib.util.spec_from_file_location("_r268_numeric_witness",p)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def source(raw="| 1,230.50}",crop="1,230.50",other="1,230.80"):
    originals=[{"source_view":"grid_removed_psm11_2x",
                "source_token_index":9,"original_source_text":raw,
                "original_source_box":[100,200,150,220],
                "numeric_text_verified":False,"posting_eligible":False}]
    def witness(tag,text):
        return {"source":tag,"ocr_literal_text":text,
                "original_source_pixel_rect":[98,195,154,225],
                "original_crop_sha256":"a"*64,
                "source_text_verified":False,"posting_eligible":False}
    return {"status":"PRINTED_RULING_COLUMNS_REVIEW_ONLY",
            "posting_eligible":False,"certified_item_rows":0,
            "certified_financial_fields":0,
            "source_numeric_row_proposals":[{
                "row_number_is_proposal":1,"posting_eligible":False,
                "row_completely_verified":False,
                "original_source_numeric_fields":{
                  "printed_taxable_amount":{
                    "field_value_certified":False,"posting_eligible":False,
                    "source_observations":originals,
                    "source_crop_ocr_alternatives":[
                        witness("TEMP_ORIGINAL_NUMERIC_CELL_PSM7",crop),
                        witness("TEMP_ORIGINAL_NUMERIC_CELL_PSM6_FALLBACK",other)]
                    }
                }}]}

class NumericSourceWitnesses(unittest.TestCase):
    def test_exact_char_span_and_unmodified_border_glyph(self):
        inp=source(other="1,230.50")
        out=m.review(inp)
        field=out["source_rows"][0]["numeric_fields"]["printed_taxable_amount"]
        first=field["source_witnesses"][0]
        self.assertEqual(first["literal_original_ocr"],"| 1,230.50}")
        token=first["numeric_substrings"][0]
        self.assertEqual(token["literal_substring"],"1,230.50")
        self.assertEqual(first["literal_original_ocr"][token["start_char"]:token["end_char"]],"1,230.50")
        self.assertTrue(token["adjacent_non_numeric_ocr"])
        self.assertEqual(field["numeric_fragment_alternatives"],["1,230.50"])
        self.assertFalse(field["has_unresolved_disagreement"])
        self.assertFalse(field["candidate_value_selected"])
        self.assertFalse(out["release_approved"])
        self.assertEqual(out["verified_financial_fields"],0)
        self.assertEqual(inp["source_numeric_row_proposals"][0]["original_source_numeric_fields"]
                         ["printed_taxable_amount"]["source_observations"][0]
                         ["original_source_text"],"| 1,230.50}")

    def test_conflicting_original_pixel_reads_never_select_winner(self):
        field=m.review(source())["source_rows"][0]["numeric_fields"]["printed_taxable_amount"]
        self.assertTrue(field["has_unresolved_disagreement"])
        self.assertEqual(field["numeric_fragment_alternatives"],["1,230.50","1,230.80"])
        self.assertTrue(field["needs_original_pixel_verification"])
        self.assertFalse(field["field_value_certified"])
        self.assertFalse(field["candidate_value_selected"])

    def test_multiple_numeric_tokens_are_not_merged_into_number(self):
        field=m.review(source(raw="1} 22032000",crop="",other=""))["source_rows"][0]["numeric_fields"]["printed_taxable_amount"]
        self.assertEqual(field["source_witnesses"][0]["numeric_substrings"][0]["literal_substring"],"1")
        self.assertEqual(field["source_witnesses"][0]["numeric_substrings"][1]["literal_substring"],"22032000")
        self.assertTrue(field["has_unresolved_disagreement"])
        self.assertFalse(field["field_value_certified"])

    def test_invalid_source_hash_posted_or_oversize_refused(self):
        for mutation in ("hash","posted","oversize"):
            sample=source()
            row=sample["source_numeric_row_proposals"][0]
            cell=row["original_source_numeric_fields"]["printed_taxable_amount"]
            if mutation=="hash":cell["source_crop_ocr_alternatives"][0]["original_crop_sha256"]="not-a-hash"
            if mutation=="posted":cell["posting_eligible"]=True
            if mutation=="oversize":cell["source_observations"][0]["original_source_text"]="X"*241
            with self.assertRaises(ValueError):m.review(sample)

    def test_no_printed_header_or_no_rows_is_safe(self):
        sample=source();sample["source_numeric_row_proposals"][0]["original_source_numeric_fields"]={}
        result=m.review(sample)
        self.assertEqual(result["source_rows"][0]["numeric_fields"],{})
        self.assertFalse(result["accounting_write_permitted"])

if __name__=="__main__":
    unittest.main(verbosity=2)
