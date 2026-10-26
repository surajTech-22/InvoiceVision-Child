"""R226 source-coordinate review adapter for the real InvoiceVision Child zone engine.

Receives the exact decoded image pixels and raw OCR TSV used in Child.
Never reconstructs an original JPEG hash from decoded pixels, never changes
OCR text, boxes, zones, financial values or posting eligibility.
Enabled ONLY by INVOICEVISION_SOURCE_REVIEW_R226=1 in recursive engine.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import hashlib
import importlib.util
import math
import re

_DATE = re.compile(r'(?<!\d)(\d{1,2})([/.-])(\d{1,2})\2(\d{4})')
_TIME = re.compile(r'^\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:AM|PM))?', re.I)
_HEADER = ('level', 'page_num', 'block_num', 'par_num', 'line_num',
           'word_num', 'left', 'top', 'width', 'height', 'conf', 'text')


def _raw_tsv_observations(tsv, width, height):
    """Keep every accepted Child source token; refuse malformed geometry."""
    if not isinstance(tsv, str):
        raise ValueError('Expected raw source-coordinate TSV')
    lines = tsv.splitlines()
    if not lines or tuple(lines[0].split('\t')) != _HEADER:
        raise ValueError('Missing exact source-coordinate TSV header')
    texts, rects, tsv_rows = [], [], []
    for row_id, row in enumerate(lines[1:], 2):
        if not row.strip():
            continue
        parts = row.split('\t', 11)
        if len(parts) != 12 or parts[0] != '5':
            raise ValueError('Unrecognized raw OCR TSV at row %d' % row_id)
        try:
            x, y, w, h = [int(parts[i]) for i in (6, 7, 8, 9)]
            conf = float(parts[10])
        except (ValueError, OverflowError) as ex:
            raise ValueError('Malformed source coordinates/confidence at row %d' % row_id) from ex
        if not (math.isfinite(conf) and 0 <= conf <= 100 and
                0 <= x < x + w <= width and 0 <= y < y + h <= height):
            raise ValueError('Source observation is outside source image at row %d' % row_id)
        if not parts[11].strip():
            # A blank string has no source evidence, and is NOT repaired.
            raise ValueError('Empty source text at row %d' % row_id)
        texts.append(parts[11])
        rects.append([x, y, x+w, y+h])
        tsv_rows.append(row_id)
    return texts, rects, tsv_rows


def _date_flags(texts, boxes):
    """Only flag calendar-invalid or source-glued dates for human inspection."""
    findings = []
    for i, (raw, box) in enumerate(zip(texts, boxes)):
        for m in _DATE.finditer(raw):
            d, month, year = map(int, (m[1], m[3], m[4]))
            try:
                date(year, month, d)
                valid = 1900 <= year <= 2100
            except ValueError:
                valid = False
            suffix = raw[m.end():]
            glued = bool(suffix and suffix[0].isdigit() and _TIME.match(suffix))
            if valid and not glued:
                continue
            findings.append({
                'source_token_index': i, 'raw_text': raw, 'source_box': list(box),
                'original_text_span': [m.start(), m.end()], 'printed_date_substring': m.group(),
                'reason': 'date_time_glued' if valid else 'invalid_calendar_date',
                'proposed_replacement': None, 'human_review_required': True,
                'posted_or_approved': False,
            })
    return findings


def _r223():
    """Load only the trusted adjacent, staged source-row implementation."""
    path = Path(__file__).with_name('INVOICE_OCR_SOURCE_ROWS_R223.py')
    if not path.is_file():
        raise RuntimeError('Staged R223 source row module missing')
    spec = importlib.util.spec_from_file_location('_invoicevision_child_r223_staged', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load local staged R223 module')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def review(image, raw_tsv):
    """Review decoded source image + source TSV without changing either.

    The SHA is of the decoded frame bytes, NOT of the original uploaded JPEG.
    This difference is explicit so no source-pixel hash is misrepresented.
    """
    if not hasattr(image, 'shape') or len(image.shape) < 2:
        raise ValueError('Missing decoded image geometry')
    h, w = [int(x) for x in image.shape[:2]]
    if not 0 < h <= 30000 or not 0 < w <= 30000:
        raise ValueError('Invalid decoded source dimensions')
    texts, boxes, row_ids = _raw_tsv_observations(raw_tsv, w, h)
    # Operates on the already-loaded decoded frame, not re-encoded input.
    frame = image.tobytes(order='C')
    digest = hashlib.sha256(frame).hexdigest()
    case = {'file': 'CHILD_DECODED_FRAME_NOT_ORIGINAL_JPEG',
            'source_sha256': digest, 'source_width': w, 'source_height': h,
            'raw_texts': texts, 'raw_boxes': boxes}
    source_rows = _r223()
    rows = source_rows.propose(case, frame)
    # R229 is an optional auxiliary review, never a replacement for source
    # OCR or the existing Child zone classifications. Fail closed if absent.
    try:
        recovery_path = Path(__file__).with_name('INVOICE_OCR_LAYOUT_RECOVERY_R229.py')
        if not recovery_path.is_file():
            raise RuntimeError('R229 layout review module unavailable')
        spec = importlib.util.spec_from_file_location('_child_r229_layout_review', recovery_path)
        if spec is None or spec.loader is None:
            raise RuntimeError('Cannot load staged R229 source module')
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        recovered_rows = recovery.propose(case, frame, source_rows)
    except Exception as exc:
        recovered_rows = {'status':'REVIEW_UNAVAILABLE','error_type':type(exc).__name__,
                          'posting_eligible':False,'release_approved':False}
    date_flags=_date_flags(texts, boxes)
    try:
        if recovered_rows.get('status')=='REVIEW_UNAVAILABLE':
            raise RuntimeError('R229 review unavailable, cannot safely build queue')
        path=Path(__file__).with_name('INVOICE_OCR_REVIEW_QUEUE_R231.py')
        spec=importlib.util.spec_from_file_location('_child_review_queue_r231',path)
        if spec is None or spec.loader is None:
            raise RuntimeError('R231 manual-review queue module unavailable')
        queue_module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(queue_module)
        queue=queue_module.build(case,rows,recovered_rows,date_flags)
    except Exception as exc:
        queue={'status':'REVIEW_UNAVAILABLE','error_type':type(exc).__name__,
               'posting_eligible':False,'accounting_write_permitted':False,
               'release_approved':False}
    try:
        consistency_path=Path(__file__).with_name('INVOICE_OCR_FIELD_CONSISTENCY_R235.py')
        spec=importlib.util.spec_from_file_location('_child_r235_field_consistency',consistency_path)
        if spec is None or spec.loader is None:
            raise RuntimeError('R235 field evidence module unavailable')
        consistency_module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consistency_module)
        consistency=consistency_module.inspect(texts,boxes)
    except Exception as exc:
        consistency={'status':'REVIEW_UNAVAILABLE',
                     'error_type':type(exc).__name__,
                     'posting_eligible':False,
                     'accounting_write_permitted':False,
                     'release_approved':False}
    # R236: inspect only OCR source cells near an actual quantity heading.
    # The optional secondary backend is local-only; no model download, cloud
    # calls, automatic digit replacement or accounting permission.
    targeted={'status':'NUMERIC_RECHECK_NOT_AVAILABLE','hints':[],
              'rereads':[],'posting_eligible':False,'release_approved':False}
    try:
        import os
        import shutil
        import subprocess
        path=Path(__file__).with_name('INVOICE_OCR_TARGETED_RECHECK_R236.py')
        spec=importlib.util.spec_from_file_location('_child_r236_source_recheck',path)
        if spec is None or spec.loader is None:
            raise RuntimeError('Source crop recheck module missing')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hints=module.numeric_quantity_candidates(texts,boxes,max_candidates=6)
        targeted['hints']=hints
        targeted['status']='SOURCE_CROP_RECHECK_HINTS_REVIEW_ONLY'
        if os.environ.get('INVOICEVISION_R236_TARGETED_RECHECK')=='1' and hints:
            exe=shutil.which('tesseract')
            if exe:
                def local_reader(crop,psm):
                    import cv2
                    ok,png=cv2.imencode('.png',crop)
                    if not ok:raise RuntimeError('Cannot encode local OCR crop')
                    answer=subprocess.run(
                        [exe,'stdin','stdout','--psm',str(psm),'-l','eng',
                         '-c','tessedit_char_whitelist=0123456789.'],
                        input=png.tobytes(),capture_output=True,timeout=8,
                        check=False)
                    if answer.returncode!=0:
                        raise RuntimeError('Local OCR backend rejected crop')
                    return answer.stdout.decode('utf-8',errors='replace').strip()
                for hint in hints[:4]:
                    try:
                        rec=module.reread(image,hint['original_ocr_text'],
                                          hint['source_box'],hint['suggested_rotation'],
                                          local_reader)
                        rec['source_token_index']=hint['source_token_index']
                        rec['header_source_token_index']=hint['header_source_token_index']
                        targeted['rereads'].append(rec)
                        if rec['candidate_disagrees_with_original']:
                            consistency.setdefault('warnings',[]).append({
                                'issue':'SOURCE_QUANTITY_LOCAL_RECHECK_DIFFERENCE',
                                'source_token_index':hint['source_token_index'],
                                'original_source_box':hint['source_box'],
                                'raw_ocr_text':hint['original_ocr_text'],
                                'reread_candidate_for_review':
                                    rec['correlated_consensus_candidate'],
                                'source_backend_independent_ground_truth':False,
                                'requires_original_print_review':True,
                                'posting_eligible':False,'field_value_certified':False})
                    except Exception as exc:
                        targeted['rereads'].append({
                            'status':'RECHECK_UNAVAILABLE',
                            'source_token_index':hint['source_token_index'],
                            'error_type':type(exc).__name__,
                            'posting_eligible':False})
                targeted['status']='LOCAL_CROP_REREADS_REVIEW_ONLY'
            else:
                targeted['status']='LOCAL_SECONDARY_OCR_NOT_INSTALLED'
        if consistency.get('status')=='SOURCE_EVIDENCE_CONSISTENCY_REVIEW_ONLY':
            consistency['warnings_count']=len(consistency.get('warnings',[]))
    except Exception as exc:
        targeted={'status':'RECHECK_UNAVAILABLE','error_type':type(exc).__name__,
                  'hints':[],'rereads':[],'posting_eligible':False,
                  'release_approved':False}
    # R237 source-bound field associations: literal OCR substrings only,
    # never an approved or altered invoice field.
    try:
        association_path=Path(__file__).with_name('INVOICE_OCR_SOURCE_FIELD_ASSOCIATIONS_R237.py')
        spec=importlib.util.spec_from_file_location('_child_r237_source_associations',association_path)
        if spec is None or spec.loader is None:
            raise RuntimeError('R237 source field module unavailable')
        associations_module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(associations_module)
        source_associations=associations_module.propose(texts,boxes,w,h)
    except Exception as exc:
        source_associations={
            'status':'REVIEW_UNAVAILABLE','error_type':type(exc).__name__,
            'proposals':[],'posting_eligible':False,'release_approved':False}
    # Read-only local QR corroboration; never release raw/sensitive QR payload.
    try:
        p=Path(__file__).with_name('INVOICE_OCR_QR_REVIEW_R238.py')
        spec=importlib.util.spec_from_file_location('_child_source_qr_r238',p)
        if spec is None or spec.loader is None:
            raise RuntimeError('QR source crosscheck unavailable')
        qr_module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qr_module)
        qr_source_review=qr_module.review(image)
    except Exception as exc:
        qr_source_review={'status':'SOURCE_QR_REVIEW_UNAVAILABLE',
                          'error_type':type(exc).__name__,
                          'qr_invoice_id_candidates':[],
                          'invoice_number_certified':False,
                          'posting_eligible':False,
                          'release_approved':False}
    return {
        'status': 'UNVERIFIED_SOURCE_GEOMETRY_REVIEW_ONLY',
        'source_kind': 'decoded_child_image_frame',
        'decoded_frame_sha256': digest, 'original_jpeg_sha256_verified': False,
        'source_observations': len(texts), 'source_tsv_row_numbers': row_ids,
        'unmodified_tsv': True, 'unmodified_image': True,
        'row_hypotheses': rows, 'layout_recovery_review': recovered_rows,
        'date_flags': date_flags,
        'manual_review_queue': queue,
        'field_consistency_review': consistency,
        'targeted_numeric_source_review': targeted,
        'source_field_associations': source_associations,
        'qr_invoice_crosscheck': qr_source_review,
        'all_values_require_human_review': True,
        'field_accuracy_certified': False,
        'posting_eligible': False, 'accounting_write_permitted': False,
        'release_approved': False,
    }
