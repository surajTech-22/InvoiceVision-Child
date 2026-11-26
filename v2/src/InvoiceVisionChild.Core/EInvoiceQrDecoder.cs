using System.Globalization;
using System.Text;
using System.Text.Json;
using InvoiceVisionChild.Contracts;

namespace InvoiceVisionChild.Core;

/// <summary>
/// Decodes Indian NIC GST e-Invoice QR strings (signed JWT payload or raw JSON object)
/// without network calls.
/// </summary>
public static class EInvoiceQrDecoder
{
    public static EInvoiceQrInfo? TryDecode(IEnumerable<string>? candidatePayloads)
    {
        if (candidatePayloads is null) return null;
        foreach (var raw in candidatePayloads)
        {
            var decoded = TryDecodeSingle(raw);
            if (decoded is { Detected: true })
                return decoded;
        }
        return null;
    }

    public static EInvoiceQrInfo? TryDecodeSingle(string? rawPayload)
    {
        var trimmed = (rawPayload ?? string.Empty).Trim();
        if (trimmed.Length < 10) return null;

        try
        {
            string? jsonText = null;
            if (trimmed.StartsWith('{'))
            {
                jsonText = trimmed;
            }
            else if (trimmed.Count(c => c == '.') == 2)
            {
                var parts = trimmed.Split('.');
                var payloadBytes = DecodeBase64Url(parts[1]);
                jsonText = Encoding.UTF8.GetString(payloadBytes);
            }

            if (string.IsNullOrWhiteSpace(jsonText)) return null;

            using var outerDoc = JsonDocument.Parse(jsonText);
            var target = outerDoc.RootElement;

            JsonDocument? innerDoc = null;
            try
            {
                if (target.ValueKind == JsonValueKind.Object &&
                    TryGetPropertyCaseInsensitive(target, "data", out var dataProp))
                {
                    if (dataProp.ValueKind == JsonValueKind.String)
                    {
                        var inner = dataProp.GetString();
                        if (!string.IsNullOrWhiteSpace(inner) && inner.TrimStart().StartsWith('{'))
                        {
                            innerDoc = JsonDocument.Parse(inner);
                            target = innerDoc.RootElement;
                        }
                    }
                    else if (dataProp.ValueKind == JsonValueKind.Object)
                    {
                        target = dataProp;
                    }
                }

                if (target.ValueKind != JsonValueKind.Object) return null;

                var sellerGstin = GstChecksumValidator.NormalizeGstin(ReadString(target, "SellerGstin"));
                var buyerGstin = GstChecksumValidator.NormalizeGstin(ReadString(target, "BuyerGstin"));
                var docNo = ReadString(target, "DocNo");
                var docDt = NormalizeDate(ReadString(target, "DocDt"));
                var docType = ReadString(target, "DocTyp");
                var total = ReadDecimal(target, "TotInvVal");
                var itemCnt = ReadInt(target, "ItemCnt");
                var mainHsn = ReadString(target, "MainHsnCode");
                var irn = ReadString(target, "Irn");

                if (sellerGstin.Length == 0 && docNo.Length == 0 && irn.Length == 0)
                    return null;

                return new EInvoiceQrInfo
                {
                    Detected = true,
                    Irn = irn,
                    SellerGstin = sellerGstin,
                    BuyerGstin = buyerGstin,
                    DocNo = docNo,
                    DocDate = docDt,
                    DocType = docType,
                    TotalValue = total,
                    ItemCount = itemCnt,
                    MainHsnCode = mainHsn,
                    RawPayload = trimmed
                };
            }
            finally
            {
                innerDoc?.Dispose();
            }
        }
        catch
        {
            return null;
        }
    }

    private static byte[] DecodeBase64Url(string segment)
    {
        var padded = segment.Replace('-', '+').Replace('_', '/');
        switch (padded.Length % 4)
        {
            case 2: padded += "=="; break;
            case 3: padded += "="; break;
        }
        return Convert.FromBase64String(padded);
    }

    private static bool TryGetPropertyCaseInsensitive(JsonElement obj, string name, out JsonElement value)
    {
        if (obj.TryGetProperty(name, out value)) return true;
        foreach (var prop in obj.EnumerateObject())
        {
            if (prop.Name.Equals(name, StringComparison.OrdinalIgnoreCase))
            {
                value = prop.Value;
                return true;
            }
        }
        value = default;
        return false;
    }

    private static string ReadString(JsonElement obj, string name) =>
        TryGetPropertyCaseInsensitive(obj, name, out var prop) && prop.ValueKind == JsonValueKind.String
            ? (prop.GetString() ?? string.Empty).Trim()
            : TryGetPropertyCaseInsensitive(obj, name, out prop) && prop.ValueKind == JsonValueKind.Number
                ? prop.ToString()
                : string.Empty;

    private static decimal ReadDecimal(JsonElement obj, string name)
    {
        if (!TryGetPropertyCaseInsensitive(obj, name, out var prop)) return 0m;
        if (prop.ValueKind == JsonValueKind.Number && prop.TryGetDecimal(out var dec)) return dec;
        if (prop.ValueKind == JsonValueKind.String &&
            decimal.TryParse(prop.GetString(), NumberStyles.Any, CultureInfo.InvariantCulture, out dec))
            return dec;
        return 0m;
    }

    private static int ReadInt(JsonElement obj, string name)
    {
        if (!TryGetPropertyCaseInsensitive(obj, name, out var prop)) return 0;
        if (prop.ValueKind == JsonValueKind.Number && prop.TryGetInt32(out var val)) return val;
        if (prop.ValueKind == JsonValueKind.String &&
            int.TryParse(prop.GetString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out val))
            return val;
        return 0;
    }

    internal static string NormalizeDate(string raw)
    {
        var trimmed = (raw ?? string.Empty).Trim();
        if (trimmed.Length == 0) return string.Empty;
        string[] formats =
        [
            "dd/MM/yyyy", "d/M/yyyy", "dd-MM-yyyy", "d-M-yyyy", "dd.MM.yyyy", "d.M.yyyy",
            "yyyy-MM-dd", "dd-MMM-yyyy", "d-MMM-yyyy", "dd MMM yyyy", "d MMM yyyy",
            "dd/MM/yy", "dd-MM-yy", "dd.MM.yy"
        ];
        if (DateTime.TryParseExact(trimmed, formats, CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out var dt))
            return dt.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
        return trimmed;
    }
}
