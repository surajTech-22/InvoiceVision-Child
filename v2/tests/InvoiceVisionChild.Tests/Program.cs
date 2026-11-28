using System.Text.Json;
using InvoiceVisionChild.App;
using InvoiceVisionChild.Contracts;
using InvoiceVisionChild.Core;

namespace InvoiceVisionChild.Tests;

internal static class Program
{
    private static int Main()
    {
        var tests = new (string Name, Action Run)[]
        {
            ("GstChecksumValidator valid synthetic GSTIN check digit", TestGstinChecksum),
            ("EInvoiceQrDecoder decodes signed JWT and JSON payload", TestQrDecoder),
            ("InvoiceMathVerifier reconciles rows, GST slabs, credit note, and grand total", TestMathVerifierAndCreditNote),
            ("InvoiceExtractionOrchestrator converts Python worker payload to Canonical result", TestWorkerPayloadConversion),
            ("InvoiceMathVerifier verifies 0%-GST exempt and case-rate invoices", TestExemptAndCaseRateInvoices),
            ("App ParseArgs handles --extract, --analyze and --source --result CLI options", TestCliParsing),
            ("SupplierMemory & Request contracts round-trip cleanly", TestSupplierMemoryAndAnalysisContracts),
            ("InvoiceMathVerifier requires exact CGST == SGST on intra-state invoices", TestCgstSgstEqualityGate),
            ("InvoiceMathVerifier & Orchestrator enforce 0%-tax, row-vs-header tax, inclusive units, and worker blocking issues", TestStrictAuditAndWorkerBlockingGates)
        };

        var passed = 0;
        foreach (var (name, run) in tests)
        {
            run();
            passed++;
            Console.WriteLine($"[PASS] {name}");
        }
        Console.WriteLine($"ALL {passed}/{tests.Length} TESTS PASSED");
        return 0;
    }

    private static void Check(bool cond, string msg)
    {
        if (!cond) throw new InvalidOperationException("ASSERTION FAILED: " + msg);
    }

    private static void TestGstinChecksum()
    {
        const string prefix = "29ABCDE1234F1Z";
        var check = GstChecksumValidator.ComputeCheckDigit(prefix);
        var synthetic = prefix + check;
        Check(GstChecksumValidator.IsValidGstin(synthetic), "Computed synthetic GSTIN must validate");
        Check(GstChecksumValidator.TryGetStateName(synthetic) == "Karnataka", "State 29 must map to Karnataka");

        var corrupted = synthetic[..14] + (check == 'A' ? 'B' : 'A');
        Check(!GstChecksumValidator.IsValidGstin(corrupted), "Corrupted check digit must fail validation");
    }

    private static void TestQrDecoder()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "27FGHIJ5678K1Z" + GstChecksumValidator.ComputeCheckDigit("27FGHIJ5678K1Z");
        var innerJson = JsonSerializer.Serialize(new
        {
            SellerGstin = seller,
            BuyerGstin = buyer,
            DocNo = "INV-2026-001",
            DocDt = "15/09/2026",
            DocTyp = "INV",
            TotInvVal = 1180.00m,
            ItemCnt = 1,
            Irn = "abc123irn"
        });
        var payloadObj = JsonSerializer.Serialize(new { data = innerJson });
        var b64Header = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes("{\"alg\":\"RS256\"}")).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        var b64Payload = Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(payloadObj)).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        var jwt = $"{b64Header}.{b64Payload}.sig";

        var qr = EInvoiceQrDecoder.TryDecode(["upi://pay?pa=test@upi", jwt]);
        Check(qr is { Detected: true }, "JWT QR must decode while ignoring upi://");
        Check(qr!.SellerGstin == seller && qr.BuyerGstin == buyer, "QR seller/buyer GSTIN mismatch");
        Check(qr.DocNo == "INV-2026-001" && qr.TotalValue == 1180.00m, "QR docNo/total mismatch");
    }

    private static void TestMathVerifierAndCreditNote()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        var res = new InvoiceExtractionResult
        {
            InvoiceNumber = "B-1001",
            InvoiceDate = "2026-09-17",
            Seller = new InvoicePartyInfo { Name = "Sample Supplier", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "Sample Buyer", Gstin = buyer },
            TaxableTotal = 1000m,
            CgstTotal = 90m,
            SgstTotal = 90m,
            CreditNoteTotal = 50m,
            RoundOff = 0m,
            InvoiceTotal = 1130m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "Test SKU",
                    HsnSac = "19053100",
                    Quantity = 10,
                    Rate = 100,
                    Taxable = 1000,
                    GstRate = 18,
                    Cgst = 90,
                    Sgst = 90,
                    LineTotal = 1180
                }
            ]
        };

        InvoiceMathVerifier.Verify(res);
        Check(res.Verification.IsBalanced, "Invoice with CreditNoteTotal must verify as balanced: " +
            string.Join("; ", res.Verification.Errors.Concat(res.Verification.Warnings)));
        Check(res.Status == "Verified", "Status should be Verified");
        Check(res.GstSlabs.Count == 1 && res.GstSlabs[0].GstRate == 18m, "Slab aggregation mismatch");
    }

    private static void TestWorkerPayloadConversion()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        var workerJson = JsonSerializer.Serialize(new
        {
            schema = "AAH-INVOICEVISION-WORKER-V1",
            engineUsed = "LightOnOCR-2-1B-P2",
            elapsedSec = 12.5,
            rawOcrText = "SAMPLE RAW TEXT",
            rawTablesHtml = new[] { "<table></table>" },
            renderedPageImages = Array.Empty<string>(),
            preprocessedImages = Array.Empty<string>(),
            canonical = new
            {
                seller = new { name = "Demo Seller", gstin = seller },
                buyer = new { name = "Demo Buyer", gstin = buyer },
                invoiceNumber = "INV-42",
                invoiceDate = "2026-10-01",
                documentType = "Tax Invoice",
                placeOfSupply = "Karnataka",
                reverseCharge = false,
                taxableTotal = 500.0,
                discountTotal = 0.0,
                cgstTotal = 45.0,
                sgstTotal = 45.0,
                igstTotal = 0.0,
                cessTotal = 0.0,
                creditNoteTotal = 0.0,
                roundOff = 0.0,
                invoiceTotal = 590.0,
                rows = new[]
                {
                    new
                    {
                        description = "Product One",
                        hsnSac = "3004",
                        quantity = 5.0,
                        unit = "PCS",
                        rate = 100.0,
                        discount = 0.0,
                        taxable = 500.0,
                        gstRate = 18.0,
                        cgst = 45.0,
                        sgst = 45.0,
                        igst = 0.0,
                        cess = 0.0,
                        lineTotal = 590.0
                    }
                },
                gstSlabs = new[]
                {
                    new { gstRate = 18.0, taxable = 500.0, cgst = 45.0, sgst = 45.0, igst = 0.0, cess = 0.0, combinedTax = 90.0 }
                }
            }
        });

        var req = new InvoiceExtractionRequest
        {
            RequestId = "req-1",
            ClientId = 9,
            ClientName = "Demo Buyer",
            ClientGstin = buyer,
            FinancialYear = "2026-27",
            DirectionHint = "Auto"
        };

        var res = InvoiceExtractionOrchestrator.ConvertWorkerPayloadToResult(
            workerJson,
            req,
            [
                new SourceFileDigest { Path = "page-001.jpg", Sha256 = "AAA", FileBytes = 10 },
                new SourceFileDigest { Path = "page-002.jpg", Sha256 = "BBB", FileBytes = 12 }
            ]);
        InvoiceMathVerifier.Verify(res);
        Check(res.Direction == "Purchase", $"Expected Direction=Purchase when ClientGstin==Buyer, got {res.Direction}");
        Check(res.Verification.IsBalanced && res.Rows.Count == 1, "Converted worker result should balance with 1 row");
        Check(res.SourceFiles.Count == 2 && res.SourceFiles[1].Sha256 == "BBB", "Expected multi-page SourceFiles preserved");
    }

    private static void TestExemptAndCaseRateInvoices()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        var exempt = new InvoiceExtractionResult
        {
            InvoiceNumber = "2948/26-27",
            InvoiceDate = "2026-11-02",
            Seller = new InvoicePartyInfo { Name = "Adarsh Papad Private Limited", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "Balaji Trading Co.", Gstin = buyer },
            TaxableTotal = 4200m,
            InvoiceTotal = 4200m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "Adarsh No 5 Plain Appalam",
                    HsnSac = "19059040",
                    Quantity = 150m,
                    Unit = "Packet",
                    Rate = 28.00m,
                    Taxable = 4200m,
                    GstRate = 0m,
                    LineTotal = 4200m
                }
            ]
        };
        InvoiceMathVerifier.Verify(exempt);
        Check(exempt.Verification.IsBalanced && exempt.Status == "Verified" && exempt.Verification.Score == 100,
            "0%-GST exempt bill should verify cleanly: " + string.Join("; ", exempt.Verification.Errors.Concat(exempt.Verification.Warnings)));

        var caseRate = new InvoiceExtractionResult
        {
            InvoiceNumber = "CKBIL260009771",
            InvoiceDate = "2026-11-07",
            Seller = new InvoicePartyInfo { Name = "VEERABHADRESHWARA ENTERPRISES", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "BALAJI TRADING CO", Gstin = buyer },
            TaxableTotal = 665.76m,
            CgstTotal = 16.64m,
            SgstTotal = 16.64m,
            RoundOff = -0.04m,
            InvoiceTotal = 699.00m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "CHIK EGG WH",
                    HsnSac = "33051090",
                    Quantity = 1m,
                    Unit = "CS",
                    Rate = 831.16m,
                    Discount = 165.40m,
                    Taxable = 665.76m,
                    GstRate = 5m,
                    Cgst = 16.64m,
                    Sgst = 16.64m,
                    LineTotal = 699.04m
                }
            ]
        };
        InvoiceMathVerifier.Verify(caseRate);
        Check(caseRate.Verification.IsBalanced && caseRate.Status == "Verified" && caseRate.Verification.Score == 100,
            "Case-unit effective rate invoice should verify cleanly: " + string.Join("; ", caseRate.Verification.Errors.Concat(caseRate.Verification.Warnings)));
    }

    private static void TestCliParsing()
    {
        var ext = LaunchOptions.Parse(["--extract", "C:\\temp\\req.json"]);
        Check(ext.ExtractRequestPath == "C:\\temp\\req.json", "Extract request path parse mismatch");

        var self = LaunchOptions.Parse(["--self-test", "--self-test-output", "C:\\temp\\out.txt"]);
        Check(self.SelfTest && self.SelfTestOutputPath == "C:\\temp\\out.txt", "Self-test parse mismatch");

        var review = LaunchOptions.Parse(["--client-id", "12", "--fy", "2026-27", "--scan-id", "SCAN-1", "--result", "C:\\temp\\res.json"]);
        Check(review.ClientId == 12 && review.FinancialYear == "2026-27" && review.ScanId == "SCAN-1" && review.ResultPath == "C:\\temp\\res.json",
            "Review options parse mismatch");

        var analyze = LaunchOptions.Parse(["--analyze", "C:\\temp\\analyze.json"]);
        Check(analyze.AnalyzeRequestPath == "C:\\temp\\analyze.json", "Analyze request path parse mismatch");
    }

    private static void TestSupplierMemoryAndAnalysisContracts()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        var workerJson = JsonSerializer.Serialize(new
        {
            schema = "AAH-INVOICEVISION-WORKER-V1",
            engineUsed = "LightOnOCR-2-1B-P2",
            elapsedSec = 8.4,
            rawOcrText = "TEST",
            rawTablesHtml = Array.Empty<string>(),
            renderedPageImages = Array.Empty<string>(),
            preprocessedImages = Array.Empty<string>(),
            supplierMemory = new
            {
                profileFound = true,
                gstin = seller,
                canonicalName = "LEARNED SUPPLIER PVT LTD",
                confirmedCount = 3,
                preferredDirection = "Purchase",
                preferredRecognitionMode = "Accounting Invoice",
                appliedRules = new[] { "Applied learned seller name 'LEARNED SUPPLIER PVT LTD'" }
            },
            canonical = new
            {
                seller = new { name = "LEARNED SUPPLIER PVT LTD", gstin = seller },
                buyer = new { name = "Demo Buyer", gstin = buyer },
                invoiceNumber = "INV-MEM-1",
                invoiceDate = "2026-11-26",
                documentType = "Tax Invoice",
                placeOfSupply = "Karnataka",
                reverseCharge = false,
                taxableTotal = 100.0,
                discountTotal = 0.0,
                cgstTotal = 9.0,
                sgstTotal = 9.0,
                igstTotal = 0.0,
                cessTotal = 0.0,
                creditNoteTotal = 0.0,
                roundOff = 0.0,
                invoiceTotal = 118.0,
                rows = new[]
                {
                    new
                    {
                        description = "Service",
                        hsnSac = "9983",
                        quantity = 1.0,
                        unit = "NOS",
                        rate = 100.0,
                        discount = 0.0,
                        taxable = 100.0,
                        gstRate = 18.0,
                        cgst = 9.0,
                        sgst = 9.0,
                        igst = 0.0,
                        cess = 0.0,
                        lineTotal = 118.0
                    }
                },
                gstSlabs = new[]
                {
                    new { gstRate = 18.0, taxable = 100.0, cgst = 9.0, sgst = 9.0, igst = 0.0, cess = 0.0, combinedTax = 18.0 }
                }
            }
        });

        var req = new InvoiceExtractionRequest
        {
            ClientId = 18,
            ClientGstin = buyer,
            FinancialYear = "2026-27",
            MemoryDbPath = "C:\\temp\\supplier_memory.db"
        };
        var roundTripReq = JsonSerializer.Deserialize<InvoiceExtractionRequest>(JsonSerializer.Serialize(req))!;
        Check(roundTripReq.MemoryDbPath == "C:\\temp\\supplier_memory.db", "MemoryDbPath round-trip mismatch");

        var res = InvoiceExtractionOrchestrator.ConvertWorkerPayloadToResult(workerJson, req, []);
        Check(res.SupplierMemory is { ProfileFound: true, ConfirmedCount: 3 } &&
              res.SupplierMemory.CanonicalName == "LEARNED SUPPLIER PVT LTD" &&
              res.SupplierMemory.AppliedRules.Count == 1,
            "SupplierMemory summary conversion mismatch");
    }

    private static void TestCgstSgstEqualityGate()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        var unequal = new InvoiceExtractionResult
        {
            InvoiceNumber = "A001532",
            InvoiceDate = "2026-10-29",
            Seller = new InvoicePartyInfo { Name = "SRI RAMA ENTERPRISES", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "BALAJI TRADING CO", Gstin = buyer },
            TaxableTotal = 2619.05m,
            CgstTotal = 65.48m,
            SgstTotal = 65.47m,
            InvoiceTotal = 2750.00m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "CHILLY PW", HsnSac = "090422", Quantity = 10m, Rate = 261.90m,
                    Taxable = 2619.05m, GstRate = 5m, Cgst = 65.48m, Sgst = 65.47m, LineTotal = 2750.00m
                }
            ]
        };
        InvoiceMathVerifier.Verify(unequal);
        Check(!unequal.Verification.IsBalanced && unequal.Status == "ReviewRequired",
            "Expected unequal CGST (65.48) vs SGST (65.47) to fail strict equality gate.");

        unequal.CgstTotal = 65.48m;
        unequal.SgstTotal = 65.48m;
        unequal.RoundOff = -0.01m;
        unequal.Rows[0].Cgst = 65.48m;
        unequal.Rows[0].Sgst = 65.48m;
        unequal.Rows[0].LineTotal = 2750.01m;
        InvoiceMathVerifier.Verify(unequal);
        Check(unequal.Verification.IsBalanced && unequal.Status == "Verified",
            "Expected equal CGST (65.48) == SGST (65.48) to verify cleanly.");
    }

    private static void TestStrictAuditAndWorkerBlockingGates()
    {
        var seller = "29ABCDE1234F1Z" + GstChecksumValidator.ComputeCheckDigit("29ABCDE1234F1Z");
        var buyer = "29KLMNO9876P1Z" + GstChecksumValidator.ComputeCheckDigit("29KLMNO9876P1Z");

        // 1. Inclusive Qty*Rate-Disc == LineTotal (e.g. Metro 0% + 5%) must balance cleanly
        var metroLike = new InvoiceExtractionResult
        {
            InvoiceNumber = "29M3100003173160",
            InvoiceDate = "2026-11-03",
            Seller = new InvoicePartyInfo { Name = "Metro Cash and Carry India Limited", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "BALAJI TRADING CO.", Gstin = buyer },
            TaxableTotal = 13393.80m,
            CgstTotal = 236.52m,
            SgstTotal = 236.52m,
            InvoiceTotal = 13866.84m,
            Rows =
            [
                new InvoiceLineItem { Description = "Atta 1kg", HsnSac = "11010000", Quantity = 30m, Rate = 75m, Discount = 341.70m, Taxable = 1817.42m, GstRate = 5m, Cgst = 45.44m, Sgst = 45.44m, LineTotal = 1908.30m },
                new InvoiceLineItem { Description = "Atta 10kg", HsnSac = "11010000", Quantity = 15m, Rate = 666m, Discount = 1964.55m, Taxable = 7643.29m, GstRate = 5m, Cgst = 191.08m, Sgst = 191.08m, LineTotal = 8025.45m },
                new InvoiceLineItem { Description = "Maida 30kg", HsnSac = "11010000", Quantity = 3m, Rate = 1620m, Discount = 926.91m, Taxable = 3933.09m, GstRate = 0m, Cgst = 0m, Sgst = 0m, LineTotal = 3933.09m }
            ]
        };
        InvoiceMathVerifier.Verify(metroLike);
        Check(metroLike.Verification.IsBalanced && !metroLike.Rows.Any(r => r.MathStatus == "Mismatch"),
            "Tax-inclusive Metro-like rows must balance cleanly: " + string.Join("; ", metroLike.Verification.Errors.Concat(metroLike.Verification.Warnings)));

        // 2. Non-zero tax on 0% GST rate must fail
        var zeroRateWithTax = new InvoiceExtractionResult
        {
            InvoiceNumber = "BAD-01",
            InvoiceDate = "2026-11-03",
            Seller = new InvoicePartyInfo { Name = "Bad Supplier", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "Buyer", Gstin = buyer },
            TaxableTotal = 100m,
            CgstTotal = 2.50m,
            SgstTotal = 2.50m,
            InvoiceTotal = 105.00m,
            Rows = [new InvoiceLineItem { Description = "Item", Quantity = 1m, Rate = 100m, Taxable = 100m, GstRate = 0m, Cgst = 2.50m, Sgst = 2.50m, LineTotal = 105m }]
        };
        InvoiceMathVerifier.Verify(zeroRateWithTax);
        Check(!zeroRateWithTax.Verification.IsBalanced && zeroRateWithTax.Status == "ReviewRequired",
            "0% GST rate carrying non-zero tax must fail strict verification.");

        // 3. Row tax sum mismatching header tax total must fail
        var rowHeaderMismatch = new InvoiceExtractionResult
        {
            InvoiceNumber = "BAD-02",
            InvoiceDate = "2026-11-03",
            Seller = new InvoicePartyInfo { Name = "Bad Supplier", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "Buyer", Gstin = buyer },
            TaxableTotal = 100m,
            CgstTotal = 9.00m,
            SgstTotal = 9.00m,
            InvoiceTotal = 118.00m,
            Rows = [new InvoiceLineItem { Description = "Item", Quantity = 1m, Rate = 100m, Taxable = 100m, GstRate = 5m, Cgst = 2.50m, Sgst = 2.50m, LineTotal = 105m }]
        };
        InvoiceMathVerifier.Verify(rowHeaderMismatch);
        Check(!rowHeaderMismatch.Verification.IsBalanced && rowHeaderMismatch.Status == "ReviewRequired",
            "Row CGST/SGST sum mismatch against header totals must fail strict verification.");

        // 4. Worker audit.blocking_issues must block even if numeric fields look internally consistent
        var blockingPayload = JsonSerializer.Serialize(new
        {
            schema = "AAH-INVOICEVISION-WORKER-V1",
            engineUsed = "LightOnOCR-2-1B-P2",
            elapsedSec = 10.0,
            canonical = new
            {
                seller = new { name = "Truncated Seller", gstin = seller },
                buyer = new { name = "Buyer", gstin = buyer },
                invoiceNumber = "TR-01",
                invoiceDate = "2026-11-03",
                documentType = "Tax Invoice",
                taxableTotal = 100.0,
                cgstTotal = 9.0,
                sgstTotal = 9.0,
                invoiceTotal = 118.0,
                rows = new[] { new { description = "Item", hsnSac = "19053100", quantity = 1.0, unit = "PCS", rate = 100.0, discount = 0.0, taxable = 100.0, gstRate = 18.0, cgst = 9.0, sgst = 9.0, igst = 0.0, cess = 0.0, lineTotal = 118.0 } }
            },
            audit = new
            {
                fully_balanced = false,
                blocking_issues = new[] { "OCR output was truncated mid-table before end of invoice." }
            }
        });
        var conv = InvoiceExtractionOrchestrator.ConvertWorkerPayloadToResult(
            blockingPayload,
            new InvoiceExtractionRequest { ClientId = 18, ClientGstin = buyer, FinancialYear = "2026-27" },
            []);
        Check(!conv.Verification.IsBalanced && conv.Status == "ReviewRequired",
            "Worker audit.blocking_issues must force Status=ReviewRequired and IsBalanced=false.");
        InvoiceMathVerifier.Verify(conv);
        Check(!conv.Verification.IsBalanced && conv.Status == "ReviewRequired",
            "InvoiceMathVerifier.Verify must preserve WorkerBlockingIssues.");

        // 5. Row where unit rate OCR differs (e.g. Nandi 5.28 vs 8.28) but Taxable+Tax==LineTotal and 5% GST math passes must balance
        var nandiRateSlip = new InvoiceExtractionResult
        {
            InvoiceNumber = "E75422",
            InvoiceDate = "2026-10-30",
            Seller = new InvoicePartyInfo { Name = "NANDI MARKETING", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "BALAJI TRADING CO.", Gstin = buyer },
            TaxableTotal = 491.95m,
            CgstTotal = 12.30m,
            SgstTotal = 12.30m,
            InvoiceTotal = 516.55m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "RED LAB LEAF E BLEND",
                    HsnSac = "09023010",
                    Quantity = 60m,
                    Rate = 5.28m,
                    Discount = 4.97m,
                    Taxable = 491.95m,
                    GstRate = 5m,
                    Cgst = 12.30m,
                    Sgst = 12.30m,
                    LineTotal = 516.55m
                }
            ]
        };
        InvoiceMathVerifier.Verify(nandiRateSlip);
        Check(nandiRateSlip.Verification.IsBalanced && nandiRateSlip.Status == "Verified",
            "Line-sum and GST-rate balanced row must not fail on unit-rate slip alone: " +
            string.Join("; ", nandiRateSlip.Verification.Errors.Concat(nandiRateSlip.Verification.Warnings)));

        // 6. Zero-value promotional/free row (Qty=0 or Rate=0, Taxable=0, LineTotal=0) must verify cleanly without 'Missing taxable amount'
        var freePromoBill = new InvoiceExtractionResult
        {
            InvoiceNumber = "I/26-27/047899",
            InvoiceDate = "2026-10-31",
            Seller = new InvoicePartyInfo { Name = "SRI GANGADHARESHWARA ENTERPRISE", Gstin = seller },
            Buyer = new InvoicePartyInfo { Name = "BALAJI TRADING CO", Gstin = buyer },
            TaxableTotal = 1516.46m,
            CgstTotal = 37.91m,
            SgstTotal = 37.91m,
            InvoiceTotal = 1592.28m,
            Rows =
            [
                new InvoiceLineItem
                {
                    Description = "AASHIRVAAD ATTA 2KG",
                    HsnSac = "11010000",
                    Quantity = 1m,
                    Rate = 1516.46m,
                    Taxable = 1516.46m,
                    GstRate = 5m,
                    Cgst = 37.91m,
                    Sgst = 37.91m,
                    LineTotal = 1592.28m
                },
                new InvoiceLineItem
                {
                    Description = "AASHIVD SALT 1KG (FREE SCHEME)",
                    HsnSac = "25010010",
                    Quantity = 0m,
                    Rate = 0m,
                    Taxable = 0m,
                    GstRate = 0m,
                    Cgst = 0m,
                    Sgst = 0m,
                    LineTotal = 0m
                }
            ]
        };
        InvoiceMathVerifier.Verify(freePromoBill);
        Check(freePromoBill.Verification.IsBalanced && freePromoBill.Status == "Verified" && freePromoBill.Rows[1].MathStatus == "OK",
            "Zero-value free promotional row must verify cleanly: " +
            string.Join("; ", freePromoBill.Verification.Errors.Concat(freePromoBill.Verification.Warnings)));
    }
}
