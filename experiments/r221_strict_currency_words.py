"""Source-only strict Indian currency amount-in-words parser (review aid).

Unknown/incomplete wording is not inferred. No image OCR or accounting writes.
"""
from __future__ import annotations
import re
from decimal import Decimal

_SMALL = {'ZERO': 0, 'ONE': 1, 'TWO': 2, 'THREE': 3, 'FOUR': 4,
          'FIVE': 5, 'SIX': 6, 'SEVEN': 7, 'EIGHT': 8, 'NINE': 9,
          'TEN': 10, 'ELEVEN': 11, 'TWELVE': 12, 'THIRTEEN': 13,
          'FOURTEEN': 14, 'FIFTEEN': 15, 'SIXTEEN': 16,
          'SEVENTEEN': 17, 'EIGHTEEN': 18, 'NINETEEN': 19}
_TENS = {'TWENTY': 20, 'THIRTY': 30, 'FORTY': 40, 'FIFTY': 50,
         'SIXTY': 60, 'SEVENTY': 70, 'EIGHTY': 80, 'NINETY': 90}
_SCALES = {'CRORE': 10000000, 'LAKH': 100000, 'THOUSAND': 1000}


def _below_hundred(tokens):
    if len(tokens) == 1:
        return _SMALL.get(tokens[0], _TENS.get(tokens[0]))
    if len(tokens) == 2 and tokens[0] in _TENS and tokens[1] in _SMALL and 1 <= _SMALL[tokens[1]] <= 9:
        return _TENS[tokens[0]] + _SMALL[tokens[1]]
    return None


def _below_thousand(tokens):
    if not tokens:
        return None
    if 'HUNDRED' not in tokens:
        return _below_hundred(tokens)
    if len(tokens) < 2 or tokens[1] != 'HUNDRED' or tokens[0] not in _SMALL or not 1 <= _SMALL[tokens[0]] <= 9:
        return None
    rest = tokens[2:]
    if rest and rest[0] == 'AND':
        rest = rest[1:]
        if not rest:
            return None
    if not rest:
        return _SMALL[tokens[0]] * 100
    extra = _below_hundred(rest)
    return _SMALL[tokens[0]] * 100 + extra if extra is not None else None


def _rupee_integer(tokens):
    if tokens == ['ZERO']:
        return 0
    if not tokens or 'ZERO' in tokens:
        return None
    total, start, previous_scale = 0, 0, float('inf')
    for idx, token in enumerate(tokens):
        if token not in _SCALES:
            continue
        scale = _SCALES[token]
        if scale >= previous_scale:
            return None
        group = _below_thousand(tokens[start:idx])
        if group is None or group == 0:
            return None
        total += group * scale
        start, previous_scale = idx + 1, scale
    last = tokens[start:]
    if last:
        group = _below_thousand(last)
        if group is None or group == 0:
            return None
        total += group
    return total if total > 0 else None


def parse_amount_words(raw):
    """Return exact rupees + paise Decimal or None; no fuzzy/OCR repairs."""
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r'\s+', ' ', raw.strip().upper())
    if not re.fullmatch(r'[A-Z ]+', cleaned):
        return None
    tokens = cleaned.split()
    if not tokens or tokens[0] != 'RUPEES':
        return None
    tokens = tokens[1:]
    if tokens and tokens[-1] == 'ONLY':
        tokens.pop()
    if not tokens or 'ONLY' in tokens or tokens.count('PAISE') > 1:
        return None
    paisa = 0
    if 'PAISE' in tokens:
        if tokens[-1] != 'PAISE':
            return None
        # Require explicit separator: 'AND FIFTY PAISE'.
        and_positions = [i for i,x in enumerate(tokens[:-1]) if x == 'AND']
        if not and_positions:
            return None
        pivot = and_positions[-1]
        p = _below_hundred(tokens[pivot+1:-1])
        if p is None or not 1 <= p <= 99:
            return None
        paisa = p
        tokens = tokens[:pivot]
    rupees = _rupee_integer(tokens)
    if rupees is None or rupees < 0:
        return None
    return Decimal(rupees) + Decimal(paisa) / 100
