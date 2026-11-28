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

    def test_q08_post_tax_summary_discount_and_rbiin_collectable_state_tax(self) -> None:
        raw_q08 = """
        SRI VENKATESHWARA AGENCIES
        GSTIN: 29AGFPL5940F1ZA
        BALAJI TRADING CO.
        GSTIN: 29ABZPB5530G1ZE
        Invoice No: INV 11874 Date: 12-11-2026
        <table>
          <tr><th>Sr</th><th>Product</th><th>HSN</th><th>QTY</th><th>RATE</th><th>GST%</th><th>DISC</th><th>AMOUNT</th></tr>
          <tr><td>1</td><td>ITEM ONE</td><td>09109100</td><td>51</td><td>178.90</td><td>5.0</td><td>0</td><td>9123.79</td></tr>
        </table>
        <table>
          <tr><th>GST%</th><th>SALE VAL</th><th>SGST%</th><th>AMOUNT</th><th></th><th>TOT ITEMS:</th><th>1.00</th><th>SUB TOTAL:</th><th>9123.82</th></tr>
          <tr><td>5.0</td><td>9123.82</td><td>2.5</td><td>228.09</td><td></td><td>TOT QTY:</td><td>51.00</td><td>DISCOUNT:</td><td>100.00</td></tr>
          <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>SGST AMT:</td><td>228.09</td></tr>
          <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>CGST AMT:</td><td>228.09</td></tr>
          <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td>NET AMT:</td><td>9,480.00</td></tr>
        </table>
        For SRI VENKATESHWARA AGENCIES
        """
        can08 = gst_parser.parse_document_text_to_canonical(raw_q08, known_client_gstin=CLIENT_GSTIN)
        self.assertAlmostEqual(can08["creditNoteTotal"], 100.00, places=2)
        self.assertAlmostEqual(can08["invoiceTotal"], 9480.00, places=2)
        self.assertTrue(can08["_audit"]["fully_balanced"])

        raw_rbi = f"""
        SIDDAGANGA AGENCIES
        GSTIN/UIN: 29BVZPC3601A1ZR
        BALAJI TRADING CO.
        GSTIN/UIN: {CLIENT_GSTIN}
        Invoice No : RBIIN022462 Invoice Date : 13-Nov-2026
        <table>
          <tr><th>Sr</th><th>Item Code - Item Description</th><th>HSN</th><th>Qty</th><th>Rate</th><th>CGST %</th><th>UT / SGST %</th><th>IGST %</th><th>Taxable Amt</th><th>Total Amt</th></tr>
          <tr><td>1</td><td>COLIN TRG 500ML</td><td>34025000</td><td>3EA</td><td>92.45</td><td>9.00% 24.71</td><td>9.00% 24.71</td><td>0.00% 0.00</td><td>274.58</td><td>324.00</td></tr>
          <tr><td>2</td><td>HARPIC DRNX</td><td>34025000</td><td>20EA</td><td>25.42</td><td>9.00% 40.27</td><td>9.00% 40.27</td><td>0.00% 0.00</td><td>447.39</td><td>527.93</td></tr>
          <tr><td colspan="8">Taxable Amount</td><td>721.97</td></tr>
          <tr><td colspan="8">UT/SGST</td><td>64.98</td></tr>
          <tr><td colspan="6">Collectable Amount</td><td>0/23</td><td>63.78</td><td>721.97</td><td>852.00</td></tr>
        </table>
        <table>
          <tr><th rowspan="2">GST Summary</th><th rowspan="2">Taxable Value</th><th colspan="2">Central Tax</th><th colspan="2">State Tax</th><th colspan="2">IGST Tax</th><th rowspan="2">Total Tax Amount</th></tr>
          <tr><th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th></tr>
          <tr><td>GST 18%</td><td>721.97</td><td>9.00%</td><td>64.98</td><td>9.00%</td><td>64.98</td><td>0.00%</td><td>0.00</td><td>129.96</td></tr>
          <tr><td>Total</td><td>721.97</td><td></td><td>64.98</td><td></td><td>64.98</td><td></td><td>0.00</td><td>129.96</td></tr>
        </table>
        TotalAmount(in Words) :Rupees Eight Hundred Fifty Two Only
        """
        can_rbi = gst_parser.parse_document_text_to_canonical(raw_rbi, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(len(can_rbi["rows"]), 2)
        self.assertAlmostEqual(can_rbi["igstTotal"], 0.00, places=2)
        self.assertAlmostEqual(can_rbi["sgstTotal"], 64.98, places=2)
        self.assertAlmostEqual(can_rbi["invoiceTotal"], 852.00, places=2)
        self.assertTrue(can_rbi["_audit"]["fully_balanced"])

    def test_inline_parenthesized_tax_rate_and_same_page_duplicate_table_dedup(self) -> None:
        raw_bair = f"""
        Sri Bairaveshwara Enterprises
        GSTIN: 29AWLPR2325L3ZX
        Bill To: Balaji Trading Co
        GSTIN: {CLIENT_GSTIN}
        Invoice No.: FY26-27/6902 Date: 10-11-2026
        <table>
          <tr><th>#</th><th>Item Name</th><th>HSN/SAC</th><th>Quantity</th><th>Price/Unit</th><th>Taxable Amount</th><th>CGST</th><th>SGST</th><th>Amount</th></tr>
          <tr><td>1</td><td>RICH MARIE 80 GM</td><td>19053100</td><td>2</td><td>₹ 361.90</td><td>₹ 723.81</td><td>₹ 18.10 (2.5%)</td><td>₹ 18.10 (2.5%)</td><td>₹ 760.00</td></tr>
          <tr><td colspan="5">Total</td><td>₹ 723.81</td><td>₹ 18.10</td><td>₹ 18.10</td><td>₹ 760.00</td></tr>
        </table>
        Total: ₹ 760.00
        Invoice Amount In Words: Seven Hundred Sixty Rupees only
        """
        can_b = gst_parser.parse_document_text_to_canonical(raw_bair, known_client_gstin=CLIENT_GSTIN)
        self.assertAlmostEqual(can_b["cgstTotal"], 18.10, places=2)
        self.assertAlmostEqual(can_b["rows"][0]["gstRate"], 5.0, places=2)
        self.assertTrue(can_b["_audit"]["fully_balanced"])

        dup_tbl = f"""
        SRI KRISHNA AGENCIES
        GSTIN: 29AAMFS8246C1ZU
        To: BALAJI TR CO
        GSTIN: {CLIENT_GSTIN}
        Page 1 of 2
        Inv No: OIS01022607727 Date: 03/11/2026
        <table><tr><th>No</th><th>Product Name</th><th>HSN Code</th><th>Qty</th><th>Rate</th><th>GST %</th><th>Total Amt</th></tr>
        <tr><td>1</td><td>Spice</td><td>09109100</td><td>72</td><td>8.66</td><td>5.00</td><td>617.64</td></tr></table>
        <table><tr><th>No</th><th>Product Name</th><th>HSN Code</th><th>Qty</th><th>Rate</th><th>GST %</th><th>Total Amt</th></tr>
        <tr><td>1</td><td>Spice</td><td>09109100</td><td>72</td><td>8.66</td><td>5.00</td><td>617.64</td></tr></table>
        """
        can_dup = gst_parser.parse_document_text_to_canonical(dup_tbl, known_client_gstin=CLIENT_GSTIN)
        self.assertEqual(len(can_dup["rows"]), 1)

    def test_durga_space_decimal_and_integer_grand_total(self) -> None:
        raw_d = f"""
        DURGA DISTRIBUTORS
        GSTIN: 29CSCPD9072P1Z2
        Balaji Trading Co
        GSTIN: {CLIENT_GSTIN}
        INVOICE NO: I73564927003447
        INVOICE DATE: 31-Oct-2026
        <table>
          <tr><th>SN.</th><th>HSN CODE</th><th>PRODUCT DESCRIPTION</th><th>QTY</th><th>R P U</th><th>GROSS AMT</th><th>DISC AMT</th><th>TAXABLE AMOUNT</th><th>GST%</th><th>GST AMT</th><th>NET AMOUNT</th></tr>
          <tr><td>1</td><td>34011190</td><td>BABY SOAP</td><td>12</td><td>77.42</td><td>929.04</td><td>55.74</td><td>873.30</td><td>5</td><td>43.66</td><td>916.96</td></tr>
          <tr><td>2</td><td>33049990</td><td>FACE WASH</td><td>6</td><td>145.62</td><td>873.72</td><td>52.42</td><td>821.30</td><td>18</td><td>147.8 3</td><td>969.13</td></tr>
          <tr><td colspan="5">TOTAL</td><td>1802.76</td><td>108.16</td><td>1694.60</td><td></td><td>191.4 9</td><td>1886.09</td></tr>
        </table>
        <table>
          <tr><th>SALE AMT</th><th>DISC AMT</th><th>TAXA. AMT</th><th>SGST%</th><th>SGST AMT</th><th>CGST %</th><th>CGST AMT</th><th>Total %</th><th>Total AMT</th></tr>
          <tr><td>929.04</td><td>55.74</td><td>873.30</td><td>2.5</td><td>21.83</td><td>2.5</td><td>21.83</td><td>5</td><td>43.66</td></tr>
          <tr><td>873.72</td><td>52.42</td><td>821.30</td><td>9</td><td>73.92</td><td>9</td><td>73.92</td><td>18</td><td>147.83</td></tr>
        </table>
        Rupees One Thousand Eight Hundred And Eighty-Six Only
        ROUND OFF -0.09
        GRAND TOTAL 1886
        """
        can_d = gst_parser.parse_document_text_to_canonical(raw_d, known_client_gstin=CLIENT_GSTIN)
        self.assertAlmostEqual(can_d["rows"][1]["rate"], 145.62, places=2)
        self.assertAlmostEqual(can_d["rows"][1]["cgst"], 73.92, places=2)
        self.assertAlmostEqual(can_d["invoiceTotal"], 1886.0, places=2)
        self.assertLessEqual(abs(can_d["roundOff"] - (-0.10)), 0.02)
        self.assertTrue(can_d["_audit"]["fully_balanced"])

    def test_bairava_two_col_kv_summary_table_with_thead_subtotal_and_sgst_cgst(self) -> None:
        raw_b = f"""
        BAIRAVA ENTERPRISES
        GSTIN: 29BURPR6552A1Z6
        BALAJI TREDING, CO-M.P.C
        GSTN NO.: {CLIENT_GSTIN}
        <table><tr><th>INVOICE NO.</th><th>DATE</th></tr><tr><td>8723</td><td>31/10/2026</td></tr></table>
        <table>
          <thead><tr><th>S.L.</th><th>Descriptions of Goods</th><th>MRP</th><th>GST %</th><th>HSN</th><th>QTY</th><th>RATE</th><th>DIS %</th><th>AMOUNT</th></tr></thead>
          <tbody>
            <tr><td>1.</td><td>ASHWINI OIL 170ML MRP 196</td><td>196.00</td><td>5 %</td><td>30049014</td><td>3PC</td><td>169.70</td><td>3.00</td><td>493.83</td></tr>
            <tr><td>2.</td><td>HP LION 10S MRP 200/-</td><td>200.00</td><td>5 %</td><td>30051090</td><td>3PC</td><td>85.71</td><td>6.00</td><td>241.70</td></tr>
            <tr><td>3.</td><td>HP WP 100+36 FREE MRP 300/-</td><td>300.00</td><td>5 %</td><td>30051090</td><td>3PC</td><td>190.48</td><td>5.00</td><td>542.87</td></tr>
            <tr><td>4.</td><td>MEDIMIX 3PK 125GM RS 165/-</td><td>190.00</td><td>5 %</td><td>34011190</td><td>3PC</td><td>164.50</td><td></td><td>493.50</td></tr>
            <tr><td>5.</td><td>MEDIMIX 3PK 75GM 111/-</td><td>111.00</td><td>5 %</td><td>34011190</td><td>3PC</td><td>96.10</td><td></td><td>288.30</td></tr>
            <tr><td>6.</td><td>HC NISHA POW BLACK MRP 10*15</td><td>150.00</td><td>18 %</td><td>33059040</td><td>5SHEE</td><td>84.75</td><td>10.00</td><td>381.37</td></tr>
            <tr><td>7.</td><td>HC NR HENNA MRP 15</td><td>300.00</td><td>18 %</td><td>33059040</td><td>6BDL</td><td>101.69</td><td>10.00</td><td>549.13</td></tr>
            <tr><td>8.</td><td>PIGEON CAT 6*40 MRP 240</td><td>240.00</td><td>5 %</td><td>96032100</td><td>2SHEE</td><td>114.29</td><td></td><td>228.58</td></tr>
          </tbody>
        </table>
        Rs. Three Thousand Five Hundred and One only
        <table>
          <thead><tr><th>SUB TOTAL</th><th>3219.28</th></tr></thead>
          <tbody>
            <tr><td>SGST</td><td>140.96</td></tr>
            <tr><td>CGST</td><td>140.96</td></tr>
            <tr><td>ROUND OFF</td><td>-0.20</td></tr>
            <tr><td>GRAND TOTAL</td><td>3501.00</td></tr>
          </tbody>
        </table>
        """
        can_b = gst_parser.parse_document_text_to_canonical(raw_b, known_client_gstin=CLIENT_GSTIN)
        self.assertAlmostEqual(can_b["taxableTotal"], 3219.28, places=2)
        self.assertAlmostEqual(can_b["cgstTotal"], 140.96, places=2)
        self.assertAlmostEqual(can_b["sgstTotal"], 140.96, places=2)
        self.assertAlmostEqual(can_b["roundOff"], -0.20, places=2)
        self.assertAlmostEqual(can_b["invoiceTotal"], 3501.00, places=2)
        self.assertTrue(can_b["_audit"]["fully_balanced"])

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
