using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Threading;
using InvoiceVisionChild.Contracts;
using InvoiceVisionChild.Core;
using WpfApp = System.Windows.Application;

namespace InvoiceVisionChild.App;

public sealed record LaunchOptions(
    string? ExtractRequestPath,
    string? AnalyzeRequestPath,
    bool SelfTest,
    string? SelfTestOutputPath,
    long ClientId,
    string ClientName,
    string ClientGstin,
    string FinancialYear,
    string ScanId,
    string? ResultPath,
    List<string> SourceFiles)
{
    public static LaunchOptions Parse(string[] args) => App.ParseArgs(args);
}

public partial class App : WpfApp
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };

    [STAThread]
    public static int Main(string[] args)
    {
        var opts = ParseArgs(args);

        // Headless CLI extraction route invoked by AAH Phone Link or CLI automation
        if (!string.IsNullOrWhiteSpace(opts.ExtractRequestPath))
            return RunHeadlessExtractAsync(opts.ExtractRequestPath).GetAwaiter().GetResult();

        if (!string.IsNullOrWhiteSpace(opts.AnalyzeRequestPath))
            return RunHeadlessAnalyzeAsync(opts.AnalyzeRequestPath).GetAwaiter().GetResult();

        var app = new App();
        app.InitializeComponent();
        app.ShutdownMode = ShutdownMode.OnMainWindowClose;

        var runtime = OcrRuntimeLocator.Locate();
        var window = new MainWindow(opts, runtime);

        if (opts.SelfTest)
        {
            if (string.IsNullOrWhiteSpace(opts.SelfTestOutputPath))
                throw new ArgumentException("--self-test requires --self-test-output PATH");

            window.Loaded += (_, _) => window.Dispatcher.BeginInvoke(new Action(() =>
            {
                try
                {
                    if (!window.IsLoaded || !window.IsVisible || PresentationSource.FromVisual(window) is null)
                        throw new InvalidOperationException("MainWindow did not render cleanly.");

                    var marker = runtime.IsReady
                        ? "SMOKE_OK|V2|VISIBLE_WINDOW|ENGINE_READY"
                        : "SMOKE_OK|V2|VISIBLE_WINDOW|ENGINE_MISSING_" + string.Join("+", runtime.GetMissingComponents());

                    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(opts.SelfTestOutputPath))!);
                    File.WriteAllText(opts.SelfTestOutputPath, marker);
                    app.Shutdown(0);
                }
                catch (Exception ex)
                {
                    try { File.WriteAllText(opts.SelfTestOutputPath!, "SMOKE_FAILED|" + ex.Message); } catch { }
                    app.Shutdown(2);
                }
            }), DispatcherPriority.ApplicationIdle);
        }

        return app.Run(window);
    }

    private static async Task<int> RunHeadlessExtractAsync(string requestPath)
    {
        InvoiceExtractionRequest? request = null;
        try
        {
            var fullReqPath = Path.GetFullPath(requestPath);
            if (!File.Exists(fullReqPath))
            {
                Console.Error.WriteLine($"Request file missing: {fullReqPath}");
                return 2;
            }

            var raw = await File.ReadAllTextAsync(fullReqPath).ConfigureAwait(false);
            request = JsonSerializer.Deserialize<InvoiceExtractionRequest>(raw, JsonOptions)
                ?? throw new InvalidDataException("Empty or invalid extraction request JSON.");

            // Support legacy Handoff field names seamlessly if present
            if (request.SourceFiles.Count == 0)
            {
                using var doc = JsonDocument.Parse(raw);
                if (doc.RootElement.TryGetProperty("sourceFiles", out var sf) && sf.ValueKind == JsonValueKind.Array)
                {
                    foreach (var el in sf.EnumerateArray())
                    {
                        if (el.ValueKind == JsonValueKind.String && el.GetString() is { Length: > 0 } p)
                            request.SourceFiles.Add(p);
                        else if (el.ValueKind == JsonValueKind.Object && el.TryGetProperty("path", out var po) && po.GetString() is { Length: > 0 } p2)
                            request.SourceFiles.Add(p2);
                    }
                }
                if (string.IsNullOrWhiteSpace(request.OutputPath) && doc.RootElement.TryGetProperty("responsePath", out var rp))
                    request.OutputPath = rp.GetString() ?? string.Empty;
                if (string.IsNullOrWhiteSpace(request.WorkDirectory) && doc.RootElement.TryGetProperty("outputDirectory", out var od))
                    request.WorkDirectory = od.GetString() ?? string.Empty;
            }

            if (string.IsNullOrWhiteSpace(request.OutputPath))
                request.OutputPath = Path.Combine(Path.GetDirectoryName(fullReqPath)!, "result.json");

            var result = await InvoiceExtractionOrchestrator.ExtractAsync(
                request,
                onProgress: (pct, msg) => Console.WriteLine($"PROGRESS|{pct}|{msg}")).ConfigureAwait(false);

            Console.WriteLine($"RESULT_OK|{request.OutputPath}|rows={result.Rows.Count}|total={result.InvoiceTotal:0.00}|balanced={result.Verification.IsBalanced}");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("EXTRACT_ERROR: " + ex);
            if (request is not null && !string.IsNullOrWhiteSpace(request.OutputPath))
            {
                try
                {
                    InvoiceExtractionOrchestrator.WriteJsonAtomically(request.OutputPath, new InvoiceExtractionResult
                    {
                        RequestId = request.RequestId,
                        ClientId = request.ClientId,
                        ClientCode = request.ClientCode,
                        FinancialYear = request.FinancialYear,
                        Status = "Failed",
                        DiagnosticsNote = ex.Message
                    });
                }
                catch { }
            }
            return 2;
        }
    }

    private static async Task<int> RunHeadlessAnalyzeAsync(string requestPath)
    {
        InvoiceAnalysisRequest? request = null;
        try
        {
            var fullReqPath = Path.GetFullPath(requestPath);
            if (!File.Exists(fullReqPath))
            {
                Console.Error.WriteLine($"Analysis request file missing: {fullReqPath}");
                return 2;
            }
            var raw = await File.ReadAllTextAsync(fullReqPath).ConfigureAwait(false);
            request = JsonSerializer.Deserialize<InvoiceAnalysisRequest>(raw, JsonOptions)
                ?? throw new InvalidDataException("Empty or invalid analysis request JSON.");
            if (string.IsNullOrWhiteSpace(request.OutputPath))
                request.OutputPath = Path.Combine(Path.GetDirectoryName(fullReqPath)!, "analysis_result.json");

            var result = await InvoiceExtractionOrchestrator.AnalyzeAsync(request).ConfigureAwait(false);
            Console.WriteLine($"ANALYSIS_OK|{request.OutputPath}|verdict={result.Verdict}|elapsed={result.ElapsedSec:0.0}s");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("ANALYZE_ERROR: " + ex);
            if (request is not null && !string.IsNullOrWhiteSpace(request.OutputPath))
            {
                try
                {
                    InvoiceExtractionOrchestrator.WriteJsonAtomically(request.OutputPath, new InvoiceAnalysisResult
                    {
                        Verdict = "Failed",
                        Summary = ex.Message
                    });
                }
                catch { }
            }
            return 2;
        }
    }

    public static LaunchOptions ParseArgs(string[] args)
    {
        string? extractPath = null;
        string? analyzePath = null;
        bool selfTest = false;
        string? selfTestOut = null;
        long clientId = 0;
        string clientName = string.Empty;
        string clientGstin = string.Empty;
        string fy = string.Empty;
        string scanId = string.Empty;
        string? resultPath = null;
        var sources = new List<string>();

        for (var i = 0; i < args.Length; i++)
        {
            var a = args[i];
            if ((a.Equals("--extract", StringComparison.OrdinalIgnoreCase) ||
                 a.Equals("--request", StringComparison.OrdinalIgnoreCase) ||
                 a.Equals("--aah-handoff", StringComparison.OrdinalIgnoreCase)) && i + 1 < args.Length)
                extractPath = args[++i];
            else if (a.Equals("--analyze", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                analyzePath = args[++i];
            else if (a.Equals("--self-test", StringComparison.OrdinalIgnoreCase))
                selfTest = true;
            else if (a.Equals("--self-test-output", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                selfTestOut = args[++i];
            else if (a.Equals("--client-id", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                long.TryParse(args[++i], out clientId);
            else if (a.Equals("--client-name", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                clientName = args[++i];
            else if (a.Equals("--client-gstin", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                clientGstin = args[++i];
            else if (a.Equals("--fy", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                fy = args[++i];
            else if (a.Equals("--scan-id", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                scanId = args[++i];
            else if ((a.Equals("--result", StringComparison.OrdinalIgnoreCase) || a.Equals("--stage1-archive", StringComparison.OrdinalIgnoreCase)) && i + 1 < args.Length)
                resultPath = args[++i];
            else if (a.Equals("--source", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
            {
                var p = args[++i];
                if (File.Exists(p) || Directory.Exists(p)) sources.Add(Path.GetFullPath(p));
            }
            else if (!a.StartsWith("--", StringComparison.Ordinal) && (File.Exists(a) || Directory.Exists(a)))
            {
                sources.Add(Path.GetFullPath(a));
            }
        }

        return new LaunchOptions(extractPath, analyzePath, selfTest, selfTestOut, clientId, clientName, clientGstin, fy, scanId, resultPath, sources);
    }
}
