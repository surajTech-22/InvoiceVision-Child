// R241: choose only a complete isolated OCR runtime supplied alongside Child.
// Never download software, change PATH globally, modify AAH environments,
// replace installed Python, or infer that having python.exe proves models exist.
using System;
using System.Diagnostics;
using System.IO;

namespace Aah.InvoiceVisionChild;

internal static class InvoiceChildBundledRuntimeR241
{
    internal static string? PythonExecutable
    {
        get
        {
            var root = Path.Combine(AppContext.BaseDirectory, "Runtime");
            var python = Path.Combine(root, "Python", "python.exe");
            var tesseract = Path.Combine(root, "Tesseract", "tesseract.exe");
            var trained = Path.Combine(root, "Tesseract", "tessdata", "eng.traineddata");
            return File.Exists(python) && File.Exists(tesseract) && File.Exists(trained)
                ? python : null;
        }
    }

    internal static bool Configure(ProcessStartInfo start)
    {
        var root = Path.Combine(AppContext.BaseDirectory, "Runtime");
        var python = PythonExecutable;
        if (python is null) return false;
        var tess = Path.Combine(root, "Tesseract", "tesseract.exe");
        var data = Path.Combine(root, "Tesseract", "tessdata");
        // Explicit child-process environment only; not the parent OS or AAH.
        // TESSDATA_PREFIX can be either tessdata or its parent depending on
        // Tesseract revision. Passing the parent is supported by Windows builds.
        start.Environment["TESSERACT_EXE"] = tess;
        start.Environment["TESSDATA_PREFIX"] = data;
        start.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        start.Environment["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True";
        return true;
    }

    internal static void AssertRuntimeCompleteOrAbsent()
    {
        var root = Path.Combine(AppContext.BaseDirectory, "Runtime");
        if (!Directory.Exists(root)) return;
        if (PythonExecutable is null)
            throw new InvalidDataException(
                "Bundled OCR Runtime folder is incomplete. No invoice OCR or update may proceed.");
    }
}
