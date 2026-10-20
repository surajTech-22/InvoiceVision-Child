"""Coordinate-linked field hypotheses. Agreement is never pixel verification."""
from __future__ import annotations
from datetime import datetime
import hashlib
import math
import re
from .r138_field_evidence import box_of, reconstruct, DATE
from .r141_inline_field_evidence import parse_inline


def valid_date(value):
    for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%Y-%m-%d',
                '%Y/%m/%d', '%Y.%m.%d', '%d-%b-%Y', '%d/%b/%Y',
                '%d.%b.%Y', '%d-%B-%Y', '%d/%B/%Y', '%d.%B.%Y'):
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


def inspect(case, engine, source_bytes=None):
    sha = case.get('source_sha256', '')
    if not re.fullmatch('[0-9a-f]{64}', sha):
        raise ValueError('Missing original SHA-256')
    if source_bytes is not None and hashlib.sha256(source_bytes).hexdigest() != sha:
        raise ValueError('Original source bytes do not match OCR evidence')
    width, height = case.get('source_width'), case.get('source_height')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or v <= 0 for v in (width, height)):
        raise ValueError('Invalid source coordinate space')
    texts, boxes = case.get('raw_texts', []), case.get('raw_boxes', [])
    valid = {}
    issues = []
    for i, text in enumerate(texts):
        box = box_of(boxes[i]) if i < len(boxes) else None
        if box is None or box[2] > width or box[3] > height:
            issues.append({'index': i, 'text': text, 'reason': 'NO_VALID_SOURCE_BOX'})
        else:
            valid[i] = box
    if len(boxes) > len(texts):
        issues.append({'reason': 'EXTRA_BOXES_WITHOUT_TEXT', 'count': len(boxes)-len(texts)})
    candidates = []

    def add(field, value, indices, evidence):
        if any(i not in valid for i in indices):
            return
        if field == 'invoice_date' and not valid_date(value):
            issues.append({'reason': 'INVALID_OR_UNSUPPORTED_CALENDAR_DATE',
                           'value': value, 'source_tokens': indices})
            return
        reason = None
        if field == 'invoice_number':
            if DATE.search(value) or len(value) > 64 or re.search(
                r'\b(?:address|pin\s*code|salesperson|beat|pan|gstin|state|customer|supplier|distributor|po\s*no)\b',value,re.I):
                reason = 'COMPETING_FIELD_OR_PROSE_NOT_INVOICE_NUMBER'
        if field in ('supplier','buyer','consignee'):
            if re.fullmatch(r'\W*(?:bill(?:ed)?\s*to|ship\s*to|from|to|buyer|supplier)\W*',value,re.I) or re.search(
                r'\b(?:address|pin\s*code|gstin|pan|order\s*id|customer\s*support|shipping)\b',value,re.I):
                reason = 'ADMINISTRATIVE_LABEL_NOT_PARTY_NAME'
        if reason:
            issues.append({'reason': reason, 'value': value, 'source_tokens': indices})
            return
        candidates.append({'field': field, 'raw_value': value, 'engine': engine,
            'source_sha256': sha, 'source_tokens': indices,
            'source_regions': [list(valid[i]) for i in indices],
            'raw_source_text': [texts[i] for i in indices], 'evidence': evidence,
            'validated_against_pixels': False, 'posting_eligible': False})

    for i, text in enumerate(texts):
        for row in parse_inline(text):
            add(row['field'], row['raw_value'], [i], row['evidence'])
    safe_case = dict(case)
    # Keep indices stable: invalid regions must not create nearby-field proposals.
    safe_case['raw_boxes'] = [valid.get(i, []) for i in range(len(texts))]
    for field, rows in reconstruct(safe_case, engine)['fields'].items():
        for row in rows:
            add(field, row['value'], row['source_tokens'], row['evidence'])
    unique = {}
    for row in candidates:
        key = row['field'], row['raw_value'], tuple(row['source_tokens'])
        unique.setdefault(key, row)
    return {'file': case.get('file'), 'source_sha256': sha,
            'source_size': [width, height], 'candidates': list(unique.values()),
            'issues': issues, 'posting_eligible': False, 'field_accuracy_verified': False}
