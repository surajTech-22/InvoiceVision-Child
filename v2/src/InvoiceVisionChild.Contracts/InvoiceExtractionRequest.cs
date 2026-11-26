using System.Text.Json.Serialization;

namespace InvoiceVisionChild.Contracts;

/// <summary>
/// Request payload written by AAH and passed to InvoiceVisionChild (--request).
/// Child never opens accounting-hub.db or Tally directly.
/// </summary>
public sealed class InvoiceExtractionRequest
{
    public const string CurrentSchema = "AAH-INVOICEVISION-REQUEST-V1";

    [JsonPropertyName("schema")]
    public string Schema { get; set; } = CurrentSchema;

    [JsonPropertyName("requestId")]
    public string RequestId { get; set; } = Guid.NewGuid().ToString("N");

    [JsonPropertyName("clientId")]
    public long ClientId { get; set; }

    [JsonPropertyName("clientCode")]
    public string ClientCode { get; set; } = string.Empty;

    [JsonPropertyName("clientName")]
    public string ClientName { get; set; } = string.Empty;

    [JsonPropertyName("clientGstin")]
    public string ClientGstin { get; set; } = string.Empty;

    [JsonPropertyName("financialYear")]
    public string FinancialYear { get; set; } = string.Empty;

    /// <summary>Auto | Purchase | Sales</summary>
    [JsonPropertyName("directionHint")]
    public string DirectionHint { get; set; } = "Auto";

    [JsonPropertyName("sourceFiles")]
    public List<string> SourceFiles { get; set; } = [];

    [JsonPropertyName("outputPath")]
    public string OutputPath { get; set; } = string.Empty;

    [JsonPropertyName("scanId")]
    public string ScanId { get; set; } = string.Empty;

    [JsonPropertyName("workDirectory")]
    public string WorkDirectory { get; set; } = string.Empty;

    /// <summary>review | extract | hybrid | fast | qwen</summary>
    [JsonPropertyName("mode")]
    public string Mode { get; set; } = "hybrid";

    [JsonPropertyName("cachedPageOcrTexts")]
    public List<string> CachedPageOcrTexts { get; set; } = [];

    [JsonPropertyName("memoryDbPath")]
    public string MemoryDbPath { get; set; } = string.Empty;
}
