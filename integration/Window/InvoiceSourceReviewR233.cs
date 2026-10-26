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
    private readonly TextBlock _r235FieldWarnings=new() {
        Text="No independent field-consistency checks loaded. Recognition is unverified.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,4,0,7),
        Foreground=System.Windows.Media.Brushes.DarkRed };
    private readonly TextBlock _r237SourceSplitCandidates=new() {
        Text="No original-source split-field review available.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,4,0,8),
        Foreground=System.Windows.Media.Brushes.DarkGoldenrod };
    private readonly TextBlock _r238QrStatus=new() {
        Text="QR invoice cross-check not loaded.",
        TextWrapping=TextWrapping.Wrap,
        Margin=new Thickness(0,4,0,8),
        Foreground=System.Windows.Media.Brushes.DarkGoldenrod };
    private readonly TextBlock _r239GstinReview=new() {
        Text="GSTIN OCR check digit has not been checked.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,4,0,8),
        Foreground=System.Windows.Media.Brushes.DarkGoldenrod };
    private readonly TextBlock _r243AlternativeOcr=new() {
        Text="No high-resolution alternate OCR evidence loaded.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,5,0,8),
        Foreground=System.Windows.Media.Brushes.DimGray };
    private readonly TextBlock _r244LowConfidence=new() {
        Text="No low-confidence source-token crop rereads available.",
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,4,0,8),
        Foreground=System.Windows.Media.Brushes.DarkGoldenrod };
    private readonly System.Windows.Controls.ListBox _r233List = new() { Height=132,MinWidth=210 };
    private readonly TextBlock _r233Original = new() {
        TextWrapping=TextWrapping.Wrap,Margin=new Thickness(0,6,0,4),
        Text="Select a source item. Raw OCR is never overwritten." };
    private readonly System.Windows.Controls.TextBox _r233Correction = new() {
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
        body.Children.Add(_r235FieldWarnings);
        body.Children.Add(_r237SourceSplitCandidates);
        body.Children.Add(_r238QrStatus);
        body.Children.Add(_r239GstinReview);
        body.Children.Add(_r243AlternativeOcr);
        body.Children.Add(_r244LowConfidence);
        body.Children.Add(_r233List);
        body.Children.Add(_r233Original);
        body.Children.Add(new TextBlock {
            Text="Correction (manual annotation only; not an approved field)",
            FontWeight=FontWeights.SemiBold,Margin=new Thickness(0,6,0,4) });
        body.Children.Add(_r233Correction);
        var save=new System.Windows.Controls.Button {
            Content="Save private correction",
            Padding=new Thickness(7,5,7,5),Margin=new Thickness(0,7,0,4),
            MinHeight=30 };
        save.Click += (_,_) => SaveSourceAnnotationR233();
        body.Children.Add(save);
        body.Children.Add(new TextBlock {
            Text="Original OCR, source boxes and image stay unchanged. " +
                 "Corrections are local and cannot authorize accounting posting.",
            Foreground=System.Windows.Media.Brushes.DimGray,TextWrapping=TextWrapping.Wrap });
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
        _r235FieldWarnings.Text="No source-field consistency evidence. Full accuracy not certified.";
        _r237SourceSplitCandidates.Text="No source-linked field candidates for this invoice.";
        _r238QrStatus.Text="QR source document ID not yet corroborated.";
        _r239GstinReview.Text="GSTIN check digits not verified for this invoice.";
        _r243AlternativeOcr.Text="No alternate high-resolution OCR source evidence for this invoice.";
        _r244LowConfidence.Text="No uncertain source-word reread available for this invoice.";
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
        if(source.TryGetProperty("field_consistency_review",out var consistency) &&
           consistency.ValueKind==JsonValueKind.Object &&
           R233GetString(consistency,"status")=="SOURCE_EVIDENCE_CONSISTENCY_REVIEW_ONLY" &&
           consistency.TryGetProperty("posting_eligible",out var postFlag) &&
           postFlag.ValueKind==JsonValueKind.False &&
           consistency.TryGetProperty("warnings",out var warnings) &&
           warnings.ValueKind==JsonValueKind.Array &&
           warnings.GetArrayLength()<=200)
        {
            var display=new List<string>();
            foreach(var warning in warnings.EnumerateArray())
            {
                if(warning.ValueKind!=JsonValueKind.Object ||
                   !warning.TryGetProperty("posting_eligible",out var wpost) ||
                   wpost.ValueKind!=JsonValueKind.False) {
                    display.Clear();break;
                }
                string issue=R233GetString(warning,"issue");
                string raw=R233GetString(warning,"raw_ocr_text");
                if(issue.Length==0 || issue.Length>100 || raw.Length>4000) {
                    display.Clear();break;
                }
                if(display.Count<12) display.Add(issue+" — "+raw[..Math.Min(raw.Length,90)]);
            }
            if(display.Count>0 || warnings.GetArrayLength()==0)
                _r235FieldWarnings.Text=warnings.GetArrayLength()+" OCR source-consistency flags. "+
                   (display.Count>0 ? string.Join("\n",display) :
                       "No source conflict detected; accuracy still not certified.");
            else
                _r235FieldWarnings.Text="Invalid OCR warnings refused; no values approved.";
        }
        else _r235FieldWarnings.Text="Field consistency review unavailable; no value approved.";
        if(source.TryGetProperty("source_field_associations",out var structured) &&
           structured.ValueKind==JsonValueKind.Object &&
           R233GetString(structured,"status")=="SOURCE_BOUND_FIELD_ASSOCIATIONS_UNVERIFIED" &&
           structured.TryGetProperty("posting_eligible",out var safe) &&
           safe.ValueKind==JsonValueKind.False &&
           structured.TryGetProperty("proposals",out var proposals) &&
           proposals.ValueKind==JsonValueKind.Array &&
           proposals.GetArrayLength()<=100)
        {
            var info=new List<string>();
            bool invalid=false;
            foreach(var proposal in proposals.EnumerateArray())
            {
                if(proposal.ValueKind!=JsonValueKind.Object ||
                   !proposal.TryGetProperty("posting_eligible",out var approved) ||
                   approved.ValueKind!=JsonValueKind.False)
                { invalid=true;break; }
                string kind=R233GetString(proposal,"type");
                if(kind is not ("HSN_WITH_ATTACHED_ROW_SERIAL" or
                                "TWO_SOURCE_AMOUNTS_JOINED_BY_OCR" or
                                "HEADER_SUPPLIER_NAME_FRAGMENTS"))
                { invalid=true;break; }
                string value="";
                if(proposal.TryGetProperty("candidate_text",out var candidate))
                {
                    if(candidate.ValueKind==JsonValueKind.String)
                        value=candidate.GetString()??"";
                    else if(candidate.ValueKind==JsonValueKind.Array)
                    {
                        var nums=new List<string>();
                        foreach(var part in candidate.EnumerateArray())
                        {
                            if(part.ValueKind!=JsonValueKind.String) { invalid=true;break; }
                            nums.Add(part.GetString()??"");
                        }
                        value=string.Join(" | ",nums);
                    }
                }
                if(invalid || value.Length==0 || value.Length>200)
                { invalid=true;break; }
                if(info.Count<8) info.Add(kind.Replace('_',' ')+": "+value);
            }
            _r237SourceSplitCandidates.Text=invalid
                ? "Malformed source associations rejected. No field approved."
                : proposals.GetArrayLength()+" unverified source-field proposals. "+
                    (info.Count>0 ? string.Join("\n",info) :
                     "No candidate requires review.");
        }
        else _r237SourceSplitCandidates.Text="Source field associations unavailable; no values approved.";
        if(source.TryGetProperty("qr_invoice_crosscheck",out var qr) &&
           qr.ValueKind==JsonValueKind.Object &&
           qr.TryGetProperty("posting_eligible",out var qrPosting) &&
           qrPosting.ValueKind==JsonValueKind.False &&
           qr.TryGetProperty("qr_invoice_id_candidates",out var qrCandidates) &&
           qrCandidates.ValueKind==JsonValueKind.Array && qrCandidates.GetArrayLength()<=10)
        {
            var options=new List<string>();
            bool valid=true;
            foreach(var v in qrCandidates.EnumerateArray())
            {
                if(v.ValueKind!=JsonValueKind.String) { valid=false;break; }
                string number=v.GetString()??"";
                if(!Regex.IsMatch(number,@"\A[A-Za-z0-9][A-Za-z0-9/_-]{1,49}\z"))
                { valid=false;break; }
                options.Add(number);
            }
            string status=R233GetString(qr,"status");
            if(!valid) _r238QrStatus.Text="Unsafe QR candidate rejected; no field approved.";
            else if(status=="SOURCE_QR_INVOICE_CANDIDATE_UNVERIFIED" && options.Count==1)
                _r238QrStatus.Text="QR-encoded invoice ID candidate: "+options[0]+
                   " (not independently verified; original printed invoice ID still required)";
            else if(status=="SOURCE_QR_UNREADABLE_REVIEW_REQUIRED")
                _r238QrStatus.Text="QR was not readable from this original photograph.";
            else
                _r238QrStatus.Text="QR cross-check: "+status+
                    "; no printed invoice identifier certified.";
        }
        else _r238QrStatus.Text="No trusted QR source evidence; invoice ID not certified.";
        // GSTIN check digit is a typo detector, never proof of supplier role.
        if(source.TryGetProperty("source_gstin_checkdigit_review",out var gst) &&
           gst.ValueKind==JsonValueKind.Object &&
           R233GetString(gst,"status")=="GSTIN_SOURCE_CHECKDIGIT_REVIEW_ONLY" &&
           gst.TryGetProperty("posting_eligible",out var gstPosted) &&
           gstPosted.ValueKind==JsonValueKind.False &&
           gst.TryGetProperty("candidates",out var gstRows) &&
           gstRows.ValueKind==JsonValueKind.Array && gstRows.GetArrayLength()<=50)
        {
            var wrong=new List<string>();
            bool gstEvidenceSafe=true;
            foreach(var item in gstRows.EnumerateArray())
            {
                if(item.ValueKind!=JsonValueKind.Object ||
                   !item.TryGetProperty("posting_eligible",out var ok) ||
                   ok.ValueKind!=JsonValueKind.False)
                { gstEvidenceSafe=false;break; }
                bool valid=item.TryGetProperty("checksum_valid",out var chk) &&
                           chk.ValueKind==JsonValueKind.True;
                if(!valid) {
                    var raw=R233GetString(item,"literal_source_text");
                    if(raw.Length!=15) { gstEvidenceSafe=false;break; }
                    if(wrong.Count<8)wrong.Add(raw);
                }
            }
            _r239GstinReview.Text=!gstEvidenceSafe
                ? "Untrusted GSTIN OCR evidence refused; no values approved."
                : gstRows.GetArrayLength()+" GSTIN OCR readings checked. "+
                    (wrong.Count>0 ? "Checksum mismatch (source review required): "+
                                     string.Join(", ",wrong)
                                   : "No checksum mismatch detected; supplier identity still unverified.");
        }
        else _r239GstinReview.Text="GSTIN source-check status unavailable; no values approved.";
        if(source.TryGetProperty("low_confidence_crop_rereads",out var crop) &&
           crop.ValueKind==JsonValueKind.Object &&
           R233GetString(crop,"status")=="UNCERTAIN_SOURCE_TOKEN_REREADS_REVIEW_ONLY" &&
           crop.TryGetProperty("posting_eligible",out var cropPost) &&
           cropPost.ValueKind==JsonValueKind.False &&
           crop.TryGetProperty("review_items",out var suspects) &&
           suspects.ValueKind==JsonValueKind.Array && suspects.GetArrayLength()<=8)
        {
            var notes=new List<string>();
            bool safe=true;
            foreach(var suspect in suspects.EnumerateArray())
            {
                string original=R233GetString(suspect,"raw_source_text");
                if(original.Length<1 || original.Length>1500 ||
                   !suspect.TryGetProperty("posting_eligible",out var neverPost) ||
                   neverPost.ValueKind!=JsonValueKind.False ||
                   !suspect.TryGetProperty("source_box",out var physical) ||
                   physical.ValueKind!=JsonValueKind.Array || physical.GetArrayLength()!=4 ||
                   !suspect.TryGetProperty("reread_observations",out var candidates) ||
                   candidates.ValueKind!=JsonValueKind.Array || candidates.GetArrayLength()>4)
                { safe=false;break; }
                var readings=new List<string>();
                foreach(var o in candidates.EnumerateArray())
                {
                    string t=R233GetString(o,"reading");
                    if(t.Length>220) { safe=false;break; }
                    if(t.Length>0 && !readings.Contains(t)) readings.Add(t);
                }
                if(!safe)break;
                notes.Add(original[..Math.Min(original.Length,50)]+" ⇒ "+
                    (readings.Count>0
                        ? string.Join(" | ",readings.Select(x=>x[..Math.Min(x.Length,40)]))
                        : "no valid local reread"));
            }
            _r244LowConfidence.Text=safe
                ? suspects.GetArrayLength()+" uncertain source cells. Reread alternatives (unverified): "+
                  string.Join("; ",notes)
                : "Untrusted source-cell reread rejected; accounting not approved.";
        }
        else _r244LowConfidence.Text="Low-confidence source crop OCR unavailable; no values approved.";

        if(refinement.TryGetProperty("alternate_multiscale_source_review",out var alternate) &&
           alternate.ValueKind==JsonValueKind.Object &&
           R233GetString(alternate,"status")=="SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY" &&
           alternate.TryGetProperty("posting_eligible",out var alternatePosting) &&
           alternatePosting.ValueKind==JsonValueKind.False &&
           alternate.TryGetProperty("variants",out var variants) &&
           variants.ValueKind==JsonValueKind.Array && variants.GetArrayLength()==2)
        {
            var summaries=new List<string>();
            bool valid=true;
            foreach(var variant in variants.EnumerateArray())
            {
                string name=R233GetString(variant,"variant");
                if(name is not ("gray_2x" or "clahe_2x") ||
                   !variant.TryGetProperty("posting_eligible",out var vp) ||
                   vp.ValueKind!=JsonValueKind.False ||
                   !variant.TryGetProperty("source_ocr_words_total",out var wc) ||
                   wc.ValueKind!=JsonValueKind.Number || !wc.TryGetInt32(out var n) ||
                   n<0 || n>8000 ||
                   !variant.TryGetProperty("source_boxes_are_original_pixels",out var orig) ||
                   orig.ValueKind!=JsonValueKind.True)
                { valid=false; break; }
                summaries.Add(name+": "+n+" OCR source words");
            }
            _r243AlternativeOcr.Text=valid && summaries.Count==2
                ? "Alternative 2x image readings (unverified): "+string.Join("; ",summaries)+
                  ". The original OCR and field assignments are not replaced."
                : "Unsafe alternate OCR evidence refused; no data approved.";
        }
        else _r243AlternativeOcr.Text="No verified alternate source OCR available; no values approved.";





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
            System.Windows.MessageBox.Show("Select a valid source item and type a correction. " +
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
            System.Windows.MessageBox.Show("Correction could not be saved: "+ex.Message,
                "Source review error",MessageBoxButton.OK,MessageBoxImage.Error);
        }
    }

    internal void AssertR233NativeReviewReadyForInstaller()
    {
        if(!_r233NativePanelBuilt || _r233List is null ||
           _r233Summary is null || _r233Correction.MaxLength!=350)
            throw new InvalidOperationException("R233 native source-linked review UI missing.");
        if(_r235FieldWarnings is null)
            throw new InvalidOperationException("R235 source warning display missing.");
        // Actual native WPF smoke: display a synthetic source-locked queue item
        // and reject an unrelated/empty invoice, without reading any user files.
        var synthetic=new {
            zone_refinement=new { source_row_and_date_review=new {
                manual_review_queue=new {
                    status="IMMUTABLE_SOURCE_REVIEW_REQUIRED",
                    posting_eligible=false,release_approved=false,
                    items=new [] { new {
                        review_id="IVR231-"+new string('a',24),
                        review_kind="ITEM_ROW_HSN_ANCHOR",
                        source_frame_sha256=new string('b',64),
                        review_required=true,posting_eligible=false,
                        original_observations=new [] {new {
                            original_ocr_text="SYNTHETIC TEST ITEM",
                            original_box=new [] {1,2,100,24}
                        }}
                    }}
                },
                field_consistency_review=new {
                    status="SOURCE_EVIDENCE_CONSISTENCY_REVIEW_ONLY",
                    posting_eligible=false,
                    warnings=new [] {new {
                        issue="NINE_DIGIT_HSN_WITH_POSSIBLE_LEADING_SERIAL",
                        raw_ocr_text="433051090 SYNTHETIC PRODUCT",
                        posting_eligible=false
                    }}
                },
                source_field_associations=new {
                    status="SOURCE_BOUND_FIELD_ASSOCIATIONS_UNVERIFIED",
                    posting_eligible=false,
                    proposals=new [] {new {
                        type="HSN_WITH_ATTACHED_ROW_SERIAL",
                        candidate_text="33051090",
                        posting_eligible=false
                    }}
                },
                qr_invoice_crosscheck=new {
                    status="SOURCE_QR_INVOICE_CANDIDATE_UNVERIFIED",
                    posting_eligible=false,
                    qr_invoice_id_candidates=new [] {"TEST-QR-0049"}
                },
                low_confidence_crop_rereads=new {
                    status="UNCERTAIN_SOURCE_TOKEN_REREADS_REVIEW_ONLY",
                    posting_eligible=false,
                    review_items=new [] {new {
                        raw_source_text="2x",
                        posting_eligible=false,
                        source_box=new [] {10,12,35,28},
                        reread_observations=new [] {
                            new {reading="20",posting_eligible=false},
                            new {reading="30",posting_eligible=false}
                        }
                    }}
                }
            }, alternate_multiscale_source_review=new {
                status="SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
                posting_eligible=false,
                variants=new [] {
                    new {variant="gray_2x",posting_eligible=false,
                        source_ocr_words_total=17,source_boxes_are_original_pixels=true},
                    new {variant="clahe_2x",posting_eligible=false,
                        source_ocr_words_total=23,source_boxes_are_original_pixels=true}
                }
            }}
        };
        using (var syntheticDoc=JsonDocument.Parse(JsonSerializer.Serialize(synthetic)))
        {
            LoadSourceReviewQueueR233(syntheticDoc.RootElement,new string('c',64));
            if(_r233Queue.Count!=1 || _r233List.Items.Count!=1 ||
               !_r233Summary.Text.Contains("1 original-source item") ||
               !_r235FieldWarnings.Text.Contains("NINE_DIGIT_HSN_WITH_POSSIBLE_LEADING_SERIAL") ||
               !_r237SourceSplitCandidates.Text.Contains("33051090") ||
               !_r238QrStatus.Text.Contains("TEST-QR-0049") ||
               !_r243AlternativeOcr.Text.Contains("clahe_2x: 23 OCR source words") ||
               !_r244LowConfidence.Text.Contains("20 | 30"))
                throw new InvalidOperationException("R233 native source queue did not display synthetic evidence.");
        }
        using (var empty=JsonDocument.Parse("{}"))
        {
            LoadSourceReviewQueueR233(empty.RootElement,new string('d',64));
            if(_r233Queue.Count!=0 || _r233List.Items.Count!=0 ||
               _r233PhotoHash is not null ||
               _r235FieldWarnings.Text.Contains("SYNTHETIC PRODUCT") ||
               _r237SourceSplitCandidates.Text.Contains("33051090") ||
               _r238QrStatus.Text.Contains("TEST-QR-0049") ||
               _r243AlternativeOcr.Text.Contains("23 OCR source words") ||
               _r244LowConfidence.Text.Contains("20 | 30"))
                throw new InvalidOperationException("R233 leaked review data between source invoices.");
        }
    }
}
