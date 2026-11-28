#!/usr/bin/env python3
"""Regression unit tests for InvoiceVisionChild v2 Python GST engine fixes."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE_DIR))

import batch_manager  # noqa: E402
import gst_math  # noqa: E402
import gst_parser  # noqa: E402
import supplier_memory  # noqa: E402


CLIENT_GSTIN = "29ABZPB5530G1ZE"


class EngineRegressionTests(unittest.TestCase):
    def test_q10_ack_no_rejected_not_mutated_to_fake_gstin(self) -> None:
        fixed, ok, reason = gst_math.repair_gstin("112633543824778")
        self.assertFalse(ok)
        self.assertEqual(reason, "not_gstin_pattern")
        self.assertEqual(fixed, "112633543824778")
        plain = f"IRN: abc\nAck No. : 112633543824778\nSeller GSTIN: 29AFQPC6468R1ZC\nParty : Balaji Trading Co.\nGSTIN/UIN : {CLIENT_GSTIN}\n"
        self.assertEqual(gst_parser.find_gstins_in_text(plain), ["29AFQPC6468R1ZC", CLIENT_GSTIN])

    def test_q10_rowspan_hsn_table_and_output_tax_footer(self) -> None:
        raw = """
        Invoice No. C211
        Dated 13-Nov-26
        Benaka Enterprises
        GSTIN/UIN: 29AFQPC6468R1ZC
        Ack No. : 112633543824778
        Party : Balaji Trading Co.,
        GSTIN/UIN : 29ABZPB5530G1ZE
        <table>
          <tr><th>Sl No.</th><th>Description of Goods</th><th>HSN/SAC</th><th>Quantity</th><th>Rate (Incl. of Tax)</th><th>Rate per bags</th><th>Amount</th></tr>
          <tr><td>1</td><td>Sugar S1</td><td>17011490</td><td>15 bags</td><td>2,725.00</td><td>2,595.24</td><td>bags 38,928.60</td></tr>
          <tr><td></td><td>CGST Output Tax @ 2.5%</td><td></td><td></td><td></td><td>2.50 %</td><td>973.22</td></tr>
          <tr><td></td><td>SGST Output Tax @ 2.5%</td><td></td><td></td><td></td><td>2.50 %</td><td>973.22</td></tr>
          <tr><td></td><td>Less : ROUND OFF</td><td></td><td></td><td></td><td></td><td>(-)0.04</td></tr>
          <tr><td></td><td>Total</td><td></td><td>15 bags</td><td></td><td></td><td>₹ 40,875.00</td></tr>
        </table>
        <table>
          <tr><th rowspan="2">HSN/SAC</th><th rowspan="2">Taxable Value</th><th colspan="2">CGST</th><th colspan="2">SGST/UTGST</th><th rowspan="2">Total Tax Amount</th></tr>
          <tr><th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th></tr>
          <tr><td>17011490</td><td>38,928.60</td><td>2.50%</td><td>973.22</td><td>2.50%</td><td>973.22</td><td>1,946.44</td></tr>
        </table>
        Amount Chargeable (in words): INR Forty Thousand Eight Hundred Seventy Five Only
        for Benaka Enterprises
        """
        can = gst_parser.parse_document_text_to_canonical(raw, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(can["seller"]["gstin"], "29AFQPC6468R1ZC")
        self.assertEqual(can["buyer"]["gstin"], CLIENT_GSTIN)
        self.assertEqual(len(can["rows"]), 1)
        self.assertAlmostEqual(can["rows"][0]["gstRate"], 5.0, places=2)
        self.assertAlmostEqual(can["invoiceTotal"], 40875.00, places=2)
        self.assertAlmostEqual(can["roundOff"], -0.04, places=2)
        self.assertTrue(can["_audit"]["fully_balanced"])

    def test_q08_q15_two_col_html_header_seller_buyer_not_swapped(self) -> None:
        raw_q15 = """
        <table>
          <tr><td>LAKSHMIVENKATESHWARA AGENCIES</td><td>M/s BALAJI TRADING CO</td></tr>
          <tr><td>D.D. No.: 2ND MAIN</td><td>APMC YARD TUMKUR GST: 29ABZPB5530GIZE</td></tr>
          <tr><td>FSSAI NO: GSTIN: 29APFPT8050D1ZO</td><td>GST INVOICE Invoice No.: LVA25/00932 Date: 11-11-2026</td></tr>
        </table>
        <table>
          <tr><th>Sn.</th><th>Product</th><th>HSN</th><th>QTY</th><th>RATE</th><th>Amount</th></tr>
          <tr><td>1.</td><td>ARUN CRISTAL 1KG</td><td>25010010</td><td>88</td><td>171.00</td><td>15000.00</td></tr>
        </table>
        GRAND TOTAL 15000.00
        For LAKSHMIVENKATESHWARA AGENCIES
        """
        can15 = gst_parser.parse_document_text_to_canonical(raw_q15, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(can15["seller"]["gstin"], "29APFPT8050D1ZO")
        self.assertEqual(can15["buyer"]["gstin"], CLIENT_GSTIN)

        raw_q08 = """
        <table>
          <tr><td colspan="4">REGISTERED NAME: AMAZON DISTRIBUTORS Pvt LTD.</td><td>Customer Name: C-7-Balaji Trading Co.</td><td>INVOICE NO: ABTMK-26-I037051</td></tr>
          <tr><td>GSTN: 29AAFC A9197E1Z9</td><td>CIN: U51909KA2006PTC040695</td><td>GSTN: 29ABZPB5530G1ZE</td><td>CHANNEL: WS</td><td></td><td></td></tr>
        </table>
        <table>
          <tr><th>Sl</th><th>Item Description</th><th>HSN</th><th>Pcs</th><th>Taxable Amt</th><th>GST %</th><th>CGST Amt</th><th>SGST Amt</th><th>Net Amt</th></tr>
          <tr><td>1</td><td>Item A</td><td>33051090</td><td>3</td><td>1000.00</td><td>5.00</td><td>25.00</td><td>25.00</td><td>1050.00</td></tr>
        </table>
        Net Payable 1050.00
        """
        can08 = gst_parser.parse_document_text_to_canonical(raw_q08, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(can08["seller"]["gstin"], "29AAFCA9197E1Z9")
        self.assertEqual(can08["buyer"]["gstin"], CLIENT_GSTIN)

    def test_q12_metro_buyer_pan_fills_known_client_gstin(self) -> None:
        raw = """
        Cash and Carry India Ltd
        GSTIN: 29AACCM4684P1ZN
        Document Number: 29M3100003217028
        Date: 11/11/2026
        Billed To: BALAJI TRADING CO.,
        PAN: ABZPB5530G
        Bill To GSTIN:
        <table>
          <tr><th>Sr.No.</th><th>HSN/SAC</th><th>Item Name</th><th>Qty (PCS)</th><th>Total Value(Incl.of Tax)(Rs)</th></tr>
          <tr><td>1</td><td>33061020</td><td>Toothpaste</td><td>6.00</td><td>1050.00</td></tr>
        </table>
        <table>
          <tr><th rowspan="2">HSN Code/SAC</th><th rowspan="2">Taxable Value</th><th colspan="2">CGST</th><th colspan="2">SGST</th></tr>
          <tr><th>Rate (%)</th><th>Amt (Rs.)</th><th>Rate (%)</th><th>Amt (Rs.)</th></tr>
          <tr><td>33061020</td><td>1000.00</td><td>2.50</td><td>25.00</td><td>2.50</td><td>25.00</td></tr>
        </table>
        Grand Total 1050.00
        """
        can = gst_parser.parse_document_text_to_canonical(raw, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(can["seller"]["gstin"], "29AACCM4684P1ZN")
        self.assertEqual(can["buyer"]["gstin"], CLIENT_GSTIN)
        self.assertTrue(can["_audit"]["fully_balanced"])

    def test_q06_single_row_line_total_ocr_slip_and_s_dtgst(self) -> None:
        raw = """
        NANDI MARKETING
        GSTN NO : 29AAQFM2308H1Z3
        BALAJI TRADING CO.
        GSTN NO : 29ABZPB5530G1ZE
        FSSAI NO : 0
        Bill NO : E79018
        Bill Date : 09/11/2026
        <table>
          <tr><th>SL</th><th>HSN No</th><th>Product Name</th><th>Total Units</th><th>Taxable Amt</th><th>GST %</th><th>CGST Amt</th><th>S/DTGST Amt</th><th>Net Amt</th></tr>
          <tr><td>1</td><td>34011190</td><td>LIRIL BAR</td><td>12</td><td>797.66</td><td>5</td><td>19.94</td><td>19.94</td><td>832.54</td></tr>
          <tr><td>Total</td><td></td><td></td><td>12</td><td>797.66</td><td></td><td>19.94</td><td>19.94</td><td>837.54</td></tr>
        </table>
        Net Payable Amt 838.00
        Eight Hundred Thirty Eight Only
        """
        can = gst_parser.parse_document_text_to_canonical(raw, known_client_gstin=CLIENT_GSTIN)
        self.assertAlmostEqual(can["rows"][0]["lineTotal"], 837.54, places=2)
        self.assertAlmostEqual(can["roundOff"], 0.46, places=2)
        self.assertTrue(can["_audit"]["fully_balanced"])

    def test_q16_amount_in_words_paise_and_scheme_column(self) -> None:
        self.assertAlmostEqual(
            gst_parser.extract_amount_in_words("Two Thousand Nine Hundred Eight Rupees & Ninety Six Paise Only") or 0.0,
            2908.96,
            places=2,
        )

    def test_supplier_memory_never_stores_or_learns_client_gstin(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "supplier_memory.db")
            res = supplier_memory.record_supplier_learning(
                db_path=db_path,
                gstin=CLIENT_GSTIN,
                canonical_name="BALAJI TRADING CO.",
                invoice_number="INV-1",
                hsn_rates=[{"hsn": "33061020", "gstRate": 18.0}],
                client_gstin=CLIENT_GSTIN,
            )
            self.assertFalse(res.get("saved", False))
            profile = supplier_memory.lookup_supplier_profile(db_path, CLIENT_GSTIN, client_gstin=CLIENT_GSTIN)
            self.assertIsNone(profile)

    def test_batch_manager_imports_re_and_daemon_log_dir(self) -> None:
        self.assertTrue(hasattr(batch_manager, "re"))
        with tempfile.TemporaryDirectory() as td:
            mgr = batch_manager.ManagerAgent(
                llama_server=Path(td) / "llama-server.exe",
                lighton_model=Path(td) / "lighton.gguf",
                lighton_mmproj=Path(td) / "mmproj.gguf",
                paddlex_cache=Path(td) / "paddlex",
                cache_dir=Path(td),
                daemon_log_dir=Path(td) / "logs",
            )
            self.assertEqual(mgr.daemon_log_dir, Path(td) / "logs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
