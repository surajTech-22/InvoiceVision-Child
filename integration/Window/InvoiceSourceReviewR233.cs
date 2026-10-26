// R233 native review panel in the REAL InvoiceVision Child window.
// Source OCR is immutable. User annotations are stored separately in LocalAppData;
// this panel has no AAH/Tally access and never grants accounting approval.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace Aah.InvoiceVisionChild;

internal sealed partial class InvoiceVisionWindow
{
    private sealed class R233ReviewItem
    {
        internal string Id = "", Kind = "", OriginalText = "";
        internal int Count;
        public override string ToString() =>
            Kind.Replace('_',' ')+"  •  "+Count+" source lines  •  "+OriginalText[..Math.Min(55,OriginalText.Length)];
    }

    private readonly List<R233ReviewItem> _r233Queue = new();
    private readonly TextBlock _r233Summary = new() {
        Text="No source-linked rows loaded. Analyze a photograph to see review items.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,3,0,8) };
    private readonly ListBox _r233List = new() { Height=132,MinWidth=210 };
    private readonly TextBlock _r233Original = new() {
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,6,0,4),
        Text="Select a source item. Raw OCR is never overwritten." };
    private readonly TextBox _r233Correction = new() {
        MinHeight=38,MaxHeight=86,TextWrapping=TextWrapping.Wrap,
        AcceptsReturn=true,VerticalScrollBarVisibility=ScrollBarVisibility.Auto,
        MaxLength=350 };
    private string? _r233PhotoHash;
    private bool _r233NativePanelBuilt;

    private void AttachSourceReviewUiR233(StackPanel inspector)
    {
        if (_r233NativePanelBuilt) throw new InvalidOperationException("Review panel created twice.");
        var body=new StackPanel { Margin=new Thickness(5,5,5,6) };
        body.Children.Add(_r233Summary);
        body.Children.Add(_r233List);
        body.Children.Add(_r233Original);
        body.Children.Add(new TextBlock {
            Text="Correction (manual annotation only; not an approved field)",
            FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,6,0,4) });
        body.Children.Add(_r233Correction);
        var save=new Button {
            Content="Save private correction",
            Padding=new Thickness(7,5,7,5),Margin=new Thickness(0,7,0,4),
            MinHeight=30 };
        save.Click += (_,_) => SaveSourceAnnotationR233();
        body.Children.Add(save);
        body.Children.Add(new TextBlock {
            Text="Original OCR, source boxes and image stay unchanged. " +
                 "Corrections are local and cannot authorize accounting posting.",
            Foreground=Brushes.DimGray,TextWrapping=TextWrapping.Wrap });
        _r233List.SelectionChanged += (_,_) => {
            _r233Correction.Text="";
            var item=_r233List.SelectedItem as R233ReviewItem;
            _r233Original.Text=item is null
                ? "Select one source row/date flag"
                : item.Id+"\nOriginal OCR:\n"+item.OriginalText;
        };
        inspector.Children.Add(new Expander {
            Header="Source-linked OCR review (unverified)",
            IsExpanded=false,Content=body,
            Margin=new Thickness(0,6,0,4) });
        _r233NativePanelBuilt=true;
    }

    private static string R233GetString(JsonElement source,string name)
    {
        return source.ValueKind==JsonValueKind.Object &&
               source.TryGetProperty(name,out var part) &&
               part.ValueKind==JsonValueKind.String ? part.GetString()??"" : "";
    }

    private void LoadSourceReviewQueueR233(JsonElement analysis,string verifiedPhotoHash)
    {
        _r233Queue.Clear();
        _r233List.ItemsSource=null;
        _r233PhotoHash=null;
        _r233Correction.Text="";
        _r233Summary.Text="No source-linked OCR review for this analysis. All recognition remains unverified.";
        if (!_r233NativePanelBuilt ||
            !Regex.IsMatch(verifiedPhotoHash,@"\A[0-9a-fA-F]{64}\z") ||
            analysis.ValueKind!=JsonValueKind.Object ||
            !analysis.TryGetProperty("zone_refinement",out var refinement) ||
            refinement.ValueKind!=JsonValueKind.Object ||
            !refinement.TryGetProperty("source_row_and_date_review",out var source) ||
            source.ValueKind!=JsonValueKind.Object ||
            !source.TryGetProperty("manual_review_queue",out var queue) ||
            queue.ValueKind!=JsonValueKind.Object)
            return;
        if(R233GetString(queue,"status")!="IMMUTABLE_SOURCE_REVIEW_REQUIRED" ||
           !queue.TryGetProperty("posting_eligible",out var post) ||
           post.ValueKind!=JsonValueKind.False ||
           !queue.TryGetProperty("release_approved",out var release) ||
           release.ValueKind!=JsonValueKind.False ||
           !queue.TryGetProperty("items",out var items) || items.ValueKind!=JsonValueKind.Array)
        {
            _r233Summary.Text="Review queue unavailable or unsafe. No values have been accepted.";
            return;
        }
        var loaded=new List<R233ReviewItem>();
        var ids=new HashSet<string>(StringComparer.Ordinal);
        foreach(var sourceItem in items.EnumerateArray())
        {
            if(loaded.Count>=500) { loaded.Clear();break; }
            var id=R233GetString(sourceItem,"review_id");
            var kind=R233GetString(sourceItem,"review_kind");
            var decodedHash=R233GetString(sourceItem,"source_frame_sha256");
            if(!Regex.IsMatch(id,@"\AIVR231-[0-9a-f]{24}\z") ||
               !Regex.IsMatch(decodedHash,@"\A[0-9a-f]{64}\z") ||
               kind is not ("ITEM_ROW_BASELINE" or "ITEM_ROW_SIDEWAYS" or
                            "ITEM_ROW_HSN_ANCHOR" or "DATE_ANOMALY") ||
               !ids.Add(id) ||
               !sourceItem.TryGetProperty("review_required",out var need) ||
               need.ValueKind!=JsonValueKind.True ||
               !sourceItem.TryGetProperty("posting_eligible",out var eligible) ||
               eligible.ValueKind!=JsonValueKind.False ||
               !sourceItem.TryGetProperty("original_observations",out var obs) ||
               obs.ValueKind!=JsonValueKind.Array)
            { loaded.Clear();break; }
            var originals=new List<string>();
            foreach(var token in obs.EnumerateArray())
            {
                var text=R233GetString(token,"original_ocr_text");
                if(string.IsNullOrWhiteSpace(text) || text.Length>1024 ||
                   !token.TryGetProperty("original_box",out var bounds) ||
                   bounds.ValueKind!=JsonValueKind.Array || bounds.GetArrayLength()!=4)
                { loaded.Clear();break; }
                originals.Add(text);
            }
            if(originals.Count==0 || originals.Count>40 || loaded.Count!=ids.Count-1)
            { loaded.Clear();break; }
            loaded.Add(new R233ReviewItem {
                Id=id,Kind=kind,Count=originals.Count,
                OriginalText=string.Join(" | ",originals)[..Math.Min(1200,string.Join(" | ",originals).Length)]
            });
        }
        if(loaded.Count!=items.GetArrayLength())
        {
            _r233Summary.Text="Unsafe or malformed OCR review items rejected. No corrections loaded.";
            return;
        }
        _r233Queue.AddRange(loaded);
        _r233PhotoHash=verifiedPhotoHash.ToLowerInvariant();
        _r233List.ItemsSource=_r233Queue;
        _r233Summary.Text=loaded.Count+" original-source item/date flags • " +
                          "not accuracy-certified • select one to inspect and annotate";
    }

    private void SaveSourceAnnotationR233()
    {
        var item=_r233List.SelectedItem as R233ReviewItem;
        var correction=_r233Correction.Text.Trim();
        if(_r233PhotoHash is null || item is null ||
           !Regex.IsMatch(item.Id,@"\AIVR231-[0-9a-f]{24}\z") ||
           correction.Length==0 || correction.Length>350 ||
           _zonePhotoPath is null || !File.Exists(_zonePhotoPath) ||
           !string.Equals(
               Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(_zonePhotoPath))),
               _r233PhotoHash,StringComparison.OrdinalIgnoreCase))
        {
            MessageBox.Show("Select a valid source item and type a correction. " +
                            "The exact original photograph must still be present.",
                            "Source review — not saved",MessageBoxButton.OK,MessageBoxImage.Warning);
            return;
        }
        try
        {
            var directory=Path.Combine(_stateDir,"SourceReviewAnnotations",_r233PhotoHash);
            Directory.CreateDirectory(directory);
            var filename=Path.Combine(directory,item.Id+".json");
            var payload=JsonSerializer.Serialize(new {
                schema_version=1,
                exact_original_photo_sha256=_r233PhotoHash,
                original_decoded_review_id=item.Id,
                kind=item.Kind,
                original_ocr_excerpt=item.OriginalText,
                reviewer_correction=correction,
                review_status="LOCAL_ANNOTATION_NOT_FIELD_APPROVAL",
                accounting_write_permitted=false,
                ocr_source_modified=false,
                approved_for_posting=false,
                recorded_utc=DateTime.UtcNow.ToString("O")
            },new JsonSerializerOptions { WriteIndented=true });
            var temp=filename+"."+Guid.NewGuid().ToString("N")+".tmp";
            try {
                File.WriteAllText(temp,payload);
                File.Move(temp,filename,true);
            } finally { if(File.Exists(temp)) File.Delete(temp); }
            _r233Summary.Text="Annotation saved in local Child data for "+item.Id+
                ". Original OCR unchanged; accounting transfer remains disabled.";
        }
        catch(Exception ex)
        {
            MessageBox.Show("Correction could not be saved: "+ex.Message,
                "Source review error",MessageBoxButton.OK,MessageBoxImage.Error);
        }
    }

    internal void AssertR233NativeReviewReadyForInstaller()
    {
        if(!_r233NativePanelBuilt || _r233List is null ||
           _r233Summary is null || _r233Correction.MaxLength!=350)
            throw new InvalidOperationException("R233 native source-linked review UI missing.");
    }
}
