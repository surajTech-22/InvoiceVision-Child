using System.Text.Json.Serialization;

namespace InvoiceVisionChild.Contracts;

/// <summary>
/// Request payload for InvoiceVisionChild --analyze (offline deterministic + local Qwen text-only GST analyst).
/// </summary>
public sealed class InvoiceAnalysisRequest
{
    public const string CurrentSchema = "AAH-INVOICEVISION-ANALYSIS-REQUEST-V1";

    [JsonPropertyName("schema")]
    public string Schema { get; set; } = CurrentSchema;

    [JsonPropertyName("requestId")]
    public string RequestId { get; set; } = Guid.NewGuid().ToString("N");

    [JsonPropertyName("invoiceNumber")]
    public string InvoiceNumber { get; set; } = string.Empty;

    [JsonPropertyName("invoiceDate")]
    public string InvoiceDate { get; set; } = string.Empty;

    [JsonPropertyName("direction")]
    public string Direction { get; set; } = "Auto";

    [JsonPropertyName("recognitionMode")]
    public string RecognitionMode { get; set; } = "Accounting Invoice";

    [JsonPropertyName("clientGstin")]
    public string ClientGstin { get; set; } = string.Empty;

    [JsonPropertyName("sellerName")]
    public string SellerName { get; set; } = string.Empty;

    [JsonPropertyName("sellerGstin")]
    public string SellerGstin { get; set; } = string.Empty;

    [JsonPropertyName("buyerName")]
    public string BuyerName { get; set; } = string.Empty;

    [JsonPropertyName("buyerGstin")]
    public string BuyerGstin { get; set; } = string.Empty;

    [JsonPropertyName("taxableTotal")]
    public decimal TaxableTotal { get; set; }

    [JsonPropertyName("cgstTotal")]
    public decimal CgstTotal { get; set; }

    [JsonPropertyName("sgstTotal")]
    public decimal SgstTotal { get; set; }

    [JsonPropertyName("igstTotal")]
    public decimal IgstTotal { get; set; }

    [JsonPropertyName("cessTotal")]
    public decimal CessTotal { get; set; }

    [JsonPropertyName("roundOff")]
    public decimal RoundOff { get; set; }

    [JsonPropertyName("invoiceTotal")]
    public decimal InvoiceTotal { get; set; }

    [JsonPropertyName("rows")]
    public List<InvoiceLineItem> Rows { get; set; } = [];

    [JsonPropertyName("gstSlabs")]
    public List<InvoiceGstSlab> GstSlabs { get; set; } = [];

    [JsonPropertyName("rawOcrText")]
    public string RawOcrText { get; set; } = string.Empty;

    [JsonPropertyName("blockingFlags")]
    public List<string> BlockingFlags { get; set; } = [];

    [JsonPropertyName("memoryDbPath")]
    public string MemoryDbPath { get; set; } = string.Empty;

    [JsonPropertyName("useLlm")]
    public bool UseLlm { get; set; } = true;

    [JsonPropertyName("outputPath")]
    public string OutputPath { get; set; } = string.Empty;
}

public sealed class InvoiceAnalysisResult
{
    [JsonPropertyName("schema")]
    public string Schema { get; set; } = "AAH-INVOICEVISION-ANALYSIS-V1";

    [JsonPropertyName("verdict")]
    public string Verdict { get; set; } = string.Empty;

    [JsonPropertyName("summary")]
    public string Summary { get; set; } = string.Empty;

    [JsonPropertyName("postingPreview")]
    public string PostingPreview { get; set; } = string.Empty;

    [JsonPropertyName("supplierMemoryStatus")]
    public string SupplierMemoryStatus { get; set; } = string.Empty;

    [JsonPropertyName("findings")]
    public List<string> Findings { get; set; } = [];

    [JsonPropertyName("recommendations")]
    public List<string> Recommendations { get; set; } = [];

    [JsonPropertyName("llmExplanation")]
    public string LlmExplanation { get; set; } = string.Empty;

    [JsonPropertyName("llmEngineUsed")]
    public string LlmEngineUsed { get; set; } = string.Empty;

    [JsonPropertyName("elapsedSec")]
    public double ElapsedSec { get; set; }
}
