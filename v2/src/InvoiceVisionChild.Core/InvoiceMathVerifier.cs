using InvoiceVisionChild.Contracts;

namespace InvoiceVisionChild.Core;

/// <summary>
/// Deterministic GST accounting math, GSTIN checksum, HSN, and QR cross-check validator.
/// </summary>
public static class InvoiceMathVerifier
{
    public static void Verify(InvoiceExtractionResult result)
    {
        ArgumentNullException.ThrowIfNull(result);

        var passed = new List<string>();
        var warnings = new List<string>();
        var errors = new List<string>();
        foreach (var wb in result.WorkerBlockingIssues)
        {
            if (!string.IsNullOrWhiteSpace(wb) && !errors.Contains(wb, StringComparer.OrdinalIgnoreCase))
                errors.Add(wb);
        }

        UpdatePartyStateAndValidity(result.Seller, "Seller", passed, warnings, errors);
        UpdatePartyStateAndValidity(result.Buyer, "Buyer", passed, warnings, errors);

        if (string.IsNullOrWhiteSpace(result.InvoiceNumber))
            errors.Add("Invoice number is missing.");
        else
            passed.Add($"Invoice number present ({result.InvoiceNumber}).");

        if (string.IsNullOrWhiteSpace(result.InvoiceDate))
            warnings.Add("Invoice date is missing or could not be parsed.");

        // Recompute missing line totals / validate each line item
        var rowIndex = 0;
        var rowMismatchCount = 0;
        foreach (var row in result.Rows)
        {
            rowIndex++;
            row.LineNumber = rowIndex;
            row.HsnSac = (row.HsnSac ?? string.Empty).Trim();
            if (row.HsnSac.Length > 0 && !GstChecksumValidator.IsValidHsnSac(row.HsnSac))
                warnings.Add($"Row {rowIndex}: HSN/SAC '{row.HsnSac}' is not 4, 6, or 8 digits.");

            var rowIssues = new List<string>();
            if (row.Quantity > 0m && row.Rate > 0m)
            {
                var expectedTaxable = Math.Round((row.Quantity * row.Rate) - row.Discount, 2, MidpointRounding.AwayFromZero);
                if (row.Taxable <= 0m)
                {
                    row.Taxable = expectedTaxable;
                }
                else
                {
                    var diff = Math.Abs(expectedTaxable - row.Taxable);
                    var tol = Math.Max(1.00m, row.Taxable * 0.005m);
                    var isInclusiveUnit = row.LineTotal > 0m && row.GstRate > 0m &&
                        Math.Abs(expectedTaxable - row.LineTotal) <= Math.Max(1.50m, row.LineTotal * 0.01m);
                    if (diff > tol && !isInclusiveUnit)
                        rowIssues.Add($"Qty*Rate-Disc ({expectedTaxable:N2}) != Taxable ({row.Taxable:N2})");
                }
            }

            var taxSum = row.Cgst + row.Sgst + row.Igst;
            if (row.Igst == 0m && (row.Cgst > 0m || row.Sgst > 0m) && Math.Abs(row.Cgst - row.Sgst) > 0.005m)
                rowIssues.Add($"CGST ({row.Cgst:N2}) != SGST ({row.Sgst:N2})");

            if (row.GstRate <= 0m && taxSum > 0.05m)
                rowIssues.Add($"Tax {taxSum:N2} present on 0% GST rate");

            if (row.GstRate > 0m && row.Taxable > 0m)
            {
                var expectedTax = Math.Round(row.Taxable * row.GstRate / 100m, 2, MidpointRounding.AwayFromZero);
                if (taxSum > 0m)
                {
                    var taxDiff = Math.Abs(expectedTax - taxSum);
                    var taxTol = Math.Max(1.00m, row.Taxable * 0.005m);
                    if (taxDiff > taxTol)
                        rowIssues.Add($"Tax {taxSum:N2} != {row.GstRate:0.##}% of {row.Taxable:N2} ({expectedTax:N2})");
                }
            }

            if (row.LineTotal <= 0m && row.Taxable > 0m)
                row.LineTotal = row.Taxable + taxSum + row.Cess;

            if (rowIssues.Count > 0)
            {
                row.MathStatus = "Mismatch";
                row.MathNote = string.Join("; ", rowIssues);
                rowMismatchCount++;
                warnings.Add($"Row {rowIndex}: {row.MathNote}");
            }
            else if (row.Taxable > 0m || row.LineTotal > 0m)
            {
                row.MathStatus = "OK";
                row.MathNote = "Balanced";
            }
            else
            {
                row.MathStatus = "Incomplete";
                row.MathNote = "Missing taxable amount";
                warnings.Add($"Row {rowIndex}: Missing taxable amount.");
            }
        }

        if (result.Rows.Count > 0 && rowMismatchCount == 0)
            passed.Add($"All {result.Rows.Count} item row(s) passed line-level arithmetic.");
        else if (result.Rows.Count == 0 && result.InvoiceTotal > 0m)
            warnings.Add("No line items were extracted.");

        // Derive summary totals from rows if missing
        if (result.Rows.Count > 0)
        {
            var sumTaxable = result.Rows.Sum(r => r.Taxable);
            var sumCgst = result.Rows.Sum(r => r.Cgst);
            var sumSgst = result.Rows.Sum(r => r.Sgst);
            var sumIgst = result.Rows.Sum(r => r.Igst);
            var sumCess = result.Rows.Sum(r => r.Cess);

            if (result.TaxableTotal <= 0m && sumTaxable > 0m) result.TaxableTotal = sumTaxable;
            if (result.CgstTotal <= 0m && sumCgst > 0m) result.CgstTotal = sumCgst;
            if (result.SgstTotal <= 0m && sumSgst > 0m) result.SgstTotal = sumSgst;
            if (result.IgstTotal <= 0m && sumIgst > 0m) result.IgstTotal = sumIgst;
            if (result.CessTotal <= 0m && sumCess > 0m) result.CessTotal = sumCess;

            if (result.TaxableTotal > 0m && sumTaxable > 0m && Math.Abs(result.TaxableTotal - sumTaxable) > 1.00m)
                warnings.Add($"Row taxable sum ({sumTaxable:N2}) differs from invoice taxable total ({result.TaxableTotal:N2}).");

            var rowTaxSum = sumCgst + sumSgst + sumIgst;
            var hdrTaxSum = result.CgstTotal + result.SgstTotal + result.IgstTotal;
            if (rowTaxSum > 0m && hdrTaxSum > 0m &&
                (Math.Abs(sumCgst - result.CgstTotal) > 1.00m ||
                 Math.Abs(sumSgst - result.SgstTotal) > 1.00m ||
                 Math.Abs(sumIgst - result.IgstTotal) > 1.00m))
            {
                errors.Add($"Row tax sum (CGST {sumCgst:N2}, SGST {sumSgst:N2}, IGST {sumIgst:N2}) mismatches header totals (CGST {result.CgstTotal:N2}, SGST {result.SgstTotal:N2}, IGST {result.IgstTotal:N2}).");
            }
            if (result.Rows.Any(r => r.GstRate <= 0m && (r.Cgst + r.Sgst + r.Igst) > 0.05m))
            {
                errors.Add("One or more rows carry non-zero GST tax on a 0% GST rate.");
            }

            RebuildGstSlabs(result);
        }

        if (result.IgstTotal == 0m && (result.CgstTotal > 0m || result.SgstTotal > 0m) && Math.Abs(result.CgstTotal - result.SgstTotal) > 0.005m)
            errors.Add($"CGST total ({result.CgstTotal:N2}) does not equal SGST total ({result.SgstTotal:N2}).");

        var computedGrandTotal = result.TaxableTotal + result.CgstTotal + result.SgstTotal + result.IgstTotal + result.CessTotal - result.CreditNoteTotal + result.RoundOff;
        if (result.InvoiceTotal <= 0m)
        {
            errors.Add("Invoice grand total is missing or zero.");
        }
        else if (result.TaxableTotal <= 0m)
        {
            errors.Add("Taxable total is missing or zero while invoice total is positive.");
        }
        else
        {
            var grandDiff = Math.Abs(computedGrandTotal - result.InvoiceTotal);
            if (grandDiff > 1.00m)
                errors.Add($"Taxable + Taxes - CreditNote + RoundOff ({computedGrandTotal:N2}) does not equal Invoice Total ({result.InvoiceTotal:N2}, diff {grandDiff:N2}).");
            else
                passed.Add($"Invoice header total balanced ({result.InvoiceTotal:N2}).");
        }

        // Cross-check NIC e-Invoice QR truth if present
        if (result.QrEvidence is { Detected: true } qr)
        {
            passed.Add("NIC e-Invoice QR payload decoded.");
            if (qr.TotalValue > 0m && result.InvoiceTotal > 0m && Math.Abs(qr.TotalValue - result.InvoiceTotal) > 1.00m)
                errors.Add($"QR total ({qr.TotalValue:N2}) mismatches extracted invoice total ({result.InvoiceTotal:N2}).");
            if (!string.IsNullOrWhiteSpace(qr.SellerGstin) &&
                !string.IsNullOrWhiteSpace(result.Seller.Gstin) &&
                !qr.SellerGstin.Equals(result.Seller.Gstin, StringComparison.OrdinalIgnoreCase))
                errors.Add($"QR Seller GSTIN ({qr.SellerGstin}) mismatches extracted ({result.Seller.Gstin}).");
            if (!string.IsNullOrWhiteSpace(qr.BuyerGstin) &&
                !string.IsNullOrWhiteSpace(result.Buyer.Gstin) &&
                !qr.BuyerGstin.Equals(result.Buyer.Gstin, StringComparison.OrdinalIgnoreCase))
                errors.Add($"QR Buyer GSTIN ({qr.BuyerGstin}) mismatches extracted ({result.Buyer.Gstin}).");
            if (!string.IsNullOrWhiteSpace(qr.DocNo) &&
                !string.IsNullOrWhiteSpace(result.InvoiceNumber) &&
                !qr.DocNo.Equals(result.InvoiceNumber, StringComparison.OrdinalIgnoreCase))
                warnings.Add($"QR invoice number ({qr.DocNo}) differs from extracted ({result.InvoiceNumber}).");
            if (qr.ItemCount > 0 && result.Rows.Count > 0 && qr.ItemCount != result.Rows.Count)
                warnings.Add($"QR reports {qr.ItemCount} item(s), extracted {result.Rows.Count} row(s).");
        }

        var totalChecks = passed.Count + warnings.Count + errors.Count;
        var score = totalChecks == 0
            ? 0
            : Math.Clamp((int)Math.Round(100.0 * passed.Count / (passed.Count + warnings.Count + errors.Count * 2)), 0, 100);

        result.Verification = new InvoiceVerificationReport
        {
            IsBalanced = errors.Count == 0 && warnings.Count == 0 && result.InvoiceTotal > 0m,
            Score = score,
            PassedChecks = passed,
            Warnings = warnings,
            Errors = errors
        };

        if (result.Status != "Failed")
        {
            result.Status = (errors.Count == 0 && warnings.Count == 0 && result.InvoiceTotal > 0m &&
                             !string.IsNullOrWhiteSpace(result.InvoiceNumber))
                ? "Verified"
                : "ReviewRequired";
        }
    }

    private static void UpdatePartyStateAndValidity(
        InvoicePartyInfo party,
        string role,
        List<string> passed,
        List<string> warnings,
        List<string> errors)
    {
        party.Gstin = GstChecksumValidator.NormalizeGstin(party.Gstin);
        if (party.Gstin.Length == 0)
        {
            party.GstinValid = false;
            warnings.Add($"{role} GSTIN not detected.");
            return;
        }

        party.GstinValid = GstChecksumValidator.IsValidGstin(party.Gstin);
        party.StateCode = GstChecksumValidator.TryGetStateCode(party.Gstin);
        if (string.IsNullOrWhiteSpace(party.StateName) && party.StateCode.Length > 0)
            party.StateName = GstChecksumValidator.TryGetStateName(party.StateCode);

        if (party.GstinValid)
            passed.Add($"{role} GSTIN checksum valid ({party.Gstin}).");
        else
            errors.Add($"{role} GSTIN '{party.Gstin}' failed mod-36 checksum verification.");
    }

    private static void RebuildGstSlabs(InvoiceExtractionResult result)
    {
        var grouped = result.Rows
            .Where(r => r.Taxable > 0m || r.Cgst > 0m || r.Sgst > 0m || r.Igst > 0m)
            .GroupBy(r => r.GstRate)
            .OrderBy(g => g.Key)
            .Select(g => new InvoiceGstSlab
            {
                GstRate = g.Key,
                Taxable = g.Sum(x => x.Taxable),
                Cgst = g.Sum(x => x.Cgst),
                Sgst = g.Sum(x => x.Sgst),
                Igst = g.Sum(x => x.Igst),
                Cess = g.Sum(x => x.Cess),
                CombinedTax = g.Sum(x => x.Cgst + x.Sgst + x.Igst + x.Cess)
            })
            .ToList();

        if (grouped.Count > 0)
            result.GstSlabs = grouped;
    }
}
