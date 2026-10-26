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
    return {
        'status': 'UNVERIFIED_SOURCE_GEOMETRY_REVIEW_ONLY',
        'source_kind': 'decoded_child_image_frame',
        'decoded_frame_sha256': digest, 'original_jpeg_sha256_verified': False,
        'source_observations': len(texts), 'source_tsv_row_numbers': row_ids,
        'unmodified_tsv': True, 'unmodified_image': True,
        'row_hypotheses': rows, 'layout_recovery_review': recovered_rows,
        'date_flags': date_flags,
        'manual_review_queue': queue,
        'all_values_require_human_review': True,
        'field_accuracy_certified': False,
        'posting_eligible': False, 'accounting_write_permitted': False,
        'release_approved': False,
    }
