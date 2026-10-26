"""R235 source-only OCR field consistency checks — conservative, read-only.

Does not infer accepted invoice values. Preserves every original OCR token,
including suspicious years, glued HSN digits and adjacent printed tax columns.
No corrections, posting, amount changes or certification.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import re

_DATE = re.compile(r'(?<![0-9])(\d{2})([/.-])(\d{2})\2(\d{4})')
_POSSIBLE_SERIAL_HSN = re.compile(r'^([1-9])([0-9]{8})\s+(.{5,})$')
_TWO_ADJACENT_AMOUNTS = re.compile(r'^([0-9]{1,9}\.[0-9]{2})([0-9]{1,9}\.[0-9]{2})$')
_SIMPLE_NUMBER = re.compile(r'^[0-9]+(?:\.[0-9]{1,4})?$')


def _warn(index, box, kind, raw, **additional):
    return {
        'source_token_index': index,
        'original_source_box': list(box),
        'raw_ocr_text': raw,
        'issue': kind,
        'requires_original_print_review': True,
        'ocr_source_text_modified': False,
        'field_value_certified': False,
        'posting_eligible': False,
        **additional
    }


def inspect(texts, boxes):
    if not isinstance(texts, list) or not isinstance(boxes, list) or len(texts) != len(boxes):
        raise ValueError('Source OCR token/box mismatch')
    if len(texts) > 20000:
        raise ValueError('Excessive source OCR observations')
    warnings, dates = [], []
    for i, (raw, box) in enumerate(zip(texts, boxes)):
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 4000:
            raise ValueError('Source OCR text missing or invalid')
        if not isinstance(box, list) or len(box) != 4 or not all(type(n) is int for n in box):
            raise ValueError('Source box invalid')
        if not (0 <= box[0] < box[2] and 0 <= box[1] < box[3]):
            raise ValueError('Source box is not positive')
        for m in _DATE.finditer(raw):
            try:
                parsed = date(int(m.group(4)), int(m.group(3)), int(m.group(1)))
            except ValueError:
                warnings.append(_warn(i, box, 'INVALID_SOURCE_DATE', raw,
                                      original_date_text=m.group(0)))
                continue
            dates.append((i, box, raw, parsed, m.group(0)))
        sm = _POSSIBLE_SERIAL_HSN.match(raw)
        if sm:
            warnings.append(_warn(i, box, 'NINE_DIGIT_HSN_WITH_POSSIBLE_LEADING_SERIAL', raw,
                                  candidate_hsn_for_review=sm.group(2),
                                  stripped_leading_character=sm.group(1),
                                  source_value_not_replaced=True))
        mt = _TWO_ADJACENT_AMOUNTS.match(raw)
        if mt:
            warnings.append(_warn(i, box, 'TWO_DECIMAL_AMOUNTS_JOINED_IN_OCR', raw,
                                  two_original_source_substrings=[mt.group(1), mt.group(2)],
                                  numeric_columns_not_approved=True))
    # Identical day and month but different years may be distinct legitimately
    # printed fields (bill date vs e-invoice date). Never choose one automatically.
    for i, (idx, box, raw, dt, rawdate) in enumerate(dates):
        if any(dt.day == other.day and dt.month == other.month and dt.year != other.year
               for j, (_, _, _, other, _) in enumerate(dates) if j != i):
            warnings.append(_warn(idx, box, 'SOURCE_DATE_YEAR_DIFFERENCE_REQUIRES_CONTEXT', raw,
                                  original_date_text=rawdate,
                                  other_date_fields_may_be_legitimate=True))
    return {
        'status': 'SOURCE_EVIDENCE_CONSISTENCY_REVIEW_ONLY',
        'source_tokens_checked': len(texts),
        'source_date_strings': len(dates),
        'warnings': warnings,
        'warnings_count': len(warnings),
        'source_text_preserved': True,
        'source_boxes_preserved': True,
        'automatic_field_replacement': False,
        'field_accuracy_certified': False,
        'accounting_write_permitted': False,
        'posting_eligible': False,
        'release_approved': False,
    }


def check_line_amount(raw_qty, raw_rate, raw_total):
    """Arithmetic warning only for *explicitly field-mapped* source tokens.

    Never call on an arbitrary triplet of nearby OCR numbers. The original
    quantity and total are preserved even when a better integer candidate
    can be proposed for manual review.
    """
    strings=(raw_qty,raw_rate,raw_total)
    if any(not isinstance(s,str) or not _SIMPLE_NUMBER.fullmatch(s) for s in strings):
        raise ValueError('Unmapped or invalid positive numeric OCR fields')
    qty, rate, total = [Decimal(s) for s in strings]
    if not (0 < qty <= 100000 and 0 < rate <= 10000000 and 0 <= total <= 1000000000):
        raise ValueError('Outside bounded invoice numeric domain')
    observed = qty * rate
    residual = abs(observed-total)
    # Rates may already be rounded on paper: allow +/- 0.01 per original
    # unit for review, but not as proof of a correct field.
    acceptable = Decimal('0.01') * qty + Decimal('0.02')
    candidate = (total/rate).quantize(Decimal('1'))
    alternative = (
        str(candidate) if candidate > 0 and candidate != qty and
        abs(rate * candidate-total) <= Decimal('0.01')*candidate+Decimal('0.02')
        else None
    )
    return {'status':'ARITHMETIC_SOURCE_REVIEW_ONLY',
            'printed_or_ocr_qty_as_supplied':raw_qty,
            'printed_or_ocr_rate_as_supplied':raw_rate,
            'printed_or_ocr_line_total_as_supplied':raw_total,
            'multiplication_residual':str(residual),
            'arithmetic_plausible':residual<=acceptable,
            'quantity_candidate_for_human_review':alternative,
            'original_field_value_replaced':False,
            'field_accuracy_certified':False,
            'posting_eligible':False,
            'release_approved':False}
