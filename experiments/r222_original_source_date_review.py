"""R222: photo-bound, review-only OCR date anomaly triage.

Uses the ORIGINAL JPEG bytes, source OCR text, and physical boxes; never
rewrites the OCR source or certifies a field. An optional local Tesseract pass
supports human-review proposals only. Accounting data must never be written.
"""
from __future__ import annotations

import hashlib
import math
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2

_DATE = re.compile(r'(?<!\d)(?P<day>\d{1,2})(?P<sep>[/.-])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4})')
_TIME = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?\b', re.I)


def parse_dates(text):
    """All dates, including invalid dates, in source order, without corrections."""
    found = []
    for m in _DATE.finditer(str(text)):
        date_str = m.group()
        day, month, year = int(m['day']), int(m['month']), int(m['year'])
        valid = 1900 <= year <= 2100
        if valid:
            try:
                datetime(year, month, day)
            except ValueError:
                valid = False
        after = str(text)[m.end():]
        glued_time = bool(_TIME.match(after)) and m.end() < len(str(text)) and after[0].isdigit()
        found.append({'original_date': date_str, 'original_start': m.start(),
                      'original_end': m.end(), 'valid': valid,
                      'glued_time': glued_time, 'day': day, 'month': month, 'year': year,
                      'separator': m['sep']})
    return found


def _box(box, w, h):
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or
        any(type(n) not in (int, float) or not math.isfinite(n) for n in box) or
        not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)):
        raise ValueError('Invalid original source OCR box')
    return box


def _variants(image, box):
    """Two non-rotating original-pixel preprocessing views + original grayscale.

    Note: these are CORRELATED passes of a single OCR engine, not independent
    model confirmations; confidence is never represented as ground truth.
    """
    h, w = image.shape[:2]
    x0, y0, x1, y1 = map(int, box)
    sideways = (y1-y0) >= 1.55*(x1-x0)
    if sideways:
        padx = max(25, round((x1-x0)*1.3))
        pady = max(10, round((y1-y0)*.12))
    else:
        padx = max(8, round((x1-x0)*.08))
        pady = max(7, round((y1-y0)*.35))
    roi = image[max(0,y0-pady):min(h,y1+pady), max(0,x0-padx):min(w,x1+padx)]
    if sideways:
        # Derived OCR view only. The original pixels/coordinates remain unchanged.
        roi = cv2.rotate(roi, cv2.ROTATE_90_COUNTERCLOCKWISE)
    enlarged = cv2.resize(roi, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    grey = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(grey)
    return {'original_scale': enlarged, 'local_contrast': clahe}


def _tesseract(image):
    encoded, raw = cv2.imencode('.png', image)
    if not encoded:
        return ''
    # No network dependency. Executable must already be installed locally.
    result = subprocess.run(
        ['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '6'],
        input=raw.tobytes(), capture_output=True, timeout=15, check=False)
    return result.stdout.decode('utf-8', errors='replace') if result.returncode == 0 else ''


def _near_source(original, alternative):
    """For a damaged source date, only propose a nearby SAME-YEAR candidate."""
    if original['separator'] != alternative['separator']:
        return False
    a = original['original_date']; b = alternative['original_date']
    if len(a) != len(b) or sum(x != y for x, y in zip(a,b)) > 2:
        return False
    if original['valid']:
        # Stronger rule when a plausible printed year is at odds with OCR:
        # same day/month, and only a one-digit year disagreement.
        return (original['day'],original['month']) == (alternative['day'],alternative['month'])
    return original['year'] == alternative['year']


def review(case, photo_bytes, ocr=None):
    """Return date proposals/flags with immutable source evidence; never posting."""
    if hashlib.sha256(photo_bytes).hexdigest() != case['source_sha256']:
        raise ValueError('Source-image SHA-256 mismatch')
    img = cv2.imdecode(__import__('numpy').frombuffer(photo_bytes, dtype='uint8'), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError('Cannot decode ORIGINAL source photo')
    h, w = img.shape[:2]
    if (w, h) != (case['source_width'], case['source_height']):
        raise ValueError('Original source image dimensions do not match OCR report')
    texts, boxes = case['raw_texts'], case['raw_boxes']
    if len(texts) != len(boxes):
        raise ValueError('Source OCR observation count mismatch')
    for box in boxes:
        _box(box, w, h)
    ocr = _tesseract if ocr is None else ocr
    rows = []
    for idx, (raw, box) in enumerate(zip(texts, boxes)):
        dates = parse_dates(raw)
        for date in dates:
            if date['valid'] and not date['glued_time']:
                continue
            entry = {
                'source_token_index': idx,
                'source_raw_text': raw,
                'source_original_box': list(box),
                'source_original_date_span': [date['original_start'],date['original_end']],
                'issue': ('date_time_glued' if date['valid'] else 'invalid_calendar_date'),
                'original_image_sha256': case['source_sha256'],
                'source_image_unchanged': True,
                'raw_ocr_text_unchanged': True,
                'accounting_write_permitted': False,
                'human_review_required': True,
                'suggested_date': None,
                'second_pass_outputs': {},
                'status': 'no_supported_alternative',
            }
            if date['valid']:
                # A calendar-valid OCR date can still be wrong (e.g. 2025/2026).
                # Until two correlated views agree on a different date, the only
                # 'split' is a reversible span boundary in original source text.
                entry['suggested_date'] = date['original_date']
                entry['status'] = 'original_date_span_only'
            evidence = Counter()
            for name, image in _variants(img, box).items():
                try:
                    output = str(ocr(image))
                except (OSError, subprocess.TimeoutExpired, ValueError):
                    output = ''
                entry['second_pass_outputs'][name] = output[:512]
                # An ambiguous OCR output containing multiple differing nearby
                # valid dates is not a vote for any one candidate.
                candidates = {d['original_date'] for d in parse_dates(output)
                              if d['valid'] and _near_source(date, d)}
                if len(candidates) == 1:
                    evidence[next(iter(candidates))] += 1
            if len(evidence) == 1 and next(iter(evidence.values())) == 2:
                candidate = next(iter(evidence))
                if candidate != date['original_date']:
                    entry['suggested_date'] = candidate
                    entry['status'] = ('correlated_ocr_date_conflict_review' if date['valid']
                                       else 'correlated_ocr_review_proposal')
            elif len(evidence) > 1:
                entry['suggested_date'] = None
                entry['status'] = 'conflicting_second_pass_dates'
            rows.append(entry)
    return {'photo': case['file'], 'original_sha256': case['source_sha256'],
            'source_token_count': len(texts), 'date_anomaly_count': len(rows),
            'source_tokens_preserved': True, 'approved_training_labels': 0,
            'certified_characters': 0, 'posting_eligible': False,
            'release_approved': False, 'proposals': rows}
