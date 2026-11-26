namespace InvoiceVisionChild.Core;

public sealed class OcrRuntimePaths
{
    public string AppRoot { get; init; } = string.Empty;
    public string WorkerScript { get; init; } = string.Empty;
    public string AnalystScript { get; init; } = string.Empty;
    public string PythonExe { get; init; } = string.Empty;
    public string LlamaServerExe { get; init; } = string.Empty;
    public string LightOnModel { get; init; } = string.Empty;
    public string LightOnMmproj { get; init; } = string.Empty;
    public string QwenModel { get; init; } = string.Empty;
    public string QwenMmproj { get; init; } = string.Empty;
    public string PaddleXCacheDir { get; init; } = string.Empty;

    public bool HasPython => File.Exists(PythonExe);
    public bool HasWorker => File.Exists(WorkerScript);
    public bool HasLlamaServer => File.Exists(LlamaServerExe);
    public bool HasLightOn => File.Exists(LightOnModel) && File.Exists(LightOnMmproj);
    public bool HasQwenHybrid => File.Exists(QwenModel) && File.Exists(QwenMmproj);
    public bool IsReady => HasPython && HasWorker && HasLlamaServer && HasLightOn;

    public string Summary => IsReady
        ? (HasQwenHybrid
            ? "LightOnOCR-2-1B + Qwen3-VL-4B Hybrid Ready"
            : "LightOnOCR-2-1B Primary Ready")
        : "Runtime incomplete: " + string.Join(", ", GetMissingComponents());

    public IReadOnlyList<string> GetMissingComponents()
    {
        var missing = new List<string>();
        if (!HasWorker) missing.Add("Engine/extract_worker.py");
        if (!HasPython) missing.Add("Runtime/venv Python");
        if (!HasLlamaServer) missing.Add("llama-server.exe");
        if (!File.Exists(LightOnModel)) missing.Add("LightOnOCR-2-1B-Q8_0.gguf");
        if (!File.Exists(LightOnMmproj)) missing.Add("mmproj-LightOnOCR-2-1B-f16.gguf");
        return missing;
    }
}

public static class OcrRuntimeLocator
{
    public const string DefaultInstallDir = @"C:\AccountingAutomationHub\InvoiceVisionChild";

    public static OcrRuntimePaths Locate(string? baseDirectoryOverride = null)
    {
        var baseDir = string.IsNullOrWhiteSpace(baseDirectoryOverride) ? AppContext.BaseDirectory : baseDirectoryOverride;
        var roots = BuildCandidateRoots(baseDir);

        var worker = FirstExistingFile(roots,
            ["Engine", "extract_worker.py"],
            ["engine", "extract_worker.py"]);

        var analyst = FirstExistingFile(roots,
            ["Engine", "ai_analyst.py"],
            ["engine", "ai_analyst.py"]);

        var envPy = Environment.GetEnvironmentVariable("AAH_INVOICEVISION_PYTHON");
        var pythonCandidates = new List<string>();
        if (!string.IsNullOrWhiteSpace(envPy)) pythonCandidates.Add(envPy);
        foreach (var r in roots)
        {
            pythonCandidates.Add(Path.Combine(r, "Runtime", "venv", "Scripts", "python.exe"));
            pythonCandidates.Add(Path.Combine(r, ".venv", "Scripts", "python.exe"));
        }
        var pythonExe = pythonCandidates.FirstOrDefault(File.Exists) ?? Path.Combine(baseDir, "Runtime", "venv", "Scripts", "python.exe");

        var llamaServer = FirstExistingFile(roots,
            ["Runtime", "llama_bin", "llama-server.exe"],
            ["llama_bin", "llama-server.exe"]);

        var lightOnModel = FirstExistingFile(roots,
            ["Runtime", "models", "lightonocr-2-1b", "LightOnOCR-2-1B-Q8_0.gguf"],
            ["models", "lightonocr-2-1b", "LightOnOCR-2-1B-Q8_0.gguf"]);

        var lightOnMmproj = FirstExistingFile(roots,
            ["Runtime", "models", "lightonocr-2-1b", "mmproj-LightOnOCR-2-1B-f16.gguf"],
            ["models", "lightonocr-2-1b", "mmproj-LightOnOCR-2-1B-f16.gguf"]);

        var qwenModel = FirstExistingFile(roots,
            ["Runtime", "models", "qwen3-vl-4b", "Qwen3VL-4B-Instruct-Q4_K_M.gguf"],
            ["models", "qwen3-vl-4b", "Qwen3VL-4B-Instruct-Q4_K_M.gguf"]);

        var qwenMmproj = FirstExistingFile(roots,
            ["Runtime", "models", "qwen3-vl-4b", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"],
            ["models", "qwen3-vl-4b", "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"]);

        var paddleCache = FirstExistingDirectory(roots,
            ["Runtime", "paddlex"],
            ["cache", "paddlex"]);

        return new OcrRuntimePaths
        {
            AppRoot = baseDir,
            WorkerScript = worker,
            AnalystScript = analyst,
            PythonExe = pythonExe,
            LlamaServerExe = llamaServer,
            LightOnModel = lightOnModel,
            LightOnMmproj = lightOnMmproj,
            QwenModel = qwenModel,
            QwenMmproj = qwenMmproj,
            PaddleXCacheDir = paddleCache
        };
    }

    private static List<string> BuildCandidateRoots(string baseDir)
    {
        var roots = new List<string>();
        void Add(string? p)
        {
            if (string.IsNullOrWhiteSpace(p)) return;
            var full = Path.GetFullPath(p);
            if (!roots.Contains(full, StringComparer.OrdinalIgnoreCase))
                roots.Add(full);
        }

        Add(baseDir);
        Add(DefaultInstallDir);

        var dir = new DirectoryInfo(baseDir);
        for (var i = 0; i < 6 && dir is not null; i++)
        {
            Add(dir.FullName);
            var siblingLab = Path.Combine(dir.FullName, "InvoiceOcrLab");
            if (Directory.Exists(siblingLab)) Add(siblingLab);
            dir = dir.Parent;
        }
        return roots;
    }

    private static string FirstExistingFile(List<string> roots, params string[][] relSegments)
    {
        foreach (var root in roots)
        {
            foreach (var seg in relSegments)
            {
                var p = Path.Combine([root, .. seg]);
                if (File.Exists(p)) return p;
            }
        }
        return Path.Combine([roots[0], .. relSegments[0]]);
    }

    private static string FirstExistingDirectory(List<string> roots, params string[][] relSegments)
    {
        foreach (var root in roots)
        {
            foreach (var seg in relSegments)
            {
                var p = Path.Combine([root, .. seg]);
                if (Directory.Exists(p)) return p;
            }
        }
        return Path.Combine([roots[0], .. relSegments[0]]);
    }
}
