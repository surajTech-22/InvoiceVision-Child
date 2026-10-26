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
           'psi.Environment["INVOICEVISION_R236_TARGETED_RECHECK"] = "1"; }')
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
    manifest_path.write_text(json.dumps(manifest,indent=2))
    (build/'R144_INTEGRATION_PROVENANCE.json').write_text(json.dumps({
        'changes':changes,
        'release_authorized':False,'installed_application_modified':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);a=p.parse_args();stage(a.build)
