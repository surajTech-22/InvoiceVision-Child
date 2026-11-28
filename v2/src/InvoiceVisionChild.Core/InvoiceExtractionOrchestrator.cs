using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using InvoiceVisionChild.Contracts;

namespace InvoiceVisionChild.Core;

public static class InvoiceExtractionOrchestrator
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public static string ComputeSha256(string filePath)
    {
        using var stream = File.OpenRead(filePath);
        return Convert.ToHexString(SHA256.HashData(stream));
    }

    public static void WriteJsonAtomically<T>(string destinationPath, T payload)
    {
        var full = Path.GetFullPath(destinationPath);
        Directory.CreateDirectory(Path.GetDirectoryName(full)!);
        var tmp = full + ".tmp";
        var json = JsonSerializer.Serialize(payload, JsonOptions);
        File.WriteAllText(tmp, json, new UTF8Encoding(false));
        File.Move(tmp, full, overwrite: true);
    }

    public static async Task<InvoiceExtractionResult> ExtractAsync(
        InvoiceExtractionRequest request,
        OcrRuntimePaths? runtimeOverride = null,
        Action<int, string>? onProgress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (request.SourceFiles.Count == 0)
            throw new ArgumentException("At least one source image or PDF is required.", nameof(request));

        var resolvedFiles = request.SourceFiles.Select(Path.GetFullPath).ToArray();
        foreach (var f in resolvedFiles)
        {
            if (!File.Exists(f))
                throw new FileNotFoundException("Source invoice file not found.", f);
        }

        var runtime = runtimeOverride ?? OcrRuntimeLocator.Locate();
        if (!runtime.IsReady)
            throw new InvalidOperationException("InvoiceVision runtime is not ready: " + string.Join(", ", runtime.GetMissingComponents()));

        var initialDigests = resolvedFiles.Select(f => new SourceFileDigest
        {
            Path = f,
            Sha256 = ComputeSha256(f),
            FileBytes = new FileInfo(f).Length
        }).ToArray();

        var workDir = string.IsNullOrWhiteSpace(request.WorkDirectory)
            ? Path.Combine(
                string.IsNullOrWhiteSpace(request.OutputPath) ? Path.GetTempPath() : Path.GetDirectoryName(Path.GetFullPath(request.OutputPath))!,
                "work_" + request.RequestId)
            : Path.GetFullPath(request.WorkDirectory);
        Directory.CreateDirectory(workDir);
        var workerOutput = Path.Combine(workDir, "worker_output.json");
        if (File.Exists(workerOutput)) File.Delete(workerOutput);

        var modeArg = (request.Mode ?? "hybrid").Trim().ToLowerInvariant() switch
        {
            "fast" => "fast",
            "qwen" => "qwen",
            _ => "hybrid"
        };

        var psi = new ProcessStartInfo(runtime.PythonExe)
        {
            WorkingDirectory = Path.GetDirectoryName(runtime.WorkerScript)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        psi.ArgumentList.Add("-u");
        psi.ArgumentList.Add(runtime.WorkerScript);
        foreach (var file in resolvedFiles)
        {
            psi.ArgumentList.Add("--input");
            psi.ArgumentList.Add(file);
        }
        psi.ArgumentList.Add("--output");
        psi.ArgumentList.Add(workerOutput);
        psi.ArgumentList.Add("--work-dir");
        psi.ArgumentList.Add(workDir);
        var sharedCacheDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "InvoiceVisionChild",
            "Cache");
        Directory.CreateDirectory(sharedCacheDir);
        psi.ArgumentList.Add("--cache-dir");
        psi.ArgumentList.Add(sharedCacheDir);
        psi.ArgumentList.Add("--mode");
        psi.ArgumentList.Add(modeArg);
        if (!string.IsNullOrWhiteSpace(request.ClientGstin))
        {
            psi.ArgumentList.Add("--client-gstin");
            psi.ArgumentList.Add(request.ClientGstin);
        }
        if (!string.IsNullOrWhiteSpace(request.DirectionHint))
        {
            psi.ArgumentList.Add("--direction");
            psi.ArgumentList.Add(request.DirectionHint);
        }
        psi.ArgumentList.Add("--llama-server");
        psi.ArgumentList.Add(runtime.LlamaServerExe);
        psi.ArgumentList.Add("--lighton-model");
        psi.ArgumentList.Add(runtime.LightOnModel);
        psi.ArgumentList.Add("--lighton-mmproj");
        psi.ArgumentList.Add(runtime.LightOnMmproj);
        if (runtime.HasQwenHybrid)
        {
            psi.ArgumentList.Add("--qwen-model");
            psi.ArgumentList.Add(runtime.QwenModel);
            psi.ArgumentList.Add("--qwen-mmproj");
            psi.ArgumentList.Add(runtime.QwenMmproj);
        }
        if (!string.IsNullOrWhiteSpace(runtime.PaddleXCacheDir))
        {
            psi.ArgumentList.Add("--paddlex-cache");
            psi.ArgumentList.Add(runtime.PaddleXCacheDir);
        }
        if (!string.IsNullOrWhiteSpace(request.MemoryDbPath))
        {
            psi.ArgumentList.Add("--memory-db");
            psi.ArgumentList.Add(Path.GetFullPath(request.MemoryDbPath));
        }
        if (request.CachedPageOcrTexts.Count == resolvedFiles.Length &&
            request.CachedPageOcrTexts.All(t => !string.IsNullOrWhiteSpace(t)))
        {
            var cachedOcrPath = Path.Combine(workDir, "cached_ocr.json");
            WriteJsonAtomically(cachedOcrPath, request.CachedPageOcrTexts);
            psi.ArgumentList.Add("--cached-ocr-json");
            psi.ArgumentList.Add(cachedOcrPath);
        }
        psi.ArgumentList.Add("--progress");

        onProgress?.Invoke(2, "Starting InvoiceVision v2 OCR worker...");

        using var proc = new Process { StartInfo = psi };
        if (!proc.Start())
            throw new IOException("Failed to launch InvoiceVision Python OCR worker.");

        var timeoutMinutes = Math.Clamp(resolvedFiles.Length * 5, 12, 45);
        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(TimeSpan.FromMinutes(timeoutMinutes));

        var stdoutLog = new StringBuilder();
        var stderrTask = proc.StandardError.ReadToEndAsync(timeoutCts.Token);
        var stdoutTask = Task.Run(async () =>
        {
            string? line;
            while ((line = await proc.StandardOutput.ReadLineAsync(timeoutCts.Token).ConfigureAwait(false)) is not null)
            {
                stdoutLog.AppendLine(line);
                if (line.StartsWith("PROGRESS|", StringComparison.Ordinal))
                {
                    var parts = line.Split('|', 3);
                    if (parts.Length == 3 && int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var pct))
                        onProgress?.Invoke(pct, parts[2]);
                }
            }
        }, timeoutCts.Token);

        try
        {
            await Task.WhenAll(stdoutTask, stderrTask, proc.WaitForExitAsync(timeoutCts.Token)).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try { if (!proc.HasExited) proc.Kill(entireProcessTree: true); } catch { }
            if (cancellationToken.IsCancellationRequested) throw;
            throw new TimeoutException($"InvoiceVision OCR extraction timed out after {timeoutMinutes} minutes.");
        }

        var stderr = await stderrTask.ConfigureAwait(false);
        if (proc.ExitCode != 0 || !File.Exists(workerOutput))
        {
            var detail = (stderr + "\n" + stdoutLog).Trim();
            if (detail.Length > 1000) detail = detail[^1000..];
            throw new InvalidOperationException($"InvoiceVision worker failed (exit {proc.ExitCode}): {detail}");
        }

        // Verify source files were never mutated during extraction
        for (var i = 0; i < initialDigests.Length; i++)
        {
            var currentHash = ComputeSha256(initialDigests[i].Path);
            if (!currentHash.Equals(initialDigests[i].Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Source file changed on disk during extraction: {initialDigests[i].Path}");
        }

        var workerJson = await File.ReadAllTextAsync(workerOutput, cancellationToken).ConfigureAwait(false);
        var result = ConvertWorkerPayloadToResult(workerJson, request, initialDigests);
        InvoiceMathVerifier.Verify(result);

        if (!string.IsNullOrWhiteSpace(request.OutputPath))
            WriteJsonAtomically(request.OutputPath, result);

        onProgress?.Invoke(100, $"Completed in {result.ElapsedSeconds:0.0}s · {result.EngineUsed}");
        return result;
    }

    public static InvoiceExtractionResult ConvertWorkerPayloadToResult(
        string workerJson,
        InvoiceExtractionRequest request,
        IReadOnlyList<SourceFileDigest> sourceDigests)
    {
        using var doc = JsonDocument.Parse(workerJson);
        var root = doc.RootElement;
        var canon = root.GetProperty("canonical");

        var result = new InvoiceExtractionResult
        {
            RequestId = request.RequestId,
            ClientId = request.ClientId,
            ClientCode = request.ClientCode,
            FinancialYear = request.FinancialYear,
            EngineUsed = ReadStr(root, "engineUsed"),
            ExtractedUtc = DateTime.UtcNow,
            ElapsedSeconds = ReadDouble(root, "elapsedSec"),
            DocumentType = ReadStr(canon, "documentType", "Tax Invoice"),
            InvoiceNumber = ReadStr(canon, "invoiceNumber"),
            InvoiceDate = ReadStr(canon, "invoiceDate"),
            PlaceOfSupply = ReadStr(canon, "placeOfSupply"),
            ReverseCharge = ReadBool(canon, "reverseCharge"),
            TaxableTotal = ReadDec(canon, "taxableTotal"),
            DiscountTotal = ReadDec(canon, "discountTotal"),
            CgstTotal = ReadDec(canon, "cgstTotal"),
            SgstTotal = ReadDec(canon, "sgstTotal"),
            IgstTotal = ReadDec(canon, "igstTotal"),
            CessTotal = ReadDec(canon, "cessTotal"),
            CreditNoteTotal = ReadDec(canon, "creditNoteTotal"),
            RoundOff = ReadDec(canon, "roundOff"),
            InvoiceTotal = ReadDec(canon, "invoiceTotal"),
            RawOcrText = ReadStr(root, "rawOcrText"),
            RawTablesHtml = ReadStrArray(root, "rawTablesHtml"),
            RenderedPageImages = ReadStrArray(root, "renderedPageImages"),
            PreprocessedPageImages = ReadStrArray(root, "preprocessedImages"),
            SourceFiles = sourceDigests.ToList()
        };

        if (canon.TryGetProperty("seller", out var sellerEl))
        {
            result.Seller.Name = ReadStr(sellerEl, "name");
            result.Seller.Gstin = GstChecksumValidator.NormalizeGstin(ReadStr(sellerEl, "gstin"));
        }
        if (canon.TryGetProperty("buyer", out var buyerEl))
        {
            result.Buyer.Name = ReadStr(buyerEl, "name");
            result.Buyer.Gstin = GstChecksumValidator.NormalizeGstin(ReadStr(buyerEl, "gstin"));
        }

        if (root.TryGetProperty("qrInfo", out var qrInfo) &&
            qrInfo.TryGetProperty("raw_codes", out var rawCodesEl) &&
            rawCodesEl.ValueKind == JsonValueKind.Array)
        {
            var rawCodes = rawCodesEl.EnumerateArray()
                .Select(x => x.GetString() ?? string.Empty)
                .Where(s => s.Length > 0)
                .ToArray();
            result.QrEvidence = EInvoiceQrDecoder.TryDecode(rawCodes);
        }

        if (canon.TryGetProperty("rows", out var rowsEl) && rowsEl.ValueKind == JsonValueKind.Array)
        {
            var lineNo = 0;
            foreach (var r in rowsEl.EnumerateArray())
            {
                lineNo++;
                result.Rows.Add(new InvoiceLineItem
                {
                    LineNumber = lineNo,
                    Description = ReadStr(r, "description"),
                    HsnSac = ReadStr(r, "hsnSac"),
                    Quantity = ReadDec(r, "quantity"),
                    Unit = ReadStr(r, "unit"),
                    Rate = ReadDec(r, "rate"),
                    Discount = ReadDec(r, "discount"),
                    Taxable = ReadDec(r, "taxable"),
                    GstRate = ReadDec(r, "gstRate"),
                    Cgst = ReadDec(r, "cgst"),
                    Sgst = ReadDec(r, "sgst"),
                    Igst = ReadDec(r, "igst"),
                    Cess = ReadDec(r, "cess"),
                    LineTotal = ReadDec(r, "lineTotal")
                });
            }
        }

        if (canon.TryGetProperty("gstSlabs", out var slabsEl) && slabsEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var s in slabsEl.EnumerateArray())
            {
                result.GstSlabs.Add(new InvoiceGstSlab
                {
                    GstRate = ReadDec(s, "gstRate"),
                    Taxable = ReadDec(s, "taxable"),
                    Cgst = ReadDec(s, "cgst"),
                    Sgst = ReadDec(s, "sgst"),
                    Igst = ReadDec(s, "igst"),
                    Cess = ReadDec(s, "cess"),
                    CombinedTax = ReadDec(s, "combinedTax")
                });
            }
        }

        if (root.TryGetProperty("supplierMemory", out var memEl) && memEl.ValueKind == JsonValueKind.Object)
        {
            result.SupplierMemory = new SupplierMemorySummary
            {
                ProfileFound = ReadBool(memEl, "profileFound"),
                Gstin = ReadStr(memEl, "gstin"),
                CanonicalName = ReadStr(memEl, "canonicalName"),
                ConfirmedCount = memEl.TryGetProperty("confirmedCount", out var cc) && cc.TryGetInt32(out var ci) ? ci : 0,
                PreferredDirection = ReadStr(memEl, "preferredDirection"),
                PreferredRecognitionMode = ReadStr(memEl, "preferredRecognitionMode"),
                AppliedRules = ReadStrArray(memEl, "appliedRules")
            };
        }

        // Resolve Seller/Buyer vs Client GSTIN to assign Purchase/Sales direction cleanly
        var clientGstin = GstChecksumValidator.NormalizeGstin(request.ClientGstin);
        var clientIsSeller = clientGstin.Length == 15 && clientGstin.Equals(result.Seller.Gstin, StringComparison.OrdinalIgnoreCase);
        var clientIsBuyer = clientGstin.Length == 15 && clientGstin.Equals(result.Buyer.Gstin, StringComparison.OrdinalIgnoreCase);

        if (clientIsSeller && !clientIsBuyer) result.Direction = "Sales";
        else if (clientIsBuyer && !clientIsSeller) result.Direction = "Purchase";
        else if (request.DirectionHint.Equals("Sales", StringComparison.OrdinalIgnoreCase) ||
                 request.DirectionHint.Equals("Purchase", StringComparison.OrdinalIgnoreCase))
            result.Direction = request.DirectionHint;
        else
            result.Direction = "Unknown";

        if (clientGstin.Length == 15 && !string.IsNullOrWhiteSpace(request.ClientName))
        {
            if (clientIsBuyer && string.IsNullOrWhiteSpace(result.Buyer.Name))
                result.Buyer.Name = request.ClientName.Trim();
            else if (clientIsSeller && string.IsNullOrWhiteSpace(result.Seller.Name))
                result.Seller.Name = request.ClientName.Trim();
        }

        if (root.TryGetProperty("audit", out var auditEl) && auditEl.ValueKind == JsonValueKind.Object)
        {
            var blocking = ReadStrArray(auditEl, "blocking_issues");
            foreach (var issue in blocking)
            {
                if (!string.IsNullOrWhiteSpace(issue))
                {
                    if (!result.WorkerBlockingIssues.Contains(issue, StringComparer.OrdinalIgnoreCase))
                        result.WorkerBlockingIssues.Add(issue);
                    if (!result.Verification.Errors.Contains(issue, StringComparer.OrdinalIgnoreCase))
                        result.Verification.Errors.Add(issue);
                }
            }
            if (blocking.Count > 0 || (auditEl.TryGetProperty("fully_balanced", out var fb) && fb.ValueKind == JsonValueKind.False))
            {
                if (result.WorkerBlockingIssues.Count == 0)
                    result.WorkerBlockingIssues.Add("Worker GST audit reported invoice not fully balanced.");
                result.Verification.IsBalanced = false;
                result.Status = "ReviewRequired";
            }
        }

        return result;
    }

    private static string ReadStr(JsonElement el, string prop, string fallback = "") =>
        el.ValueKind == JsonValueKind.Object && el.TryGetProperty(prop, out var v) && v.ValueKind != JsonValueKind.Null
            ? (v.ValueKind == JsonValueKind.String ? v.GetString() ?? fallback : v.ToString()).Trim()
            : fallback;

    private static bool ReadBool(JsonElement el, string prop) =>
        el.ValueKind == JsonValueKind.Object && el.TryGetProperty(prop, out var v) && v.ValueKind == JsonValueKind.True;

    private static double ReadDouble(JsonElement el, string prop) =>
        el.ValueKind == JsonValueKind.Object && el.TryGetProperty(prop, out var v) && v.TryGetDouble(out var d) ? d : 0.0;

    private static decimal ReadDec(JsonElement el, string prop)
    {
        if (el.ValueKind != JsonValueKind.Object || !el.TryGetProperty(prop, out var v)) return 0m;
        if (v.ValueKind == JsonValueKind.Number && v.TryGetDecimal(out var dec)) return dec;
        if (v.ValueKind == JsonValueKind.String && decimal.TryParse(v.GetString(), NumberStyles.Any, CultureInfo.InvariantCulture, out dec)) return dec;
        return 0m;
    }

    private static List<string> ReadStrArray(JsonElement el, string prop)
    {
        var list = new List<string>();
        if (el.ValueKind != JsonValueKind.Object || !el.TryGetProperty(prop, out var arr) || arr.ValueKind != JsonValueKind.Array)
            return list;
        foreach (var item in arr.EnumerateArray())
        {
            var s = item.GetString();
            if (!string.IsNullOrWhiteSpace(s)) list.Add(s);
        }
        return list;
    }

    public static async Task<InvoiceAnalysisResult> AnalyzeAsync(
        InvoiceAnalysisRequest request,
        OcrRuntimePaths? runtimeOverride = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        var runtime = runtimeOverride ?? OcrRuntimeLocator.Locate();
        if (!runtime.HasPython || !File.Exists(runtime.AnalystScript))
            throw new InvalidOperationException("InvoiceVision analyst runtime (Python / ai_analyst.py) is missing.");

        var workDir = Path.Combine(
            string.IsNullOrWhiteSpace(request.OutputPath) ? Path.GetTempPath() : Path.GetDirectoryName(Path.GetFullPath(request.OutputPath))!,
            "analyze_" + request.RequestId);
        Directory.CreateDirectory(workDir);
        var reqJsonPath = Path.Combine(workDir, "analysis_request.json");
        var outJsonPath = string.IsNullOrWhiteSpace(request.OutputPath)
            ? Path.Combine(workDir, "analysis_result.json")
            : Path.GetFullPath(request.OutputPath);
        if (File.Exists(outJsonPath)) File.Delete(outJsonPath);
        WriteJsonAtomically(reqJsonPath, request);

        var psi = new ProcessStartInfo(runtime.PythonExe)
        {
            WorkingDirectory = Path.GetDirectoryName(runtime.AnalystScript)!,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        psi.ArgumentList.Add("-u");
        psi.ArgumentList.Add(runtime.AnalystScript);
        psi.ArgumentList.Add("--input");
        psi.ArgumentList.Add(reqJsonPath);
        psi.ArgumentList.Add("--output");
        psi.ArgumentList.Add(outJsonPath);
        if (!string.IsNullOrWhiteSpace(request.MemoryDbPath))
        {
            psi.ArgumentList.Add("--memory-db");
            psi.ArgumentList.Add(Path.GetFullPath(request.MemoryDbPath));
        }
        if (runtime.HasLlamaServer)
        {
            psi.ArgumentList.Add("--llama-server");
            psi.ArgumentList.Add(runtime.LlamaServerExe);
        }
        if (File.Exists(runtime.QwenModel))
        {
            psi.ArgumentList.Add("--qwen-model");
            psi.ArgumentList.Add(runtime.QwenModel);
        }
        if (!request.UseLlm)
            psi.ArgumentList.Add("--no-llm");

        using var proc = new Process { StartInfo = psi };
        if (!proc.Start())
            throw new IOException("Failed to start offline AI analyst process.");

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeoutCts.CancelAfter(TimeSpan.FromSeconds(120));

        var outTask = proc.StandardOutput.ReadToEndAsync(timeoutCts.Token);
        var errTask = proc.StandardError.ReadToEndAsync(timeoutCts.Token);
        try
        {
            await Task.WhenAll(outTask, errTask, proc.WaitForExitAsync(timeoutCts.Token)).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try { if (!proc.HasExited) proc.Kill(entireProcessTree: true); } catch { }
            if (cancellationToken.IsCancellationRequested) throw;
            throw new TimeoutException("Offline AI analyst timed out after 120 seconds.");
        }

        var stderr = await errTask.ConfigureAwait(false);
        if (proc.ExitCode != 0 || !File.Exists(outJsonPath))
            throw new InvalidOperationException($"Offline AI analyst failed (exit {proc.ExitCode}): {stderr}");

        var json = await File.ReadAllTextAsync(outJsonPath, cancellationToken).ConfigureAwait(false);
        return JsonSerializer.Deserialize<InvoiceAnalysisResult>(json, JsonOptions)
            ?? throw new InvalidDataException("Empty or invalid analysis output JSON.");
    }
}
