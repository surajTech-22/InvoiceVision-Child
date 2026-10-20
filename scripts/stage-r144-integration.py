"""Apply reviewed research overlays only inside an isolated CI build tree.

Baseline source identity is checked first; the original archive stays immutable.
Never run this against an installed Child or a user accounting directory.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGET='InvoiceVisionChild/Engine/INVOICE_OCR_PADDLE_ADAPTER_R112.py'


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
    before=hashlib.sha256((build/TARGET).read_bytes()).hexdigest()
    replacement=(ROOT/'integration/Engine/INVOICE_OCR_PADDLE_ADAPTER_R112.py').read_bytes()
    (build/TARGET).write_bytes(replacement)
    after=hashlib.sha256(replacement).hexdigest()
    for entry in manifest['files']:
        if entry['path']==TARGET:
            entry['sha256']=after
            if 'size_bytes' in entry:entry['size_bytes']=len(replacement)
    manifest_path.write_text(json.dumps(manifest,indent=2))
    (build/'R144_INTEGRATION_PROVENANCE.json').write_text(json.dumps({
        'target':TARGET,'previous_sha256':before,'overlay_sha256':after,
        'release_authorized':False,'installed_application_modified':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('build',type=Path);a=p.parse_args();stage(a.build)
