using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using InvoiceVisionChild.Contracts;
using InvoiceVisionChild.Core;
using Microsoft.Win32;
using MediaColor = System.Windows.Media.Color;

namespace InvoiceVisionChild.App;

public partial class MainWindow : Window
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true
    };

    private static readonly HashSet<string> SupportedExts = new(StringComparer.OrdinalIgnoreCase)
    {
        ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".pdf"
    };

    private readonly LaunchOptions _launch;
    private readonly OcrRuntimePaths _runtime;
    private readonly List<string> _sourceFiles = [];
    private readonly ObservableCollection<InvoiceLineItem> _rows = [];
    private readonly ObservableCollection<InvoiceGstSlab> _slabs = [];

    private InvoiceExtractionResult _currentResult = new();
    private CancellationTokenSource? _runCts;
    private bool _suppressFieldEvents;
    private string? _lastSavedResultPath;

    public MainWindow(LaunchOptions launch, OcrRuntimePaths runtime)
    {
        InitializeComponent();
        _launch = launch;
        _runtime = runtime;
        _lastSavedResultPath = launch.ResultPath;

        RowsGrid.ItemsSource = _rows;
        SlabsGrid.ItemsSource = _slabs;

        RuntimeBadgeText.Text = _runtime.Summary;
        RuntimeBadgeText.Foreground = _runtime.IsReady
            ? new SolidColorBrush(MediaColor.FromRgb(21, 128, 61))
            : new SolidColorBrush(MediaColor.FromRgb(185, 28, 28));

        if (_launch.ClientId > 0 || !string.IsNullOrWhiteSpace(_launch.FinancialYear))
        {
            ClientContextBadge.Text = $"AAH Client #{_launch.ClientId} · {_launch.FinancialYear}" +
                (string.IsNullOrWhiteSpace(_launch.ScanId) ? "" : $" · Scan {_launch.ScanId}");
        }

        foreach (var src in _launch.SourceFiles)
        {
            if (Directory.Exists(src)) AddDirectoryFiles(src);
            else if (File.Exists(src) && SupportedExts.Contains(Path.GetExtension(src))) _sourceFiles.Add(src);
        }
        RefreshInputSelector();

        if (!string.IsNullOrWhiteSpace(_launch.ResultPath) && File.Exists(_launch.ResultPath))
        {
            TryLoadExistingResult(_launch.ResultPath);
        }

        Closing += (_, _) => _runCts?.Cancel();
    }

    private void TryLoadExistingResult(string path)
    {
        try
        {
            var raw = File.ReadAllText(path);
            var parsed = JsonSerializer.Deserialize<InvoiceExtractionResult>(raw, JsonOptions);
            if (parsed is not null)
            {
                InvoiceMathVerifier.Verify(parsed);
                BindResult(parsed);
                StatusFooterText.Text = "Loaded existing AAH extraction result for review.";
            }
        }
        catch (Exception ex)
        {
            StatusFooterText.Text = "Could not load existing result: " + ex.Message;
        }
    }

    private void RefreshInputSelector()
    {
        var previous = InputSelector.SelectedIndex;
        InputSelector.Items.Clear();
        foreach (var f in _sourceFiles) InputSelector.Items.Add(Path.GetFileName(f));
        if (_sourceFiles.Count > 0)
            InputSelector.SelectedIndex = previous >= 0 && previous < _sourceFiles.Count ? previous : 0;
        else
            ClearImagePreview();
    }

    private void AddFiles_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFileDialog
        {
            Title = "Select invoice photos or PDFs",
            Multiselect = true,
            Filter = "Invoices (*.jpg;*.jpeg;*.png;*.pdf;*.bmp;*.tif;*.tiff;*.webp)|*.jpg;*.jpeg;*.png;*.pdf;*.bmp;*.tif;*.tiff;*.webp|All files (*.*)|*.*"
        };
        if (dlg.ShowDialog(this) != true) return;
        foreach (var f in dlg.FileNames)
            if (!_sourceFiles.Contains(f, StringComparer.OrdinalIgnoreCase)) _sourceFiles.Add(f);
        RefreshInputSelector();
    }

    private void AddFolder_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new OpenFolderDialog
        {
            Title = "Select folder containing invoice images/PDFs",
            Multiselect = false
        };
        if (dlg.ShowDialog(this) != true || string.IsNullOrWhiteSpace(dlg.FolderName)) return;
        AddDirectoryFiles(dlg.FolderName);
        RefreshInputSelector();
    }

    private void AddDirectoryFiles(string dir)
    {
        foreach (var f in Directory.EnumerateFiles(dir, "*.*", SearchOption.TopDirectoryOnly).OrderBy(x => x))
            if (SupportedExts.Contains(Path.GetExtension(f)) && !_sourceFiles.Contains(f, StringComparer.OrdinalIgnoreCase))
                _sourceFiles.Add(f);
    }

    private async void RunHybrid_Click(object sender, RoutedEventArgs e) => await RunExtractionAsync("hybrid");
    private async void RunFast_Click(object sender, RoutedEventArgs e) => await RunExtractionAsync("fast");

    private void CancelRun_Click(object sender, RoutedEventArgs e)
    {
        _runCts?.Cancel();
        StatusFooterText.Text = "Cancelling OCR worker...";
    }

    private async Task RunExtractionAsync(string mode)
    {
        if (_sourceFiles.Count == 0)
        {
            System.Windows.MessageBox.Show(this, "Add an invoice image or PDF first.", "InvoiceVision Child v2", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        if (!_runtime.IsReady)
        {
            System.Windows.MessageBox.Show(this, _runtime.Summary, "Runtime Missing", MessageBoxButton.OK, MessageBoxImage.Error);
            return;
        }

        _runCts?.Cancel();
        _runCts = new CancellationTokenSource();
        SetBusy(true);
        try
        {
            var req = new InvoiceExtractionRequest
            {
                RequestId = Guid.NewGuid().ToString("N"),
                ClientId = _launch.ClientId,
                ClientName = _launch.ClientName,
                ClientGstin = _launch.ClientGstin,
                FinancialYear = _launch.FinancialYear,
                ScanId = _launch.ScanId,
                Mode = mode,
                SourceFiles = _sourceFiles.ToList(),
                OutputPath = _lastSavedResultPath ?? string.Empty
            };

            var result = await InvoiceExtractionOrchestrator.ExtractAsync(
                req,
                _runtime,
                (pct, msg) => Dispatcher.BeginInvoke(() =>
                {
                    WorkProgressBar.Value = Math.Clamp(pct, 0, 100);
                    StatusFooterText.Text = msg;
                }),
                _runCts.Token);

            BindResult(result);
            ShowSelectedPreview();
            StatusFooterText.Text = $"Extracted {result.Rows.Count} item(s) in {result.ElapsedSeconds:0.0}s ({result.EngineUsed}).";
        }
        catch (OperationCanceledException)
        {
            StatusFooterText.Text = "Extraction cancelled.";
        }
        catch (Exception ex)
        {
            StatusFooterText.Text = "Extraction failed: " + ex.Message;
            System.Windows.MessageBox.Show(this, ex.Message, "Extraction Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private void SetBusy(bool busy)
    {
        RunHybridBtn.IsEnabled = !busy;
        RunFastBtn.IsEnabled = !busy;
        SaveResultBtn.IsEnabled = !busy;
        CancelRunBtn.IsEnabled = busy;
        if (!busy) WorkProgressBar.Value = 0;
    }

    private void BindResult(InvoiceExtractionResult result)
    {
        _currentResult = result;
        _suppressFieldEvents = true;
        try
        {
            SellerNameBox.Text = result.Seller.Name;
            SellerGstinBox.Text = result.Seller.Gstin;
            BuyerNameBox.Text = result.Buyer.Name;
            BuyerGstinBox.Text = result.Buyer.Gstin;
            InvoiceNoBox.Text = result.InvoiceNumber;
            InvoiceDateBox.Text = result.InvoiceDate;
            DocTypeBox.Text = result.DocumentType;
            PosBox.Text = result.PlaceOfSupply;
            TaxableTotalBox.Text = result.TaxableTotal.ToString("0.00", CultureInfo.InvariantCulture);
            CgstTotalBox.Text = result.CgstTotal.ToString("0.00", CultureInfo.InvariantCulture);
            SgstTotalBox.Text = result.SgstTotal.ToString("0.00", CultureInfo.InvariantCulture);
            IgstTotalBox.Text = result.IgstTotal.ToString("0.00", CultureInfo.InvariantCulture);
            CreditNoteBox.Text = result.CreditNoteTotal.ToString("0.00", CultureInfo.InvariantCulture);
            RoundOffBox.Text = result.RoundOff.ToString("0.00", CultureInfo.InvariantCulture);
            InvoiceTotalBox.Text = result.InvoiceTotal.ToString("0.00", CultureInfo.InvariantCulture);

            foreach (ComboBoxItem item in DirectionBox.Items)
            {
                if (string.Equals(item.Content?.ToString(), result.Direction, StringComparison.OrdinalIgnoreCase))
                {
                    DirectionBox.SelectedItem = item;
                    break;
                }
            }

            _rows.Clear();
            foreach (var r in result.Rows) _rows.Add(r);

            RefreshComputedDisplays();

            RawOcrTextBox.Text = result.RawOcrText;
            QrTextBox.Text = result.QrEvidence is { Detected: true } qr
                ? $"NIC e-Invoice QR Detected\nIRN: {qr.Irn}\nSeller GSTIN: {qr.SellerGstin}\nBuyer GSTIN: {qr.BuyerGstin}\nDoc No: {qr.DocNo} | Date: {qr.DocDate}\nTotal: {qr.TotalValue:N2} | Items: {qr.ItemCount}"
                : "No signed NIC GST e-Invoice QR detected on the source pages (UPI QRs are ignored).";
            EngineBadgeText.Text = string.IsNullOrWhiteSpace(result.EngineUsed)
                ? ""
                : $"{result.EngineUsed} · {result.ElapsedSeconds:0.0}s";
        }
        finally
        {
            _suppressFieldEvents = false;
        }
    }

    private void RefreshComputedDisplays()
    {
        _slabs.Clear();
        foreach (var s in _currentResult.GstSlabs) _slabs.Add(s);

        var sgOk = GstChecksumValidator.IsValidGstin(_currentResult.Seller.Gstin);
        SellerGstinStateText.Text = string.IsNullOrWhiteSpace(_currentResult.Seller.Gstin)
            ? ""
            : (sgOk ? $"✓ {GstChecksumValidator.TryGetStateName(_currentResult.Seller.Gstin)}" : "✗ Bad checksum");
        SellerGstinStateText.Foreground = sgOk
            ? new SolidColorBrush(MediaColor.FromRgb(21, 128, 61))
            : new SolidColorBrush(MediaColor.FromRgb(185, 28, 28));

        var bgOk = GstChecksumValidator.IsValidGstin(_currentResult.Buyer.Gstin);
        BuyerGstinStateText.Text = string.IsNullOrWhiteSpace(_currentResult.Buyer.Gstin)
            ? ""
            : (bgOk ? $"✓ {GstChecksumValidator.TryGetStateName(_currentResult.Buyer.Gstin)}" : "✗ Bad checksum");
        BuyerGstinStateText.Foreground = bgOk
            ? new SolidColorBrush(MediaColor.FromRgb(21, 128, 61))
            : new SolidColorBrush(MediaColor.FromRgb(185, 28, 28));

        var v = _currentResult.Verification;
        if (v.IsBalanced && v.Errors.Count == 0)
        {
            VerifyBanner.Background = new SolidColorBrush(MediaColor.FromRgb(236, 253, 245));
            VerifyBannerText.Foreground = new SolidColorBrush(MediaColor.FromRgb(6, 95, 70));
            VerifyBannerText.Text = $"✓ Verified · Score {v.Score}/100 · All GSTIN & GST accounting math balanced ({_currentResult.InvoiceTotal:N2})";
        }
        else if (v.Errors.Count == 0)
        {
            VerifyBanner.Background = new SolidColorBrush(MediaColor.FromRgb(255, 251, 235));
            VerifyBannerText.Foreground = new SolidColorBrush(MediaColor.FromRgb(146, 64, 14));
            VerifyBannerText.Text = $"Review ({v.Score}/100): " + string.Join(" · ", v.Warnings.Take(3));
        }
        else
        {
            VerifyBanner.Background = new SolidColorBrush(MediaColor.FromRgb(254, 242, 242));
            VerifyBannerText.Foreground = new SolidColorBrush(MediaColor.FromRgb(153, 27, 27));
            VerifyBannerText.Text = $"Action Required ({v.Score}/100): " + string.Join(" · ", v.Errors.Take(3));
        }

        var sb = new StringBuilder();
        foreach (var e in v.Errors) sb.AppendLine("[ERROR] " + e);
        foreach (var w in v.Warnings) sb.AppendLine("[WARN]  " + w);
        foreach (var p in v.PassedChecks) sb.AppendLine("[PASS]  " + p);
        ChecksTextBox.Text = sb.ToString();
    }

    private void SyncControlsToResultAndReverify()
    {
        if (_suppressFieldEvents || !IsLoaded) return;
        _currentResult.Seller.Name = SellerNameBox.Text.Trim();
        _currentResult.Seller.Gstin = SellerGstinBox.Text.Trim();
        _currentResult.Buyer.Name = BuyerNameBox.Text.Trim();
        _currentResult.Buyer.Gstin = BuyerGstinBox.Text.Trim();
        _currentResult.InvoiceNumber = InvoiceNoBox.Text.Trim();
        _currentResult.InvoiceDate = InvoiceDateBox.Text.Trim();
        _currentResult.DocumentType = DocTypeBox.Text.Trim();
        _currentResult.PlaceOfSupply = PosBox.Text.Trim();
        _currentResult.Direction = (DirectionBox.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? _currentResult.Direction;
        _currentResult.TaxableTotal = ParseDec(TaxableTotalBox.Text);
        _currentResult.CgstTotal = ParseDec(CgstTotalBox.Text);
        _currentResult.SgstTotal = ParseDec(SgstTotalBox.Text);
        _currentResult.IgstTotal = ParseDec(IgstTotalBox.Text);
        _currentResult.CreditNoteTotal = ParseDec(CreditNoteBox.Text);
        _currentResult.RoundOff = ParseDec(RoundOffBox.Text);
        _currentResult.InvoiceTotal = ParseDec(InvoiceTotalBox.Text);
        _currentResult.Rows = _rows.ToList();

        InvoiceMathVerifier.Verify(_currentResult);
        RowsGrid.Items.Refresh();
        RefreshComputedDisplays();
    }

    private static decimal ParseDec(string? s) =>
        decimal.TryParse(s?.Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var d) ? d : 0m;

    private void EditableHeader_Changed(object sender, TextChangedEventArgs e) => SyncControlsToResultAndReverify();
    private void DirectionBox_SelectionChanged(object sender, SelectionChangedEventArgs e) => SyncControlsToResultAndReverify();
    private void Reaudit_Click(object sender, RoutedEventArgs e) => SyncControlsToResultAndReverify();

    private void RowsGrid_CellEditEnding(object? sender, DataGridCellEditEndingEventArgs e) =>
        Dispatcher.BeginInvoke(SyncControlsToResultAndReverify);

    private void AddRow_Click(object sender, RoutedEventArgs e)
    {
        _rows.Add(new InvoiceLineItem { LineNumber = _rows.Count + 1 });
        SyncControlsToResultAndReverify();
    }

    private void DeleteRow_Click(object sender, RoutedEventArgs e)
    {
        if (RowsGrid.SelectedItem is InvoiceLineItem item)
        {
            _rows.Remove(item);
            SyncControlsToResultAndReverify();
        }
    }

    private void SaveResult_Click(object sender, RoutedEventArgs e)
    {
        SyncControlsToResultAndReverify();
        var target = _lastSavedResultPath;
        if (string.IsNullOrWhiteSpace(target))
        {
            var dlg = new SaveFileDialog
            {
                Title = "Save verified InvoiceVision JSON",
                Filter = "JSON files (*.json)|*.json",
                FileName = string.IsNullOrWhiteSpace(_currentResult.InvoiceNumber)
                    ? "invoice_result.json"
                    : $"invoice_{_currentResult.InvoiceNumber.Replace('/', '_')}.json"
            };
            if (dlg.ShowDialog(this) != true) return;
            target = dlg.FileName;
        }
        _currentResult.UserApproved = true;
        InvoiceExtractionOrchestrator.WriteJsonAtomically(target, _currentResult);
        _lastSavedResultPath = target;
        StatusFooterText.Text = "Saved verified JSON: " + target;
    }

    private void InputSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!IsLoaded) return;
        ImageRotateTransform.Angle = 0;
        ShowSelectedPreview();
    }

    private void PageViewSelector_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!IsLoaded) return;
        ShowSelectedPreview();
    }

    private void RotateLeft_Click(object sender, RoutedEventArgs e) => ImageRotateTransform.Angle = (ImageRotateTransform.Angle + 270) % 360;
    private void RotateRight_Click(object sender, RoutedEventArgs e) => ImageRotateTransform.Angle = (ImageRotateTransform.Angle + 90) % 360;

    private void ZoomMode_Changed(object sender, RoutedEventArgs e)
    {
        if (PreviewImage is null) return;
        if (ActualViewRadio.IsChecked == true)
        {
            PreviewImage.Stretch = Stretch.None;
            PreviewImage.HorizontalAlignment = System.Windows.HorizontalAlignment.Left;
            PreviewImage.VerticalAlignment = System.Windows.VerticalAlignment.Top;
        }
        else
        {
            PreviewImage.Stretch = Stretch.Uniform;
            PreviewImage.HorizontalAlignment = System.Windows.HorizontalAlignment.Center;
            PreviewImage.VerticalAlignment = System.Windows.VerticalAlignment.Center;
        }
    }

    private void ClearImagePreview()
    {
        if (PreviewImage is null || NoImageHint is null || ImageMetaText is null) return;
        PreviewImage.Source = null;
        NoImageHint.Visibility = Visibility.Visible;
        ImageMetaText.Text = "No file selected";
    }

    private void ShowSelectedPreview()
    {
        if (InputSelector is null || PreviewImage is null || PageViewSelector is null) return;
        var idx = InputSelector.SelectedIndex;
        if (idx < 0 || idx >= _sourceFiles.Count)
        {
            ClearImagePreview();
            return;
        }

        string path = _sourceFiles[idx];
        var wantDewarped = PageViewSelector.SelectedIndex == 1;
        if (wantDewarped && idx < _currentResult.PreprocessedPageImages.Count && File.Exists(_currentResult.PreprocessedPageImages[idx]))
            path = _currentResult.PreprocessedPageImages[idx];
        else if (Path.GetExtension(path).Equals(".pdf", StringComparison.OrdinalIgnoreCase) &&
                 idx < _currentResult.RenderedPageImages.Count && File.Exists(_currentResult.RenderedPageImages[idx]))
            path = _currentResult.RenderedPageImages[idx];

        if (!File.Exists(path) || Path.GetExtension(path).Equals(".pdf", StringComparison.OrdinalIgnoreCase))
        {
            PreviewImage.Source = null;
            NoImageHint.Text = Path.GetFileName(path) + " (PDF page preview renders during Extract)";
            NoImageHint.Visibility = Visibility.Visible;
            ImageMetaText.Text = Path.GetFileName(path);
            return;
        }

        try
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.UriSource = new Uri(path, UriKind.Absolute);
            bmp.EndInit();
            bmp.Freeze();
            PreviewImage.Source = bmp;
            NoImageHint.Visibility = Visibility.Collapsed;
            ImageMetaText.Text = $"{bmp.PixelWidth}×{bmp.PixelHeight} px · {Path.GetFileName(path)}";
        }
        catch (Exception ex)
        {
            PreviewImage.Source = null;
            NoImageHint.Text = "Image preview error: " + ex.Message;
            NoImageHint.Visibility = Visibility.Visible;
        }
    }
}
