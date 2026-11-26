using System.Globalization;
using System.Net;
using System.Text.RegularExpressions;
using InvoiceVisionChild.Contracts;

namespace InvoiceVisionChild.Core;

/// <summary>
/// Converts raw OCR text, HTML tables (from PaddleOCR-VL / PdfPig), and optional NIC QR truth
/// into a canonical InvoiceExtractionResult, then runs InvoiceMathVerifier.
/// </summary>
public static partial class InvoiceStructuredParser
{
    public static InvoiceExtractionResult Parse(
        InvoiceExtractionRequest request,
        string engineUsed,
        string rawText,
        IReadOnlyList<string> htmlTables,
        IReadOnlyList<string>? qrPayloads = null,
        IReadOnlyList<string>? renderedPageImages = null,
        IReadOnlyList<SourceFileDigest>? sourceDigests = null,
        string diagnosticsNote = "")
    {
        ArgumentNullException.ThrowIfNull(request);

        var qr = EInvoiceQrDecoder.TryDecode(qrPayloads);
        var result = new InvoiceExtractionResult
        {
            RequestId = request.RequestId,
            ClientId = request.ClientId,
            ClientCode = request.ClientCode,
            FinancialYear = request.FinancialYear,
            EngineUsed = engineUsed,
            ExtractedUtc = DateTime.UtcNow,
            RawOcrText = rawText ?? string.Empty,
            RawTablesHtml = htmlTables?.Where(t => !string.IsNullOrWhiteSpace(t)).ToList() ?? [],
            RenderedPageImages = renderedPageImages?.Where(p => !string.IsNullOrWhiteSpace(p)).ToList() ?? [],
            SourceFiles = sourceDigests?.ToList() ?? [],
            QrEvidence = qr,
            DiagnosticsNote = diagnosticsNote
        };

        var lines = NormalizeLines(rawText);
        ResolvePartiesAndDirection(request, lines, rawText ?? string.Empty, qr, result);

        result.InvoiceNumber = ExtractInvoiceNumber(lines, qr);
        result.InvoiceDate = ExtractInvoiceDate(lines, qr);
        result.PlaceOfSupply = ExtractLabeledValue(lines, ["place of supply", "pos"]);
        result.ReverseCharge = DetectReverseCharge(lines);
        result.DocumentType = DetectDocumentType(lines, qr);

        ParseTablesAndTotals(result.RawTablesHtml, lines, result);

        if (qr is { Detected: true } && qr.TotalValue > 0m && result.InvoiceTotal <= 0m)
            result.InvoiceTotal = qr.TotalValue;

        InvoiceMathVerifier.Verify(result);
        return result;
    }

    private static string[] NormalizeLines(string? text) =>
        string.IsNullOrWhiteSpace(text)
            ? []
            : text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    private static void ResolvePartiesAndDirection(
        InvoiceExtractionRequest request,
        string[] lines,
        string rawText,
        EInvoiceQrInfo? qr,
        InvoiceExtractionResult result)
    {
        var gstins = GstChecksumValidator.ExtractValidGstins(rawText);
        var sellerGstin = qr?.SellerGstin is { Length: 15 } qs ? qs : (gstins.Count > 0 ? gstins[0] : string.Empty);
        var buyerGstin = qr?.BuyerGstin is { Length: 15 } qb
            ? qb
            : gstins.FirstOrDefault(g => !g.Equals(sellerGstin, StringComparison.OrdinalIgnoreCase)) ?? string.Empty;

        var clientGstin = GstChecksumValidator.NormalizeGstin(request.ClientGstin);
        var direction = request.DirectionHint.Trim();

        if (clientGstin.Length == 15)
        {
            if (clientGstin.Equals(buyerGstin, StringComparison.OrdinalIgnoreCase))
            {
                direction = "Purchase";
            }
            else if (clientGstin.Equals(sellerGstin, StringComparison.OrdinalIgnoreCase))
            {
                direction = "Sales";
            }
            else if (direction.Equals("Auto", StringComparison.OrdinalIgnoreCase) && gstins.Count >= 2 &&
                     gstins[0].Equals(clientGstin, StringComparison.OrdinalIgnoreCase))
            {
                direction = "Sales";
            }
        }

        if (string.IsNullOrWhiteSpace(direction) || direction.Equals("Auto", StringComparison.OrdinalIgnoreCase))
            direction = "Purchase";

        result.Direction = direction;
        result.Seller.Gstin = sellerGstin;
        result.Buyer.Gstin = buyerGstin;

        result.Seller.Name = ExtractPartyNameNear(lines, sellerGstin, ["supplier", "seller", "from", "m/s"], fallbackTopLine: true);
        result.Buyer.Name = ExtractPartyNameNear(lines, buyerGstin, ["buyer", "bill to", "billed to", "recipient", "customer", "to:"], fallbackTopLine: false);

        if (clientGstin.Length == 15 && !string.IsNullOrWhiteSpace(request.ClientName))
        {
            if (clientGstin.Equals(result.Buyer.Gstin, StringComparison.OrdinalIgnoreCase) && string.IsNullOrWhiteSpace(result.Buyer.Name))
                result.Buyer.Name = request.ClientName.Trim();
            else if (clientGstin.Equals(result.Seller.Gstin, StringComparison.OrdinalIgnoreCase) && string.IsNullOrWhiteSpace(result.Seller.Name))
                result.Seller.Name = request.ClientName.Trim();
        }
    }

    private static string ExtractPartyNameNear(string[] lines, string targetGstin, string[] roleKeywords, bool fallbackTopLine)
    {
        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            if (!line.ContainsAny(roleKeywords, StringComparison.OrdinalIgnoreCase)) continue;

            var colonIdx = line.IndexOf(':');
            if (colonIdx >= 0 && colonIdx + 1 < line.Length)
            {
                var after = line[(colonIdx + 1)..].Trim();
                if (after.Length >= 3 && !after.Contains("GSTIN", StringComparison.OrdinalIgnoreCase))
                    return CleanPartyName(after);
            }
            if (i + 1 < lines.Length && !lines[i + 1].Contains("GSTIN", StringComparison.OrdinalIgnoreCase))
                return CleanPartyName(lines[i + 1]);
        }

        if (targetGstin.Length == 15)
        {
            for (var i = 0; i < lines.Length; i++)
            {
                if (!lines[i].Contains(targetGstin, StringComparison.OrdinalIgnoreCase)) continue;
                for (var back = 1; back <= 3 && i - back >= 0; back++)
                {
                    var cand = CleanPartyName(lines[i - back]);
                    if (cand.Length >= 3 && !cand.StartsWith("GSTIN", StringComparison.OrdinalIgnoreCase) &&
                        !cand.StartsWith("TAX INVOICE", StringComparison.OrdinalIgnoreCase))
                    {
                        return cand;
                    }
                }
            }
        }

        if (fallbackTopLine)
        {
            foreach (var line in lines.Take(6))
            {
                var cand = CleanPartyName(line);
                if (cand.Length >= 3 &&
                    !cand.Contains("TAX INVOICE", StringComparison.OrdinalIgnoreCase) &&
                    !cand.Contains("GSTIN", StringComparison.OrdinalIgnoreCase) &&
                    !cand.Contains("ORIGINAL", StringComparison.OrdinalIgnoreCase))
                {
                    return cand;
                }
            }
        }

        return string.Empty;
    }

    private static string CleanPartyName(string raw)
    {
        var s = StripMarkdownAndHtml(raw).Trim().Trim('-', ':', '|');
        return s;
    }

    private static string ExtractInvoiceNumber(string[] lines, EInvoiceQrInfo? qr)
    {
        if (qr is { Detected: true } && !string.IsNullOrWhiteSpace(qr.DocNo))
            return qr.DocNo.Trim();

        foreach (var line in lines)
        {
            var m = InvoiceNoRegex().Match(line);
            if (m.Success)
            {
                var val = m.Groups[1].Value.Trim().Trim(':', '#', '-', ' ');
                if (val.Length is >= 1 and <= 40 && !val.Equals("Date", StringComparison.OrdinalIgnoreCase))
                    return val;
            }
        }
        return string.Empty;
    }

    private static string ExtractInvoiceDate(string[] lines, EInvoiceQrInfo? qr)
    {
        if (qr is { Detected: true } && !string.IsNullOrWhiteSpace(qr.DocDate))
            return EInvoiceQrDecoder.NormalizeDate(qr.DocDate);

        foreach (var line in lines)
        {
            if (!line.Contains("Date", StringComparison.OrdinalIgnoreCase) &&
                !line.Contains("Dated", StringComparison.OrdinalIgnoreCase))
                continue;
            var m = DateTokenRegex().Match(line);
            if (m.Success)
                return EInvoiceQrDecoder.NormalizeDate(m.Value);
        }

        foreach (var line in lines.Take(35))
        {
            var m = DateTokenRegex().Match(line);
            if (m.Success)
                return EInvoiceQrDecoder.NormalizeDate(m.Value);
        }
        return string.Empty;
    }

    private static string ExtractLabeledValue(string[] lines, string[] labels)
    {
        foreach (var line in lines)
        {
            foreach (var label in labels)
            {
                var idx = line.IndexOf(label, StringComparison.OrdinalIgnoreCase);
                if (idx < 0) continue;
                var rest = line[(idx + label.Length)..].Trim().TrimStart(':', '-').Trim();
                if (rest.Length > 0) return StripMarkdownAndHtml(rest);
            }
        }
        return string.Empty;
    }

    private static bool DetectReverseCharge(string[] lines)
    {
        foreach (var line in lines)
        {
            if (!line.Contains("Reverse Charge", StringComparison.OrdinalIgnoreCase) &&
                !line.Contains("RCM", StringComparison.OrdinalIgnoreCase))
                continue;
            if (line.Contains("Yes", StringComparison.OrdinalIgnoreCase)) return true;
        }
        return false;
    }

    private static string DetectDocumentType(string[] lines, EInvoiceQrInfo? qr)
    {
        var docTyp = (qr?.DocType ?? string.Empty).Trim().ToUpperInvariant();
        if (docTyp == "CRN") return "Credit Note";
        if (docTyp == "DBN") return "Debit Note";
        foreach (var line in lines.Take(12))
        {
            if (line.Contains("CREDIT NOTE", StringComparison.OrdinalIgnoreCase)) return "Credit Note";
            if (line.Contains("DEBIT NOTE", StringComparison.OrdinalIgnoreCase)) return "Debit Note";
            if (line.Contains("BILL OF SUPPLY", StringComparison.OrdinalIgnoreCase)) return "Bill of Supply";
        }
        return "Tax Invoice";
    }

    private static void ParseTablesAndTotals(IReadOnlyList<string> htmlTables, string[] lines, InvoiceExtractionResult result)
    {
        foreach (var html in htmlTables)
        {
            var grid = ParseHtmlTableGrid(html);
            if (grid.Count < 2) continue;

            var headerIdx = FindItemHeaderRow(grid);
            if (headerIdx >= 0)
            {
                var map = BuildColumnMap(grid[headerIdx]);
                for (var r = headerIdx + 1; r < grid.Count; r++)
                {
                    var row = grid[r];
                    var joined = string.Join(" | ", row.Where(c => !string.IsNullOrWhiteSpace(c)));
                    if (string.IsNullOrWhiteSpace(joined)) continue;

                    if (TryConsumeSummaryRow(row, joined, result))
                        continue;

                    var item = MapRowToLineItem(row, map, joined);
                    if (item is not null)
                        result.Rows.Add(item);
                }
            }
            else
            {
                // Could be a standalone tax summary / totals table
                foreach (var row in grid)
                {
                    var joined = string.Join(" | ", row.Where(c => !string.IsNullOrWhiteSpace(c)));
                    TryConsumeSummaryRow(row, joined, result);
                }
            }
        }

        // Fill missing invoice summary totals from raw text lines if needed
        ExtractSummaryTotalsFromText(lines, result);
    }

    private static List<List<string>> ParseHtmlTableGrid(string html)
    {
        var grid = new List<List<string?>>();
        var spans = new Dictionary<(int Row, int Col), string>();
        var rowMatches = TrRegex().Matches(html);
        var rowIndex = 0;

        foreach (Match tr in rowMatches)
        {
            while (grid.Count <= rowIndex) grid.Add([]);
            var colIndex = 0;

            foreach (Match cell in TdThRegex().Matches(tr.Value))
            {
                while (spans.TryGetValue((rowIndex, colIndex), out var spanned))
                {
                    EnsureWidth(grid[rowIndex], colIndex + 1);
                    grid[rowIndex][colIndex] = spanned;
                    colIndex++;
                }

                var attrs = cell.Groups[1].Value;
                var inner = cell.Groups[2].Value;
                var text = CleanWhitespace(WebUtility.HtmlDecode(HtmlTagRegex().Replace(inner, " ")));
                var rowSpan = ParseSpanAttr(attrs, "rowspan");
                var colSpan = ParseSpanAttr(attrs, "colspan");

                for (var rr = rowIndex; rr < rowIndex + rowSpan; rr++)
                {
                    while (grid.Count <= rr) grid.Add([]);
                    for (var cc = colIndex; cc < colIndex + colSpan; cc++)
                    {
                        spans[(rr, cc)] = text;
                        EnsureWidth(grid[rr], cc + 1);
                        grid[rr][cc] = text;
                    }
                }
                colIndex += colSpan;
            }

            rowIndex++;
        }

        var width = grid.Count == 0 ? 0 : grid.Max(r => r.Count);
        var clean = new List<List<string>>(grid.Count);
        foreach (var r in grid)
        {
            var outRow = new List<string>(width);
            for (var c = 0; c < width; c++)
                outRow.Add(c < r.Count ? (r[c] ?? string.Empty) : string.Empty);
            clean.Add(outRow);
        }
        return clean;
    }

    private static int ParseSpanAttr(string attrs, string attrName)
    {
        var m = Regex.Match(attrs, $@"{attrName}\s*=\s*[""']?(\d+)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        return m.Success && int.TryParse(m.Groups[1].Value, out var v) ? Math.Clamp(v, 1, 20) : 1;
    }

    private static void EnsureWidth(List<string?> row, int targetWidth)
    {
        while (row.Count < targetWidth) row.Add(null);
    }

    private static int FindItemHeaderRow(List<List<string>> grid)
    {
        for (var i = 0; i < Math.Min(4, grid.Count); i++)
        {
            var cells = grid[i].Select(c => c.ToLowerInvariant()).ToArray();
            var hasDesc = cells.Any(c => c.Contains("desc") || c.Contains("particular") || c.Contains("item") || c.Contains("goods") || c.Contains("service"));
            var hasMoneyOrQty = cells.Any(c => c.Contains("hsn") || c.Contains("qty") || c.Contains("rate") || c.Contains("taxable") || c.Contains("amount") || c.Contains("total"));
            if (hasDesc && hasMoneyOrQty) return i;
        }
        return -1;
    }

    private sealed class ColumnMap
    {
        public int Description = -1;
        public int Hsn = -1;
        public int Qty = -1;
        public int Unit = -1;
        public int Rate = -1;
        public int Discount = -1;
        public int Taxable = -1;
        public int GstRate = -1;
        public int Cgst = -1;
        public int Sgst = -1;
        public int Igst = -1;
        public int Cess = -1;
        public int Total = -1;
    }

    private static ColumnMap BuildColumnMap(List<string> headerRow)
    {
        var map = new ColumnMap();
        for (var i = 0; i < headerRow.Count; i++)
        {
            var h = headerRow[i].Trim().ToLowerInvariant();
            if (h.Length == 0) continue;

            if (map.Description < 0 && (h.Contains("desc") || h.Contains("particular") || h.Contains("item") || h.Contains("goods") || h.Contains("product") || h.Contains("service")))
                map.Description = i;
            else if (map.Hsn < 0 && (h.Contains("hsn") || h.Contains("sac")))
                map.Hsn = i;
            else if (map.Qty < 0 && (h.Contains("qty") || h.Contains("quantity") || h == "nos" || h == "pcs"))
                map.Qty = i;
            else if (map.Unit < 0 && (h == "unit" || h == "uom" || h == "per"))
                map.Unit = i;
            else if (map.GstRate < 0 && (h.Contains("gst %") || h.Contains("gst%") || h.Contains("tax %") || h.Contains("tax rate") || h == "gst"))
                map.GstRate = i;
            else if (map.Rate < 0 && (h.Contains("rate") || h.Contains("price")))
                map.Rate = i;
            else if (map.Discount < 0 && h.Contains("disc"))
                map.Discount = i;
            else if (map.Cgst < 0 && h.Contains("cgst"))
                map.Cgst = i;
            else if (map.Sgst < 0 && h.Contains("sgst"))
                map.Sgst = i;
            else if (map.Igst < 0 && h.Contains("igst"))
                map.Igst = i;
            else if (map.Cess < 0 && h.Contains("cess"))
                map.Cess = i;
            else if (map.Taxable < 0 && (h.Contains("taxable") || h.Contains("assessable") || h.Contains("tax. val")))
                map.Taxable = i;
            else if (h.Contains("total") || h.Contains("amount"))
            {
                if (map.Taxable < 0 && !h.Contains("grand") && !h.Contains("net") && !h.Contains("line"))
                    map.Taxable = i;
                else
                    map.Total = i;
            }
        }
        return map;
    }

    private static bool TryConsumeSummaryRow(List<string> row, string joined, InvoiceExtractionResult result)
    {
        var lower = joined.ToLowerInvariant();
        if (!lower.Contains("total") && !lower.Contains("cgst") && !lower.Contains("sgst") &&
            !lower.Contains("igst") && !lower.Contains("round off") && !lower.Contains("round-off"))
        {
            return false;
        }

        var lastMoney = ExtractLastDecimal(row);
        if (lower.Contains("grand total") || lower.Contains("invoice total") || lower.Contains("net payable") ||
            (lower.StartsWith("total", StringComparison.OrdinalIgnoreCase) && !lower.Contains("taxable") && lastMoney > result.InvoiceTotal))
        {
            if (lastMoney > 0m) result.InvoiceTotal = lastMoney;
            return true;
        }

        if (lower.Contains("round off") || lower.Contains("round-off"))
        {
            if (TryParseSignedMoney(row.LastOrDefault(c => !string.IsNullOrWhiteSpace(c)), out var ro))
                result.RoundOff = ro;
            return true;
        }

        if (lower.Contains("cgst") && lastMoney > 0m && result.CgstTotal <= 0m) { result.CgstTotal = lastMoney; return true; }
        if (lower.Contains("sgst") && lastMoney > 0m && result.SgstTotal <= 0m) { result.SgstTotal = lastMoney; return true; }
        if (lower.Contains("igst") && lastMoney > 0m && result.IgstTotal <= 0m) { result.IgstTotal = lastMoney; return true; }
        if (lower.Contains("taxable") && lastMoney > 0m && result.TaxableTotal <= 0m) { result.TaxableTotal = lastMoney; return true; }
        if (lower.Contains("sub total") || lower.Contains("subtotal"))
        {
            if (lastMoney > 0m && result.TaxableTotal <= 0m) result.TaxableTotal = lastMoney;
            return true;
        }

        return lower.Contains("total");
    }

    private static InvoiceLineItem? MapRowToLineItem(List<string> row, ColumnMap map, string joined)
    {
        string Cell(int idx) => idx >= 0 && idx < row.Count ? row[idx].Trim() : string.Empty;

        var desc = Cell(map.Description);
        var taxable = ParseMoney(Cell(map.Taxable));
        var total = ParseMoney(Cell(map.Total));
        if (string.IsNullOrWhiteSpace(desc) && taxable <= 0m && total <= 0m)
            return null;

        var (qty, qtyUnit) = ParseQuantityAndUnit(Cell(map.Qty));
        var unit = Cell(map.Unit);
        if (unit.Length == 0 && qtyUnit.Length > 0) unit = qtyUnit;

        var hsn = Regex.Replace(Cell(map.Hsn), @"\s+", "");
        if (hsn.Contains('/')) hsn = hsn.Split('/')[0].Trim();

        var item = new InvoiceLineItem
        {
            Description = desc,
            HsnSac = hsn,
            Quantity = qty,
            Unit = unit,
            Rate = ParseMoney(Cell(map.Rate)),
            Discount = ParseMoney(Cell(map.Discount)),
            Taxable = taxable,
            GstRate = ParsePercent(Cell(map.GstRate)),
            Cgst = ParseMoney(Cell(map.Cgst)),
            Sgst = ParseMoney(Cell(map.Sgst)),
            Igst = ParseMoney(Cell(map.Igst)),
            Cess = ParseMoney(Cell(map.Cess)),
            LineTotal = total,
            SourceText = joined
        };

        if (item.Quantity == 0m && item.Rate == 0m && item.Taxable == 0m && item.LineTotal == 0m)
            return null;

        return item;
    }

    private static void ExtractSummaryTotalsFromText(string[] lines, InvoiceExtractionResult result)
    {
        foreach (var line in lines)
        {
            var m = ExtractLabeledMoney(line, "Grand Total", "Invoice Total", "Total Invoice Value", "Net Payable", "Total Amount");
            if (m > 0m && result.InvoiceTotal <= 0m) result.InvoiceTotal = m;

            var tax = ExtractLabeledMoney(line, "Taxable Value", "Taxable Amount", "Assessable Value", "Sub Total", "Subtotal");
            if (tax > 0m && result.TaxableTotal <= 0m) result.TaxableTotal = tax;

            var cgst = ExtractLabeledMoney(line, "Total CGST", "CGST");
            if (cgst > 0m && result.CgstTotal <= 0m && !line.Contains('%')) result.CgstTotal = cgst;

            var sgst = ExtractLabeledMoney(line, "Total SGST", "SGST");
            if (sgst > 0m && result.SgstTotal <= 0m && !line.Contains('%')) result.SgstTotal = sgst;

            var igst = ExtractLabeledMoney(line, "Total IGST", "IGST");
            if (igst > 0m && result.IgstTotal <= 0m && !line.Contains('%')) result.IgstTotal = igst;
        }
    }

    private static decimal ExtractLabeledMoney(string line, params string[] labels)
    {
        foreach (var label in labels)
        {
            var idx = line.IndexOf(label, StringComparison.OrdinalIgnoreCase);
            if (idx < 0) continue;
            var tail = line[(idx + label.Length)..];
            var m = MoneyTokenRegex().Match(tail);
            if (m.Success && ParseMoney(m.Value) is > 0m and var val)
                return val;
        }
        return 0m;
    }

    private static (decimal Qty, string Unit) ParseQuantityAndUnit(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return (0m, string.Empty);
        var m = Regex.Match(raw.Trim(), @"^([0-9,]+\.?[0-9]*)\s*([A-Za-z.]+)?$", RegexOptions.CultureInvariant);
        if (!m.Success) return (ParseMoney(raw), string.Empty);
        return (ParseMoney(m.Groups[1].Value), m.Groups[2].Value.Trim());
    }

    private static decimal ParsePercent(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return 0m;
        return ParseMoney(raw.Replace("%", "", StringComparison.Ordinal));
    }

    private static decimal ExtractLastDecimal(List<string> row)
    {
        for (var i = row.Count - 1; i >= 0; i--)
        {
            var val = ParseMoney(row[i]);
            if (val > 0m) return val;
        }
        return 0m;
    }

    internal static decimal ParseMoney(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return 0m;
        var cleaned = Regex.Replace(raw, @"[₹$€£,\s]|INR|RS\.?", "", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant).Trim();
        return decimal.TryParse(cleaned, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var val)
            ? val
            : 0m;
    }

    private static bool TryParseSignedMoney(string? raw, out decimal value)
    {
        value = 0m;
        if (string.IsNullOrWhiteSpace(raw)) return false;
        var cleaned = Regex.Replace(raw, @"[₹$€£,\s]|INR|RS\.?", "", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant).Trim();
        return decimal.TryParse(cleaned, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out value);
    }

    private static string StripMarkdownAndHtml(string raw) =>
        CleanWhitespace(WebUtility.HtmlDecode(HtmlTagRegex().Replace(raw ?? string.Empty, " ")).Replace("**", ""));

    private static string CleanWhitespace(string raw) =>
        MultiSpaceRegex().Replace(raw ?? string.Empty, " ").Trim();

    private static bool ContainsAny(this string text, IEnumerable<string> needles, StringComparison comparison) =>
        needles.Any(n => text.Contains(n, comparison));

    [GeneratedRegex(@"(?:Invoice\s*(?:No\.?|Number)|Bill\s*No\.?|Inv\s*No\.?)\s*[:#\-]?\s*([A-Za-z0-9][A-Za-z0-9/\-_]{1,35})", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex InvoiceNoRegex();

    [GeneratedRegex(@"\b(?:\d{1,2}[-./]\d{1,2}[-./]\d{2,4}|\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4}|\d{4}-\d{2}-\d{2})\b", RegexOptions.CultureInvariant)]
    private static partial Regex DateTokenRegex();

    [GeneratedRegex(@"<tr\b[^>]*>(.*?)</tr>", RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.CultureInvariant)]
    private static partial Regex TrRegex();

    [GeneratedRegex(@"<t[dh]\b([^>]*)>(.*?)</t[dh]>", RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.CultureInvariant)]
    private static partial Regex TdThRegex();

    [GeneratedRegex(@"<[^>]+>", RegexOptions.CultureInvariant)]
    private static partial Regex HtmlTagRegex();

    [GeneratedRegex(@"[0-9][0-9,]*\.?[0-9]*", RegexOptions.CultureInvariant)]
    private static partial Regex MoneyTokenRegex();

    [GeneratedRegex(@"\s+", RegexOptions.CultureInvariant)]
    private static partial Regex MultiSpaceRegex();
}
