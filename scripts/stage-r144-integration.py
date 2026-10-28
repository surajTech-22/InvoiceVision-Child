"""Apply reviewed research overlays only inside an isolated CI build tree.

Baseline source identity is checked first; the original archive stays immutable.
Never run this against an installed Child or a user accounting directory.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGETS=['InvoiceVisionChild/Engine/INVOICE_OCR_PADDLE_ADAPTER_R112.py',
         'InvoiceVisionChild/Engine/INVOICE_OCR_RECURSIVE_ZONES_R109.py']

# Additive, review-only modules (not among the verified original 73 files).
REVIEW_MODULES={
    'experiments/r223_source_table_rows.py': 'INVOICE_OCR_SOURCE_ROWS_R223.py',
    'integration/Engine/INVOICE_OCR_SOURCE_REVIEW_R226.py': 'INVOICE_OCR_SOURCE_REVIEW_R226.py',
    'integration/Engine/INVOICE_OCR_LAYOUT_RECOVERY_R229.py': 'INVOICE_OCR_LAYOUT_RECOVERY_R229.py',
    'integration/Engine/INVOICE_OCR_REVIEW_QUEUE_R231.py': 'INVOICE_OCR_REVIEW_QUEUE_R231.py',
    'integration/Engine/INVOICE_OCR_FIELD_CONSISTENCY_R235.py': 'INVOICE_OCR_FIELD_CONSISTENCY_R235.py',
    'integration/Engine/INVOICE_OCR_TARGETED_RECHECK_R236.py': 'INVOICE_OCR_TARGETED_RECHECK_R236.py',
    'integration/Engine/INVOICE_OCR_SOURCE_FIELD_ASSOCIATIONS_R237.py': 'INVOICE_OCR_SOURCE_FIELD_ASSOCIATIONS_R237.py',
    'integration/Engine/INVOICE_OCR_QR_REVIEW_R238.py': 'INVOICE_OCR_QR_REVIEW_R238.py',
    'integration/Engine/INVOICE_OCR_GSTIN_REVIEW_R239.py': 'INVOICE_OCR_GSTIN_REVIEW_R239.py',
    'integration/Engine/INVOICE_OCR_MULTISCALE_REVIEW_R243.py': 'INVOICE_OCR_MULTISCALE_REVIEW_R243.py',
    'integration/Engine/INVOICE_OCR_FIELD_CROP_REVIEW_R244.py': 'INVOICE_OCR_FIELD_CROP_REVIEW_R244.py',
    'integration/Engine/INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py': 'INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py',
    'integration/Engine/INVOICE_OCR_GRID_TABLE_R246.py': 'INVOICE_OCR_GRID_TABLE_R246.py',
    'integration/Engine/INVOICE_OCR_RULED_ROW_BANDS_R259.py': 'INVOICE_OCR_RULED_ROW_BANDS_R259.py',
    'integration/Engine/INVOICE_OCR_COLUMN_BANDS_R261.py': 'INVOICE_OCR_COLUMN_BANDS_R261.py',
    'integration/Engine/INVOICE_OCR_NUMERIC_WITNESS_R268.py': 'INVOICE_OCR_NUMERIC_WITNESS_R268.py',
    'integration/Engine/INVOICE_OCR_NUMERIC_ONLY_R272.py': 'INVOICE_OCR_NUMERIC_ONLY_R272.py',
    'integration/Engine/INVOICE_OCR_ITEM_AMOUNT_REREAD_R248.py': 'INVOICE_OCR_ITEM_AMOUNT_REREAD_R248.py',
}


def stage(build):
    build=build.resolve()
    if build != (ROOT/'integration-build').resolve():
        raise ValueError('Only the isolated repository integration-build directory is allowed')
    manifest_path=build/'CHILD_SOURCE_SHA256.json'
    manifest=json.loads(manifest_path.read_text())
    if len(manifest['files'])!=73:raise ValueError('Incomplete baseline source manifest')
    for entry in manifest['files']:
        path=Path(entry['path'])
        if path.is_absolute() or '..' in path.parts or not entry['path'].startswith('InvoiceVisionChild/'):
            raise ValueError('Unsafe baseline manifest path')
        if hashlib.sha256((build/path).read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('Baseline source checksum mismatch: '+entry['path'])
    changes=[]
    for target in TARGETS:
        before=hashlib.sha256((build/target).read_bytes()).hexdigest()
        replacement=(ROOT/'integration/Engine'/Path(target).name).read_bytes()
        (build/target).write_bytes(replacement)
        after=hashlib.sha256(replacement).hexdigest()
        changes.append({'target':target,'previous_sha256':before,'overlay_sha256':after})
        for entry in manifest['files']:
            if entry['path']==target:
                entry['sha256']=after
                if 'size_bytes' in entry:entry['size_bytes']=len(replacement)
    # Preserve original manifest identity and stage extra source-only files.
    engine=build/'InvoiceVisionChild/Engine'
    if not engine.is_dir():
        raise ValueError('Staged Child Engine folder is absent')
    for source_rel, dest_name in REVIEW_MODULES.items():
        source=ROOT/source_rel
        destination=engine/dest_name
        if not source.is_file() or destination.exists():
            raise ValueError('Additive review module missing or collides with baseline: '+source_rel)
        shutil.copyfile(source,destination)
        changes.append({'type':'ADDITIVE_REVIEW_MODULE_NOT_BASELINE',
                        'target':str(destination.relative_to(build)).replace(chr(92),'/'),
                        'overlay_sha256':hashlib.sha256(destination.read_bytes()).hexdigest()})
    # R233: patch the verified native C# workspace only inside the isolated
    # research build. An exact one-time string match prevents fuzzy edits to
    # any new or unverified installed application revision.
    cs_rel='InvoiceVisionChild/InvoiceZoneWorkspace.cs'
    cs_path=build/cs_rel
    original=cs_path.read_text(encoding='utf-8-sig')
    review_insert='inspector.Children.Add(_zoneContentStatus);'
    review_attach='inspector.Children.Add(_zoneContentStatus); AttachSourceReviewUiR233(inspector);'
    review_load='RefreshZonePhoto(); RefreshZones();'
    review_loaded='LoadSourceReviewQueueR233(root, actualHash); RefreshZonePhoto(); RefreshZones();'
    smoke='ToggleZoneInspector();\n        if (_toolTabs.SelectedIndex != 1)'
    smoke_new='ToggleZoneInspector();\n        AssertR233NativeReviewReadyForInstaller();\n        if (_toolTabs.SelectedIndex != 1)'
    for before,after in ((review_insert,review_attach),(review_load,review_loaded),
                         (smoke,smoke_new)):
        if original.count(before)!=1:
            raise ValueError('Verified C# source review insertion anchor mismatched: '+before[:55])
        original=original.replace(before,after)
    previous=hashlib.sha256(cs_path.read_bytes()).hexdigest()
    cs_path.write_text(original,encoding='utf-8')
    after=hashlib.sha256(cs_path.read_bytes()).hexdigest()
    matching=[entry for entry in manifest['files'] if entry['path']==cs_rel]
    if len(matching)!=1:raise ValueError('Expected exactly one sealed native workspace source')
    matching[0]['sha256']=after
    if 'size_bytes' in matching[0]:matching[0]['size_bytes']=cs_path.stat().st_size
    changes.append({'type':'R233_STAGED_NATIVE_WPF_REVIEW_HOOK',
                    'target':cs_rel,'previous_sha256':previous,'overlay_sha256':after})
    add_source=ROOT/'integration/Window/InvoiceSourceReviewR233.cs'
    add_target=build/'InvoiceVisionChild/InvoiceSourceReviewR233.cs'
    if not add_source.is_file() or add_target.exists():
        raise ValueError('R233 WPF review source missing or collides with original')
    shutil.copyfile(add_source,add_target)
    changes.append({'type':'R233_ADDITIVE_WPF_SOURCE_NOT_ORIGINAL_BASELINE',
                    'target':'InvoiceVisionChild/InvoiceSourceReviewR233.cs',
                    'overlay_sha256':hashlib.sha256(add_target.read_bytes()).hexdigest()})
    # R233: request read-only geometry review only for source analysis.
    # No OCR writes or posting permissions are ever enabled by this variable.
    category_rel='InvoiceVisionChild/InvoiceCategoryFirst.cs'
    category_path=build/category_rel
    code=category_path.read_text(encoding='utf-8-sig')
    before='psi.ArgumentList.Add("-u"); psi.ArgumentList.Add(_categoryEngine);'
    after=(before+'\n        if (arguments.Length > 0 && arguments[0] == "analyze") { '
           'psi.Environment["INVOICEVISION_SOURCE_REVIEW_R226"] = "1"; '
           'psi.Environment["INVOICEVISION_R236_TARGETED_RECHECK"] = "1"; '
           'psi.Environment["INVOICEVISION_R244_FIELD_CROP_REVIEW"] = "1"; }')
    if code.count(before)!=1:
        raise ValueError('Verified category analysis launch hook changed')
    before_sha=hashlib.sha256(category_path.read_bytes()).hexdigest()
    category_path.write_text(code.replace(before,after),encoding='utf-8')
    after_sha=hashlib.sha256(category_path.read_bytes()).hexdigest()
    matches=[e for e in manifest['files'] if e['path']==category_rel]
    if len(matches)!=1:raise ValueError('Sealed category WPF source not present')
    matches[0]['sha256']=after_sha
    if 'size_bytes' in matches[0]:matches[0]['size_bytes']=category_path.stat().st_size
    changes.append({'type':'R233_ENABLE_SOURCE_REVIEW_IN_ANALYSIS_ONLY',
                    'target':category_rel,'previous_sha256':before_sha,
                    'overlay_sha256':after_sha})
    # R234 privacy: source repository remains separately restricted by owner,
    # but no customer invoice example is embedded/launched in a candidate app.
    program_rel='InvoiceVisionChild/Program.cs'
    program=build/program_rel
    contents=program.read_text(encoding='utf-8-sig')
    deprecated=[
        ('            LoadBenchmarkPreview();',
         '            // R234: bundled customer-invoice previews disabled.'),
        ('            if (autoBenchmark && !previouslyCompleted)\n'
         '                Dispatcher.BeginInvoke(new Action(async () => await RunAsync("benchmark")), DispatcherPriority.ContextIdle);',
         '            // R234: automatic customer-invoice benchmark execution disabled.'),
        ('        AddButton(advancedPanel, "Run 15 Real Example Photos", async () => await RunAsync("benchmark"));',
         '        // R234: private benchmark source is never presented as a demo option.'),
    ]
    for before,after in deprecated:
        if contents.count(before)!=1:
            raise ValueError('Unexpected sealed native Program.cs benchmark hook')
        contents=contents.replace(before,after)
    old_program=hashlib.sha256(program.read_bytes()).hexdigest()
    program.write_text(contents,encoding='utf-8')
    new_program=hashlib.sha256(program.read_bytes()).hexdigest()
    matches=[e for e in manifest['files'] if e['path']==program_rel]
    if len(matches)!=1:raise ValueError('Sealed native Program.cs absent')
    matches[0]['sha256']=new_program
    if 'size_bytes' in matches[0]:matches[0]['size_bytes']=program.stat().st_size
    changes.append({'type':'R234_DISABLE_CUSTOMER_CORPUS_UI_AND_AUTO_BENCHMARK',
                    'target':program_rel,'previous_sha256':old_program,
                    'overlay_sha256':new_program})
    # R241: isolated, fully local OCR runtime support in the real Child.
    # Preserve the sealed source archive. All substitutions are one-time,
    # exact-match and fail if the baseline handoff changed unexpectedly.
    bundled_source=ROOT/'integration/Window/InvoiceChildBundledRuntimeR241.cs'
    bundled_target=build/'InvoiceVisionChild/InvoiceChildBundledRuntimeR241.cs'
    if not bundled_source.is_file() or bundled_target.exists():
        raise ValueError('R241 bundled runtime helper missing or source collision')
    shutil.copyfile(bundled_source,bundled_target)
    changes.append({'type':'R241_ADDITIVE_LOCAL_OCR_RUNTIME_SOURCE',
                    'target':'InvoiceVisionChild/InvoiceChildBundledRuntimeR241.cs',
                    'overlay_sha256':hashlib.sha256(bundled_target.read_bytes()).hexdigest()})
    # Existing verified Paddle user runtimes retain precedence, and bundled
    # local Tesseract is an additional verified, self-contained candidate.
    handoff_rel='InvoiceVisionChild/AahInvoiceHandoff.cs'
    handoff_path=build/handoff_rel
    handoff=handoff_path.read_text(encoding='utf-8-sig')
    handoff_before='var candidates = new[] {\n            verifiedPython,\n'
    handoff_after=('var candidates = new[] {\n            verifiedPython,\n'
                   '            InvoiceChildBundledRuntimeR241.PythonExecutable,\n')
    subprocess_before='            start.ArgumentList.Add("-u"); start.ArgumentList.Add(engine);'
    subprocess_after=('            InvoiceChildBundledRuntimeR241.Configure(start);\n'
                      +subprocess_before)
    for before,after in ((handoff_before,handoff_after),
                         (subprocess_before,subprocess_after)):
        if handoff.count(before)!=1:
            raise ValueError('R241 original AAH handoff source changed unexpectedly')
        handoff=handoff.replace(before,after)
    handoff_original_sha=hashlib.sha256(handoff_path.read_bytes()).hexdigest()
    handoff_path.write_text(handoff,encoding='utf-8')
    handoff_new_sha=hashlib.sha256(handoff_path.read_bytes()).hexdigest()
    handoff_matches=[v for v in manifest['files'] if v['path']==handoff_rel]
    if len(handoff_matches)!=1:raise ValueError('Original handoff not in sealed manifest')
    handoff_matches[0]['sha256']=handoff_new_sha
    if 'size_bytes' in handoff_matches[0]:
        handoff_matches[0]['size_bytes']=handoff_path.stat().st_size
    changes.append({'type':'R241_OFFLINE_RUNTIME_AAH_HANDOFF',
                    'previous_sha256':handoff_original_sha,
                    'overlay_sha256':handoff_new_sha})
    # Native category Analyze/OCR invokes the same isolated launcher.
    cat=category_path.read_text(encoding='utf-8')
    config_before='        foreach (var arg in arguments) psi.ArgumentList.Add(arg);'
    config_after=('        InvoiceChildBundledRuntimeR241.Configure(psi);\n'
                  +config_before)
    if cat.count(config_before)!=1:raise ValueError('R241 Child OCR launch hook missing')
    cat=cat.replace(config_before,config_after)
    before_sha=hashlib.sha256(category_path.read_bytes()).hexdigest()
    category_path.write_text(cat,encoding='utf-8')
    after_sha=hashlib.sha256(category_path.read_bytes()).hexdigest()
    cat_matches=[v for v in manifest['files'] if v['path']==category_rel]
    if len(cat_matches)!=1:raise ValueError('Category source absent during runtime overlay')
    cat_matches[0]['sha256']=after_sha
    if 'size_bytes' in cat_matches[0]:
        cat_matches[0]['size_bytes']=category_path.stat().st_size
    changes.append({'type':'R241_PRIVATE_CHILD_PROCESS_ONLY_OCR_ENVIRONMENT',
                    'previous_sha256':before_sha,
                    'overlay_sha256':after_sha})
    # R243: integrate actual source-preserving 2x OCR evidence into the
    # original Child category-first analyzer. No auto-selected values change.
    analyzer_rel='InvoiceVisionChild/Engine/INVOICE_OCR_CATEGORY_FIRST_R101.py'
    analyzer_path=build/analyzer_rel
    analyzer=analyzer_path.read_text(encoding='utf-8-sig')
    before=' regions,refinement,content_lines=refine_regions(oriented,coarse,content_tsv)'
    after=before+'''
 # R243 only adds alternative original-pixel-bound OCR review metadata.
 # Original first-pass OCR/boxes, zone decisions and posting permissions stay.
 try:
  if binary and binary!='__PADDLEOCR3__':
   import importlib.util
   alt=Path(__file__).with_name('INVOICE_OCR_MULTISCALE_REVIEW_R243.py')
   spec=importlib.util.spec_from_file_location('_child_r243_multiscale_review',alt)
   if spec is None or spec.loader is None:raise RuntimeError('R243 source review missing')
   module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   def local_read(view,psm):
    return ts_exec(binary,view,psm=str(psm),tsv=True,deadline=38)
   refinement['alternate_multiscale_source_review']=module.review(oriented,local_read,max_words=480)
   try:
    anchors=Path(__file__).with_name('INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py')
    aspec=importlib.util.spec_from_file_location('_child_r245_field_row_anchors',anchors)
    if aspec is None or aspec.loader is None:
     raise RuntimeError('R245 source field/row engine unavailable')
    amodule=importlib.util.module_from_spec(aspec)
    aspec.loader.exec_module(amodule)
    ah,aw=oriented.shape[:2]
    refinement['source_field_row_anchors_r245']=amodule.propose(
     refinement['alternate_multiscale_source_review'],aw,ah)
   except Exception as anchor_error:
    refinement['source_field_row_anchors_r245']={
     'status':'SOURCE_FIELD_ROW_ANCHORS_UNAVAILABLE',
     'error_type':type(anchor_error).__name__,
     'posting_eligible':False,'release_approved':False}
   # R246 treats ruling-line-suppressed OCR only as a separate row hypothesis;
   # it cannot overwrite R243/R245 first-pass evidence or approve fields.
   try:
    grid_path=Path(__file__).with_name('INVOICE_OCR_GRID_TABLE_R246.py')
    gspec=importlib.util.spec_from_file_location('_child_r246_grid_table',grid_path)
    if gspec is None or gspec.loader is None:
     raise RuntimeError('R246 grid source table module missing')
    gmodule=importlib.util.module_from_spec(gspec);gspec.loader.exec_module(gmodule)
    def local_plain(view,psm):
     return ts_exec(binary,view,psm=str(psm),tsv=False,deadline=24)
    # Optional original-pixel numeric-only OCR uses verified local Tesseract
    # directly on in-memory PNG bytes (stdin->stdout; no private temp file).
    # The Child continues to function without this optional OCR witness.
    numeric_read=None
    try:
     npath=Path(__file__).with_name('INVOICE_OCR_NUMERIC_ONLY_R272.py')
     nspec=importlib.util.spec_from_file_location('_child_r272_numeric',npath)
     if nspec is None or nspec.loader is None:
      raise RuntimeError('R272 local numeric OCR module unavailable')
     nmodule=importlib.util.module_from_spec(nspec);nspec.loader.exec_module(nmodule)
     numeric_read=nmodule.reader_for(binary)
    except Exception:
     numeric_read=None
    refinement['source_grid_table_review_r246']=gmodule.review(
     oriented,local_read,local_plain,numeric_read)
   except Exception as grid_error:
    refinement['source_grid_table_review_r246']={
     'status':'GRID_TABLE_REVIEW_UNAVAILABLE',
     'error_type':type(grid_error).__name__,
     'posting_eligible':False,'release_approved':False}
  else:
   refinement['alternate_multiscale_source_review']={
    'status':'CPU_ALTERNATE_OCR_UNAVAILABLE','posting_eligible':False,
    'release_approved':False}
 except Exception as exc:
  refinement['alternate_multiscale_source_review']={
   'status':'REVIEW_UNAVAILABLE','error_type':type(exc).__name__,
   'posting_eligible':False,'release_approved':False}
'''
    if analyzer.count(before)!=1:
        raise ValueError('R243 genuine source analyzer OCR review anchor unexpectedly changed')
    old_sha=hashlib.sha256(analyzer_path.read_bytes()).hexdigest()
    analyzer_path.write_text(analyzer.replace(before,after),encoding='utf-8')
    new_sha=hashlib.sha256(analyzer_path.read_bytes()).hexdigest()
    records=[x for x in manifest['files'] if x['path']==analyzer_rel]
    if len(records)!=1:raise ValueError('R243 actual category-first analyzer source missing')
    records[0]['sha256']=new_sha
    if 'size_bytes' in records[0]:
        records[0]['size_bytes']=analyzer_path.stat().st_size
    changes.append({'type':'R243_TWO_ALTERNATE_SOURCE_VIEW_OCR_AFTER_BASELINE',
                    'target':analyzer_rel,'previous_sha256':old_sha,
                    'overlay_sha256':new_sha})
    manifest_path.write_text(json.dumps(manifest,indent=2))
    (build/'R144_INTEGRATION_PROVENANCE.json').write_text(json.dumps({
        'changes':changes,
        'release_authorized':False,'installed_application_modified':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);a=p.parse_args();stage(a.build)
