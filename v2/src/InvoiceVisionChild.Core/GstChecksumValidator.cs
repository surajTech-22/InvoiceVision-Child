using System.Text.RegularExpressions;

namespace InvoiceVisionChild.Core;

public static partial class GstChecksumValidator
{
    private const string Alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    private static readonly IReadOnlyDictionary<string, string> StateNames =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["01"] = "Jammu & Kashmir", ["02"] = "Himachal Pradesh", ["03"] = "Punjab",
            ["04"] = "Chandigarh", ["05"] = "Uttarakhand", ["06"] = "Haryana",
            ["07"] = "Delhi", ["08"] = "Rajasthan", ["09"] = "Uttar Pradesh",
            ["10"] = "Bihar", ["11"] = "Sikkim", ["12"] = "Arunachal Pradesh",
            ["13"] = "Nagaland", ["14"] = "Manipur", ["15"] = "Mizoram",
            ["16"] = "Tripura", ["17"] = "Meghalaya", ["18"] = "Assam",
            ["19"] = "West Bengal", ["20"] = "Jharkhand", ["21"] = "Odisha",
            ["22"] = "Chhattisgarh", ["23"] = "Madhya Pradesh", ["24"] = "Gujarat",
            ["26"] = "Dadra & Nagar Haveli and Daman & Diu", ["27"] = "Maharashtra",
            ["28"] = "Andhra Pradesh (Old)", ["29"] = "Karnataka", ["30"] = "Goa",
            ["31"] = "Lakshadweep", ["32"] = "Kerala", ["33"] = "Tamil Nadu",
            ["34"] = "Puducherry", ["35"] = "Andaman & Nicobar Islands",
            ["36"] = "Telangana", ["37"] = "Andhra Pradesh", ["38"] = "Ladakh",
            ["97"] = "Other Territory"
        };

    [GeneratedRegex(@"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$", RegexOptions.CultureInvariant)]
    private static partial Regex GstinShapeRegex();

    [GeneratedRegex(@"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", RegexOptions.CultureInvariant)]
    private static partial Regex GstinCandidateRegex();

    [GeneratedRegex(@"^[0-9]{4}([0-9]{2})?([0-9]{2})?$", RegexOptions.CultureInvariant)]
    private static partial Regex HsnSacRegex();

    public static string NormalizeGstin(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return string.Empty;
        return new string(raw.Where(char.IsLetterOrDigit).Select(char.ToUpperInvariant).ToArray());
    }

    public static bool IsValidGstin(string? raw)
    {
        var normalized = NormalizeGstin(raw);
        if (normalized.Length != 15 || !GstinShapeRegex().IsMatch(normalized))
            return false;

        var state = normalized[..2];
        if (!StateNames.ContainsKey(state))
            return false;

        return ComputeCheckDigit(normalized[..14]) == normalized[14];
    }

    public static char ComputeCheckDigit(string first14)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(first14);
        var upper = first14.Trim().ToUpperInvariant();
        if (upper.Length != 14)
            throw new ArgumentException("GSTIN prefix must be exactly 14 characters.", nameof(first14));

        var sum = 0;
        for (var i = 0; i < 14; i++)
        {
            var codePoint = Alphabet.IndexOf(upper[i]);
            if (codePoint < 0)
                throw new ArgumentException($"Invalid GSTIN character '{upper[i]}'.", nameof(first14));

            var factor = (i % 2 == 0) ? 1 : 2;
            var product = codePoint * factor;
            sum += (product / 36) + (product % 36);
        }

        var checkIndex = (36 - (sum % 36)) % 36;
        return Alphabet[checkIndex];
    }

    public static string TryGetStateCode(string? gstin)
    {
        var normalized = NormalizeGstin(gstin);
        if (normalized.Length < 2) return string.Empty;
        var code = normalized[..2];
        return StateNames.ContainsKey(code) ? code : string.Empty;
    }

    public static string TryGetStateName(string? stateCodeOrGstin)
    {
        if (string.IsNullOrWhiteSpace(stateCodeOrGstin)) return string.Empty;
        var trimmed = stateCodeOrGstin.Trim();
        if (trimmed.Length >= 2 && StateNames.TryGetValue(trimmed[..2], out var byCode))
            return byCode;

        foreach (var kvp in StateNames)
        {
            if (trimmed.Contains(kvp.Value, StringComparison.OrdinalIgnoreCase))
                return kvp.Value;
        }
        return string.Empty;
    }

    public static IReadOnlyList<string> ExtractValidGstins(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return Array.Empty<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var result = new List<string>();
        foreach (Match m in GstinCandidateRegex().Matches(text.ToUpperInvariant()))
        {
            var val = m.Value;
            if (IsValidGstin(val) && seen.Add(val))
                result.Add(val);
        }
        return result;
    }

    public static bool IsValidHsnSac(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return false;
        var cleaned = raw.Trim();
        return HsnSacRegex().IsMatch(cleaned);
    }
}
