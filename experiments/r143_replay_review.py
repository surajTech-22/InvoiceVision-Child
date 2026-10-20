"""Replay existing independent OCR, verify original hashes, draw review evidence.

This does not perform new OCR inference or certify any physical invoice box.
"""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw
from .r143_orientation_evidence import hypotheses


def run(evidence, out):
    out.mkdir(parents=True, exist_ok=True)
    reports = {e: json.loads((evidence/e/'REPORT.json').read_text()) for e in ('rapidocr','paddleocr')}
    by_engine = {e: {c['file']: c for c in report['cases']} for e, report in reports.items()}
    if set(by_engine['rapidocr']) != set(by_engine['paddleocr']):
        raise ValueError('Independent OCR source sets differ')
    summary = {'kind': 'REPLAY_OF_EXISTING_CPU_OCR_NOT_NEW_INFERENCE',
               'posting_eligible': False, 'release_verified': False, 'cases': []}
    for filename in sorted(by_engine['rapidocr']):
        path = evidence/'rapidocr'/(Path(filename).stem+'_input.jpg')
        raw = path.read_bytes()
        original = Image.open(path).convert('RGB')
        views = {}
        for engine, cases in by_engine.items():
            case = cases[filename]
            if list(original.size) != [case['source_width'], case['source_height']]:
                raise ValueError('Source dimensions do not match report')
            views[engine] = hypotheses(case, engine, raw)
        sha = hashlib.sha256(raw).hexdigest()
        comparison = Image.new('RGB', (original.width*3, original.height+60), 'white')
        comparison.paste(original, (0,60))
        draw = ImageDraw.Draw(comparison)
        draw.text((10,10), 'ORIGINAL / '+filename, fill='black')
        counts = {}
        for column, engine in enumerate(('rapidocr','paddleocr'),1):
            pane = original.copy(); d = ImageDraw.Draw(pane)
            rows = [r for view in views[engine] for r in view['candidates']]
            seen = set()
            for row in rows:
                color = {'consignee':'orange','buyer':'cyan','supplier':'lime',
                         'invoice_number':'magenta','invoice_date':'yellow','grand_total':'red'}.get(row['field'],'white')
                for box in row['source_regions']:
                    key = row['field'], tuple(box)
                    if key in seen: continue
                    seen.add(key)
                    d.rectangle(box, outline=color, width=2)
                    d.text((box[0], max(0,box[1]-12)), row['field'], fill=color, stroke_width=1, stroke_fill='black')
            comparison.paste(pane, (column*original.width,60))
            draw.text((column*original.width+10,10), engine+' / FIELD CANDIDATES ONLY / physical borders unverified',fill='black')
            counts[engine] = {'candidates_with_orientation_hypotheses':len(rows),
                              'issues':len(views[engine][0]['issues'])}
        comparison.save(out/(Path(filename).stem+'_source_comparison.jpg'),quality=92)
        (out/(Path(filename).stem+'_evidence.json')).write_text(json.dumps(views, indent=2,ensure_ascii=False))
        summary['cases'].append({'file':filename,'source_sha256':sha,'engines':counts,
                                 'source_bytes_verified':True,'physical_boxes_verified':False})
    summary['source_count'] = len(summary['cases'])
    (out/'REPORT.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps({'sources_replayed':len(summary['cases']), 'release_verified':False}))

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.evidence,a.out)
