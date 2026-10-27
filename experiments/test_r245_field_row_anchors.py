"""R245 source-aligned label-value and physical table-column synthetic tests."""
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).resolve().parents[1]/"integration/Engine/INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py"
spec=importlib.util.spec_from_file_location("_child_r245_fields",p)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def token(text,x,y,w=58):
    return {"original_source_text":text,
            "original_source_box":[x,y,x+w,y+20],
            "field_value_verified":False,"posting_eligible":False}
def source(*,conflict=False,missing_headers=False):
    words=[token("INVOICE",35,32),token("NO",114,32,w=32),
           token("TEST2026A17" if not conflict else "TEST2026A18",164,32,w=142),
           token("INVOICE",35,80),token("DATE",116,80,w=47),
           token("17/09/2026",185,80,w=130),
           token("GRAND",34,129),token("TOTAL",100,129),
           token("1140.00",205,129,w=104),
           token("DESCRIPTION",35,255,w=140),
           token("QTY",250,255,w=45),
           token("AMOUNT",400,255,w=90),
           token("PACKAGED",34,310,w=90),token("SAMPLE",133,310,w=77),
           token("20",251,310,w=35),token("1140.00",412,310,w=75)]
    if missing_headers:words=[x for x in words if x["original_source_text"]!="AMOUNT"]
    return words
def fixture(*,other_conflict=False,missing_headers=False):
    return {"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
            "posting_eligible":False,
            "variants":[
                {"variant":"gray_2x","posting_eligible":False,
                 "source_boxes_are_original_pixels":True,
                 "source_words":source(missing_headers=missing_headers)},
                {"variant":"clahe_2x","posting_eligible":False,
                 "source_boxes_are_original_pixels":True,
                 "source_words":source(conflict=other_conflict,
                                       missing_headers=missing_headers)}
            ]}

class SourceAnchoredFieldRows(unittest.TestCase):
    def test_invoice_meta_and_row_fields_kept_separate(self):
        result=mod.propose(fixture(),600,700)
        types=[x["category"] for x in result["field_label_anchored_proposals"]]
        self.assertIn("invoice_number",types)
        self.assertIn("invoice_date",types)
        self.assertIn("net_total",types)
        self.assertGreaterEqual(len(result["table_header_anchored_row_proposals"]),1)
        first=result["table_header_anchored_row_proposals"][0]
        self.assertEqual(first["quantity_original_ocr"],"20")
        self.assertEqual(first["amount_original_ocr"],"1140.00")
        self.assertEqual(first["description_original_ocr"],"PACKAGED SAMPLE")
        self.assertFalse(first["row_complete_certified"])
        self.assertEqual(result["verified_invoice_fields"],0)
        self.assertFalse(result["posting_eligible"])
    def test_conflicting_invoice_identifiers_kept_as_disagreements(self):
        result=mod.propose(fixture(other_conflict=True),600,700)
        ids=[x["candidate_text"] for x in result["field_label_anchored_proposals"]
             if x["category"]=="invoice_number"]
        self.assertEqual(set(ids),{"TEST2026A17","TEST2026A18"})
        self.assertEqual(result["verified_invoice_fields"],0)
    def test_two_line_product_pcs_net_amt_headings(self):
        # Table heading OCR comes from multiple print baselines, including
        # a conservative 'Pes' alias for the heading 'Pcs' and 'Ant' for 'Amt'.
        header=[
            token("Product",90,110,w=95),
            token("Name",189,114,w=55),
            token("Pes",315,123,w=42),
            token("Net",460,128,w=36),
            token("Ant",503,133,w=39),
            token("SAMPLE",90,185,w=85),
            token("BAR",180,188,w=45),
            token("60",317,185,w=28),
            token("164.95",495,192,w=63)
        ]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,
             "variants":[
                 {"variant":"grid_removed_psm11_2x","posting_eligible":False,
                  "source_boxes_are_original_pixels":True,
                  "source_words":list(header)},
                 {"variant":"grid_removed_psm6_2x","posting_eligible":False,
                  "source_boxes_are_original_pixels":True,
                  "source_words":list(header)}
             ]}
        result=mod.propose(src,700,500)
        self.assertEqual(result["row_proposals_count"],2)
        row=result["table_header_anchored_row_proposals"][0]
        self.assertEqual(row["quantity_original_ocr"],"60")
        self.assertEqual(row["amount_original_ocr"],"164.95")
        self.assertFalse(row["row_complete_certified"])
    def test_three_adjacent_numeric_columns_cannot_replace_pcs(self):
        words=[
            token("Product",90,110,w=95),token("Name",189,114,w=55),
            token("CS",250,121,w=38),token("PES",315,123,w=42),
            token("Total",385,123,w=58),token("Net",460,128,w=36),
            token("Ant",503,133,w=39),
            token("SAMPLE",90,185,w=85),token("BAR",180,188,w=45),
            token("0",254,185,w=25),token("60",317,185,w=28),
            token("360",395,185,w=40),token("164.95",495,192,w=63)
        ]
        f={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
           "posting_eligible":False,
           "variants":[
               {"variant":"gray_2x","posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":list(words)},
               {"variant":"clahe_2x","posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":list(words)}
           ]}
        proposal=mod.propose(f,700,500)
        self.assertEqual(proposal["row_proposals_count"],2)
        rows=proposal["table_header_anchored_row_proposals"]
        self.assertTrue(all(q["quantity_original_ocr"]=="60" for q in rows))
        self.assertTrue(all(q["amount_original_ocr"]=="164.95" for q in rows))
        self.assertEqual(proposal["verified_table_rows"],0)

    def test_unanchored_amounts_cannot_be_assumed_final_total(self):
        src=fixture()
        for v in src["variants"]:
            v["source_words"]=[token("PES",315,110),token("NET",460,110),
                               token("ANT",500,110),token("20",317,180),
                               token("1140.00",500,180)]
        self.assertEqual(mod.propose(src,700,500)["row_proposals_count"],0)

    def test_split_total_value_including_tax_header_anchor(self):
        # Source layout of a general retail tax invoice: the amount heading
        # is printed as two words, with the second OCR-joined to (incl tax).
        tokens=[token("Item",173,690,25),token("Qty",690,690,24),
                token("Total",753,690,25),token("ValuetInclof",783,690,64),
                token("PACKAGED",174,736,86),token("SAMPLE",264,736,72),
                token("75",692,736,24),token("3813.75",795,736,60)]
        fixture={
          "status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
          "posting_eligible":False,"variants":[
            {"variant":"gray_2x","posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":tokens},
            {"variant":"clahe_2x","posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":tokens}
          ]}
        result=mod.propose(fixture,950,1600)
        self.assertEqual(result["row_proposals_count"],2)
        self.assertTrue(all(row["quantity_original_ocr"]=="75" and
                            row["amount_original_ocr"]=="3813.75" and
                            row["posting_eligible"] is False for row in
                            result["table_header_anchored_row_proposals"]))
        self.assertEqual(result["verified_table_rows"],0)

    def test_inclusive_value_without_total_heading_is_not_assumed_amount(self):
        tokens=[token("Item",173,690,25),token("Qty",690,690,24),
                token("ValuetInclof",783,690,64),
                token("PACKAGED",174,736,86),token("SAMPLE",264,736,72),
                token("75",692,736,24),token("3813.75",795,736,60)]
        variants=[{"variant":name,"posting_eligible":False,
                   "source_boxes_are_original_pixels":True,"source_words":tokens}
                  for name in ("gray_2x","clahe_2x")]
        result=mod.propose({"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
                            "posting_eligible":False,"variants":variants},950,1600)
        self.assertEqual(result["row_proposals_count"],0)

    def test_printed_total_stops_tax_summary_becoming_phantom_item(self):
        f=fixture()
        for variant in f["variants"]:
            variant["source_words"]+= [
                token("TOTAL",55,370,w=65),
                token("ADJUSTMENT",42,425,w=112),
                token("3",251,425,w=28),
                token("10.00",412,425,w=67)]
        result=mod.propose(f,600,700)
        # Two OCR views of exactly one genuine printed item = two hypotheses.
        self.assertEqual(result["row_proposals_count"],2)
        self.assertTrue(all(row["quantity_original_ocr"]=="20" for row
                            in result["table_header_anchored_row_proposals"]))
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["accounting_write_permitted"])

    def test_missing_amount_header_blocks_row_proposals(self):
        result=mod.propose(fixture(missing_headers=True),600,700)
        self.assertEqual(result["row_proposals_count"],0)
    def test_unlabeled_number_does_not_become_invoice_field(self):
        f=fixture()
        for v in f["variants"]:
            v["source_words"]=[token("2026X0099",90,40),token("1300.00",210,65)]
        z=mod.propose(f,600,700)
        self.assertEqual(z["field_proposals_count"],0)
        self.assertEqual(z["row_proposals_count"],0)
    def test_invalid_box_rejected_and_source_values_unmodified(self):
        f=fixture()
        t=f["variants"][0]["source_words"][0]
        t["original_source_box"]=[-2,35,90,60]
        with self.assertRaises(ValueError):mod.propose(f,600,700)
    def test_duplicate_view_rejected(self):
        f=fixture();f["variants"][1]["variant"]="gray_2x"
        with self.assertRaises(ValueError):mod.propose(f,600,700)
    def test_numerical_row_must_have_source_description(self):
        f=fixture()
        for v in f["variants"]:
            v["source_words"]=[w for w in v["source_words"] if
                w["original_source_text"] not in ("PACKAGED","SAMPLE")]
        self.assertEqual(mod.propose(f,600,700)["row_proposals_count"],0)
    def test_posting_false_even_if_both_views_agree(self):
        z=mod.propose(fixture(),600,700)
        self.assertFalse(z["accounting_write_permitted"])
        self.assertFalse(z["release_approved"])
        self.assertTrue(all(x["posting_eligible"] is False for x in
                            z["field_label_anchored_proposals"]))
    def test_bounded_word_count_fail_closed(self):
        f=fixture()
        f["variants"][1]["source_words"]=[token("ITEM",10,10)]*601
        with self.assertRaises(ValueError):mod.propose(f,600,700)
    def test_r252_second_printed_header_after_empty_first(self):
        # The first source-printed header has no physical item rows. A later
        # table with its own headings and numeric anchors must be considered.
        words=[
            token("DESCRIPTION",35,75,135),token("QTY",250,75,38),
            token("AMOUNT",420,75,88),
            token("DESCRIPTION",35,255,135),token("QTY",250,255,38),
            token("AMOUNT",420,255,88),
            token("RECOVERABLE",35,310,132),token("SAMPLE",175,310,58),
            token("8",251,310,28),token("48.00",422,310,58)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,650,700)
        self.assertEqual(result["row_proposals_count"],2)
        self.assertTrue(all(row["quantity_original_ocr"]=="8"
                            and row["amount_original_ocr"]=="48.00"
                            and row["posting_eligible"] is False
                            for row in result["table_header_anchored_row_proposals"]))
        self.assertFalse(result["accounting_write_permitted"])
        self.assertTrue(all(row["header_source_boxes"]["description"]==[35,255,170,275] for row in result["table_header_anchored_row_proposals"]))

    def test_r252_punctuated_header_labels_remain_source_literal(self):
        words=[token("DESCRIPTION:",35,255,145),
               token("QTY.",250,255,40),token("AMOUNT:",420,255,95),
               token("PRODUCT",35,310,85),token("SAMPLE",125,310,75),
               token("4",251,310,28),token("80.50",423,310,55)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,650,700)
        self.assertEqual(result["row_proposals_count"],2)
        for row in result["table_header_anchored_row_proposals"]:
            self.assertEqual(row["amount_original_ocr"],"80.50")
            self.assertEqual(row["header_source_boxes"]["amount"],[420,255,515,275])
            self.assertFalse(row["row_complete_certified"])
        self.assertEqual(words[0]["original_source_text"],"DESCRIPTION:")
        self.assertEqual(words[1]["original_source_text"],"QTY.")

    def test_r252_punctuation_does_not_replace_required_header(self):
        words=[token("QTY.",250,255,40),token("AMOUNT:",420,255,95),
               token("4",251,310,28),token("80.50",423,310,55)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,650,700)
        self.assertEqual(result["row_proposals_count"],0)
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["release_approved"])
    def test_r253_seven_printed_rows_survive_page_fraction_cutoff(self):
        # Seven physical product rows span almost half the printed page.
        # The former 28%-height limit suppressed the lower three.
        words=[token("DESCRIPTION",35,130,140),token("QTY",250,130,42),
               token("AMOUNT",410,130,92)]
        for i in range(7):
            y=195+45*i
            words.extend([token("PRODUCT",35,y,93),
                          token("CODE"+str(i+1),135,y,65),
                          token(str(i+1),251,y,28),
                          token(str(100+i)+".00",420,y,72)])
        # Printed financial footer must suppress a fake numeric summary row
        # even though that row falls within the widened source-search window.
        words.extend([token("TOTAL",35,510,65),
                      token("FREIGHT",35,530,88),
                      token("2",251,530,28),token("25.00",420,530,67)])
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,650,800)
        self.assertEqual(result["row_proposals_count"],14)
        self.assertEqual(
            [r["description_original_ocr"] for r in
             result["table_header_anchored_row_proposals"][:7]],
            ["PRODUCT CODE"+str(i+1) for i in range(7)])
        self.assertTrue(all(r["posting_eligible"] is False
                            and r["row_complete_certified"] is False
                            for r in result["table_header_anchored_row_proposals"]))
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["accounting_write_permitted"])
    def test_r254_two_separate_printed_item_sections_are_both_proposed(self):
        # A real page can contain independent goods and services sections.
        # A valid early item must not mask a later independently headed table.
        words=[
            token("DESCRIPTION",35,105,140), token("QTY",250,105,42),
            token("AMOUNT",410,105,92),
            token("PART",35,169,85),token("ALPHA",125,169,75),
            token("2",253,169,25),token("120.00",420,169,74),
            token("SUBTOTAL",35,262,100),
            token("DESCRIPTION",35,413,140),token("QTY",250,413,42),
            token("AMOUNT",410,413,92),
            token("PART",35,473,85),token("BETA",125,473,75),
            token("3",253,473,25),token("66.00",420,473,65),
            token("TOTAL",35,563,67)
        ]
        source={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
                "posting_eligible":False,"variants":[
            {"variant":variant,"posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":words}
            for variant in ("gray_2x","clahe_2x")]}
        result=mod.propose(source,650,800)
        rows=result["table_header_anchored_row_proposals"]
        self.assertEqual(len(rows),4)
        self.assertEqual(
            sorted((r["description_original_ocr"],r["quantity_original_ocr"],
                    r["amount_original_ocr"]) for r in rows),
            [("PART ALPHA","2","120.00"),("PART ALPHA","2","120.00"),
             ("PART BETA","3","66.00"),("PART BETA","3","66.00")])
        self.assertEqual(len(set(tuple(r["header_source_boxes"]["description"])
                                 for r in rows)),2)
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["accounting_write_permitted"])

    def test_r254_overlapping_header_baselines_do_not_duplicate_source_rows(self):
        # One physical printed header split over two baselines can be
        # detected by both header bands: emit a numeric row only once/view.
        words=[token("DESCRIPTION",35,110,140),
               token("QTY",250,129,42), token("AMOUNT",410,129,92),
               token("PRODUCT",35,190,93),token("SAMPLE",135,190,62),
               token("5",253,190,25),token("125.00",420,190,72)]
        source={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
                "posting_eligible":False,"variants":[
            {"variant":variant,"posting_eligible":False,
             "source_boxes_are_original_pixels":True,"source_words":words}
            for variant in ("gray_2x","clahe_2x")]}
        result=mod.propose(source,650,680)
        self.assertEqual(result["row_proposals_count"],2)
        self.assertTrue(all(row["description_original_ocr"]=="PRODUCT SAMPLE"
                            for row in result["table_header_anchored_row_proposals"]))
        self.assertFalse(result["posting_eligible"])

    def test_r255_high_resolution_right_aligned_amount_and_qty(self):
        # On larger phone photos, actual cells can be displaced >90 original
        # pixels from heading centres even though printed columns match.
        tokens=[
            token("DESCRIPTION",155,190,195),
            token("QTY",1350,190,55),
            token("AMOUNT",1950,190,105),
            token("PACKAGED",155,278,130),token("TEST",290,278,95),
            token("12",1440,278,38),
            token("1250.00",2175,278,105)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
               {"variant":name,"posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":tokens}
               for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,2600,1600)
        self.assertEqual(result["row_proposals_count"],2)
        self.assertTrue(all(row["quantity_original_ocr"]=="12" and
                            row["amount_original_ocr"]=="1250.00"
                            for row in result["table_header_anchored_row_proposals"]))
        self.assertFalse(result["accounting_write_permitted"])

    def test_r255_two_competing_right_aligned_amounts_still_refused(self):
        tokens=[
            token("DESCRIPTION",155,190,195),
            token("QTY",1350,190,55),
            token("AMOUNT",1950,190,105),
            token("PACKAGED",155,278,130),token("TEST",290,278,95),
            token("12",1440,278,38),
            token("999.00",2080,278,88),
            token("1250.00",2175,278,105)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
               {"variant":name,"posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":tokens}
               for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,2600,1600)
        self.assertEqual(result["row_proposals_count"],0)
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["release_approved"])

    def test_r256_parenthesized_unit_note_does_not_hijack_qty_heading(self):
        # Parenthesized PCS is a unit note, not the true quantity column.
        # The correct original source QTY header is physically farther right.
        tokens=[
            token("ITEM",100,195,65),
            token("(PCS)",510,195,72),token("QTY",700,195,55),
            token("AMOUNT",1010,195,115),
            token("SAMPLE",102,275,112),token("PRODUCT",217,275,122),
            token("4",706,275,28),token("350.00",1030,275,85)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
               {"variant":name,"posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":tokens}
               for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,1300,850)
        self.assertEqual(result["row_proposals_count"],2)
        for row in result["table_header_anchored_row_proposals"]:
            self.assertEqual(row["quantity_original_ocr"],"4")
            self.assertEqual(row["header_source_boxes"]["quantity"],[700,195,755,215])
            self.assertEqual(row["amount_original_ocr"],"350.00")
            self.assertFalse(row["posting_eligible"])
        self.assertEqual(tokens[1]["original_source_text"],"(PCS)")

    def test_r256_only_parenthesized_unit_without_qty_is_not_a_header(self):
        tokens=[token("ITEM",100,195,65),token("(PCS)",510,195,72),
                token("AMOUNT",1010,195,115),
                token("SAMPLE",102,275,112),token("PRODUCT",217,275,122),
                token("4",516,275,28),token("350.00",1030,275,85)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
               {"variant":name,"posting_eligible":False,
                "source_boxes_are_original_pixels":True,"source_words":tokens}
               for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,1300,850)
        self.assertEqual(result["row_proposals_count"],0)
        self.assertEqual(result["verified_table_rows"],0)
        self.assertFalse(result["accounting_write_permitted"])

    def test_r257_hsn_and_free_column_bounds_do_not_steal_quantity(self):
        # Wide physical column gaps may contain HSN and FREE values, neither
        # is the printed quantity cell even if both are numeric OCR tokens.
        words=[
            token("PRODUCT",322,187,65),
            token("HSN.",594,185,44),token("QTY",682,186,41),
            token("FREE",748,186,51),token("AMOUNT",1257,188,64),
            token("SAMPLE",300,218,95),
            token("19021900",582,217,69),token("20",687,217,13),
            token("0.000",757,217,34),token("1085.71",1269,217,50)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,1600,900)
        self.assertEqual(result["row_proposals_count"],2)
        for row in result["table_header_anchored_row_proposals"]:
            self.assertEqual(row["quantity_original_ocr"],"20")
            self.assertEqual(row["amount_original_ocr"],"1085.71")
            self.assertFalse(row["row_complete_certified"])
        self.assertFalse(result["accounting_write_permitted"])

    def test_r257_numeric_neighbours_without_headers_remain_ambiguous(self):
        words=[token("PRODUCT",322,187,65),token("QTY",682,186,41),
               token("AMOUNT",1257,188,64),token("SAMPLE",300,218,95),
               token("19021900",582,217,69),token("20",687,217,13),
               token("0.000",757,217,34),token("1085.71",1269,217,50)]
        src={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
             "posting_eligible":False,"variants":[
                 {"variant":name,"posting_eligible":False,
                  "source_boxes_are_original_pixels":True,"source_words":words}
                 for name in ("gray_2x","clahe_2x")]}
        result=mod.propose(src,1600,900)
        self.assertEqual(result["row_proposals_count"],0)
        self.assertEqual(result["verified_table_rows"],0)

if __name__=="__main__":
    unittest.main(verbosity=2)
