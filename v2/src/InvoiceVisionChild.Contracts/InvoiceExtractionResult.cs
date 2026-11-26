using System.Text.Json.Serialization;

namespace InvoiceVisionChild.Contracts;

/// <summary>
/// Canonical invoice extraction result produced by InvoiceVisionChild v2 and consumed by AAH.
/// Mirrors AAH's AAH-GST-INVOICE-CANONICAL-V1 structure with deterministic math verification metadata.
/// </summary>
public sealed class InvoiceExtractionResult
{
    public const string ResultSchema = "AAH-INVOICEVISION-RESULT-V1";
    public const string CanonicalSchema = "AAH-GST-INVOICE-CANONICAL-V1";

    [JsonPropertyName("schema")]
    public string Schema { get; set; } = ResultSchema;

    [JsonPropertyName("canonicalInvoiceSchema")]
    public string CanonicalInvoiceSchema { get; set; } = CanonicalSchema;

    [JsonPropertyName("requestId")]
    public string RequestId { get; set; } = string.Empty;

    [JsonPropertyName("clientId")]
    public long ClientId { get; set; }

    [JsonPropertyName("clientCode")]
    public string ClientCode { get; set; } = string.Empty;

    [JsonPropertyName("financialYear")]
    public string FinancialYear { get; set; } = string.Empty;

    /// <summary>Verified | ReviewRequired | Failed</summary>
    [JsonPropertyName("status")]
    public string Status { get; set; } = "ReviewRequired";

    [JsonPropertyName("userApproved")]
    public bool UserApproved { get; set; }

    [JsonPropertyName("engineUsed")]
    public string EngineUsed { get; set; } = string.Empty;

    [JsonPropertyName("extractedUtc")]
    public DateTime ExtractedUtc { get; set; } = DateTime.UtcNow;

    /// <summary>Purchase | Sales | Unknown</summary>
    [JsonPropertyName("direction")]
    public string Direction { get; set; } = "Unknown";

    [JsonPropertyName("documentType")]
    public string DocumentType { get; set; } = "Tax Invoice";

    [JsonPropertyName("invoiceNumber")]
    public string InvoiceNumber { get; set; } = string.Empty;

    /// <summary>Normalized yyyy-MM-dd when parsed cleanly.</summary>
    [JsonPropertyName("invoiceDate")]
    public string InvoiceDate { get; set; } = string.Empty;

    [JsonPropertyName("placeOfSupply")]
    public string PlaceOfSupply { get; set; } = string.Empty;

    [JsonPropertyName("reverseCharge")]
    public bool ReverseCharge { get; set; }

    [JsonPropertyName("seller")]
    public InvoicePartyInfo Seller { get; set; } = new();

    [JsonPropertyName("buyer")]
    public InvoicePartyInfo Buyer { get; set; } = new();

    [JsonPropertyName("rows")]
    public List<InvoiceLineItem> Rows { get; set; } = [];

    [JsonPropertyName("gstSlabs")]
    public List<InvoiceGstSlab> GstSlabs { get; set; } = [];

    [JsonPropertyName("taxableTotal")]
    public decimal TaxableTotal { get; set; }

    [JsonPropertyName("discountTotal")]
    public decimal DiscountTotal { get; set; }

    [JsonPropertyName("cgstTotal")]
    public decimal CgstTotal { get; set; }

    [JsonPropertyName("sgstTotal")]
    public decimal SgstTotal { get; set; }

    [JsonPropertyName("igstTotal")]
    public decimal IgstTotal { get; set; }

    [JsonPropertyName("cessTotal")]
    public decimal CessTotal { get; set; }

    [JsonPropertyName("creditNoteTotal")]
    public decimal CreditNoteTotal { get; set; }

    [JsonPropertyName("roundOff")]
    public decimal RoundOff { get; set; }

    [JsonPropertyName("invoiceTotal")]
    public decimal InvoiceTotal { get; set; }

    [JsonPropertyName("elapsedSeconds")]
    public double ElapsedSeconds { get; set; }

    [JsonPropertyName("preprocessedPageImages")]
    public List<string> PreprocessedPageImages { get; set; } = [];

    [JsonPropertyName("qrEvidence")]
    public EInvoiceQrInfo? QrEvidence { get; set; }

    [JsonPropertyName("verification")]
    public InvoiceVerificationReport Verification { get; set; } = new();

    [JsonPropertyName("sourceFiles")]
    public List<SourceFileDigest> SourceFiles { get; set; } = [];

    [JsonPropertyName("rawOcrText")]
    public string RawOcrText { get; set; } = string.Empty;

    [JsonPropertyName("rawTablesHtml")]
    public List<string> RawTablesHtml { get; set; } = [];

    [JsonPropertyName("renderedPageImages")]
    public List<string> RenderedPageImages { get; set; } = [];

    [JsonPropertyName("diagnosticsNote")]
    public string DiagnosticsNote { get; set; } = string.Empty;

    [JsonPropertyName("supplierMemory")]
    public SupplierMemorySummary? SupplierMemory { get; set; }
}

public sealed class SupplierMemorySummary
{
    [JsonPropertyName("profileFound")]
    public bool ProfileFound { get; set; }

    [JsonPropertyName("gstin")]
    public string Gstin { get; set; } = string.Empty;

    [JsonPropertyName("canonicalName")]
    public string CanonicalName { get; set; } = string.Empty;

    [JsonPropertyName("confirmedCount")]
    public int ConfirmedCount { get; set; }

    [JsonPropertyName("preferredDirection")]
    public string PreferredDirection { get; set; } = string.Empty;

    [JsonPropertyName("preferredRecognitionMode")]
    public string PreferredRecognitionMode { get; set; } = string.Empty;

    [JsonPropertyName("appliedRules")]
    public List<string> AppliedRules { get; set; } = [];
}

public sealed class InvoicePartyInfo
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("gstin")]
    public string Gstin { get; set; } = string.Empty;

    [JsonPropertyName("gstinValid")]
    public bool GstinValid { get; set; }

    [JsonPropertyName("stateCode")]
    public string StateCode { get; set; } = string.Empty;

    [JsonPropertyName("stateName")]
    public string StateName { get; set; } = string.Empty;
}

public sealed class InvoiceLineItem
{
    [JsonPropertyName("lineNumber")]
    public int LineNumber { get; set; }

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;

    [JsonPropertyName("hsnSac")]
    public string HsnSac { get; set; } = string.Empty;

    [JsonPropertyName("quantity")]
    public decimal Quantity { get; set; }

    [JsonPropertyName("unit")]
    public string Unit { get; set; } = string.Empty;

    [JsonPropertyName("rate")]
    public decimal Rate { get; set; }

    [JsonPropertyName("discount")]
    public decimal Discount { get; set; }

    [JsonPropertyName("taxable")]
    public decimal Taxable { get; set; }

    [JsonPropertyName("gstRate")]
    public decimal GstRate { get; set; }

    [JsonPropertyName("cgst")]
    public decimal Cgst { get; set; }

    [JsonPropertyName("sgst")]
    public decimal Sgst { get; set; }

    [JsonPropertyName("igst")]
    public decimal Igst { get; set; }

    [JsonPropertyName("cess")]
    public decimal Cess { get; set; }

    [JsonPropertyName("lineTotal")]
    public decimal LineTotal { get; set; }

    /// <summary>OK | Mismatch | Incomplete</summary>
    [JsonPropertyName("mathStatus")]
    public string MathStatus { get; set; } = "Incomplete";

    [JsonPropertyName("mathNote")]
    public string MathNote { get; set; } = string.Empty;

    [JsonPropertyName("sourceText")]
    public string SourceText { get; set; } = string.Empty;
}

public sealed class InvoiceGstSlab
{
    [JsonPropertyName("gstRate")]
    public decimal GstRate { get; set; }

    [JsonPropertyName("taxable")]
    public decimal Taxable { get; set; }

    [JsonPropertyName("cgst")]
    public decimal Cgst { get; set; }

    [JsonPropertyName("sgst")]
    public decimal Sgst { get; set; }

    [JsonPropertyName("igst")]
    public decimal Igst { get; set; }

    [JsonPropertyName("cess")]
    public decimal Cess { get; set; }

    [JsonPropertyName("combinedTax")]
    public decimal CombinedTax { get; set; }
}

public sealed class EInvoiceQrInfo
{
    [JsonPropertyName("detected")]
    public bool Detected { get; set; }

    [JsonPropertyName("irn")]
    public string Irn { get; set; } = string.Empty;

    [JsonPropertyName("sellerGstin")]
    public string SellerGstin { get; set; } = string.Empty;

    [JsonPropertyName("buyerGstin")]
    public string BuyerGstin { get; set; } = string.Empty;

    [JsonPropertyName("docNo")]
    public string DocNo { get; set; } = string.Empty;

    [JsonPropertyName("docDate")]
    public string DocDate { get; set; } = string.Empty;

    [JsonPropertyName("docType")]
    public string DocType { get; set; } = string.Empty;

    [JsonPropertyName("totalValue")]
    public decimal TotalValue { get; set; }

    [JsonPropertyName("itemCount")]
    public int ItemCount { get; set; }

    [JsonPropertyName("mainHsnCode")]
    public string MainHsnCode { get; set; } = string.Empty;

    [JsonPropertyName("rawPayload")]
    public string RawPayload { get; set; } = string.Empty;
}

public sealed class InvoiceVerificationReport
{
    [JsonPropertyName("isBalanced")]
    public bool IsBalanced { get; set; }

    [JsonPropertyName("score")]
    public int Score { get; set; }

    [JsonPropertyName("passedChecks")]
    public List<string> PassedChecks { get; set; } = [];

    [JsonPropertyName("warnings")]
    public List<string> Warnings { get; set; } = [];

    [JsonPropertyName("errors")]
    public List<string> Errors { get; set; } = [];
}

public sealed class SourceFileDigest
{
    [JsonPropertyName("path")]
    public string Path { get; set; } = string.Empty;

    [JsonPropertyName("sha256")]
    public string Sha256 { get; set; } = string.Empty;

    [JsonPropertyName("fileBytes")]
    public long FileBytes { get; set; }
}
