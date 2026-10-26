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
    manifest_path.write_text(json.dumps(manifest,indent=2))
    (build/'R144_INTEGRATION_PROVENANCE.json').write_text(json.dumps({
        'changes':changes,
        'release_authorized':False,'installed_application_modified':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);a=p.parse_args();stage(a.build)
