"""R150 review-only punctuation normalization for sourced amount candidates.

Only remove label punctuation explicitly before a well-formed numeric token.
Do not round, invent missing digits, use close-number fuzzy matching, or post.
"""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation

MONEY = re.compile(r'^\s*(?::\s*)?(?:(?:INR|Rs\.?|₹)\s*)?([+-]?(?:\d{1,3}(?:,\d{3})+|\d{1,9})(?:\.\d{1,2})?)\s*$',re.I)

def parse_source_amount(text):
    original=str(text)
    match=MONEY.fullmatch(original)
    if not match:
        return {'raw_text':original,'accepted_numeric_syntax':False,
                'posting_eligible':False,'field_verified':False}
    numeric=match.group(1).replace(',','')
    try:
        value=Decimal(numeric)
        if not value.is_finite():raise InvalidOperation
    except InvalidOperation:
        return {'raw_text':original,'accepted_numeric_syntax':False,
                'posting_eligible':False,'field_verified':False}
    return {'raw_text':original,'candidate_exact_decimal':str(value),
            'normalization':'REMOVE_ONLY_SOURCE_LABEL_PREFIX_AND_THOUSAND_SEPARATOR',
            'accepted_numeric_syntax':True,'posting_eligible':False,
            'field_verified':False,'source_pixels_verified':False}

def compare_to_reference(raw, reference):
    candidate=parse_source_amount(raw)
    target=parse_source_amount(reference)
    if not candidate.get('accepted_numeric_syntax') or not target.get('accepted_numeric_syntax'):
        return {'exact_amount_candidate_match':False,'posting_eligible':False,
                'candidate':candidate}
    return {'exact_amount_candidate_match':
                Decimal(candidate['candidate_exact_decimal'])==Decimal(target['candidate_exact_decimal']),
            'posting_eligible':False,'candidate':candidate,
            'reference_used_only_for_research_audit':True}
