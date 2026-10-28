"""R231 corrected HSN OCR disagreement triage, never OCR repair or posting.

All variants produced by one OCR engine are correlated observations, not
independent ground truth. Invalid OCR strings MUST NOT be stripped to form
apparently matching financial or HSN digits.
"""
import hashlib
import re

_SOURCE_DIGITS = re.compile(r'[0-9]{6,10}\Z')
_CLEAN_VIEW = re.compile(r'[0-9]+(?:[ .-][0-9]+)*\Z')


def _read_secondary(raw):
    """Return (digits, validity). Never manufacture digits from mixed text."""
    if not isinstance(raw, str):
        raise ValueError('Secondary OCR result must be text')
    clean = raw.strip()
    if not clean:
        return None, 'blank'
    if not _CLEAN_VIEW.fullmatch(clean):
        return None, 'invalid'
    digits = re.sub(r'[ .-]', '', clean)
    if not _SOURCE_DIGITS.fullmatch(digits):
        return None, 'invalid'
    return digits, 'valid'


def review(raw_source_token, variants, source_image_sha256, source_box):
    if not isinstance(raw_source_token, str) or not _SOURCE_DIGITS.fullmatch(raw_source_token):
        raise ValueError('Only original 6-to-10 ASCII-digit OCR tokens may be reviewed')
    if not isinstance(variants, (dict,list,tuple)) or isinstance(variants,str):
        raise ValueError('Second-engine variants must be a collection')
    if isinstance(variants,dict):
        if any(not isinstance(k,str) for k in variants):
            raise ValueError('Invalid OCR variant name')
        reads=list(variants.values())
    else:
        reads=list(variants)
    if len(reads)>64 or not all(isinstance(x,str) for x in reads):
        raise ValueError('Invalid or excessive OCR variants')
    if not isinstance(source_image_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}',source_image_sha256):
        raise ValueError('Source image SHA-256 required')
    if (not isinstance(source_box,(list,tuple)) or len(source_box)!=4 or
        any(type(x) is not int for x in source_box) or
        not 0<=source_box[0]<source_box[2] or not 0<=source_box[1]<source_box[3]):
        raise ValueError('Source rectangle invalid')
    parsed=[_read_secondary(s) for s in reads]
    valid=[digits for digits,kind in parsed if kind=='valid']
    matches=sum(s==raw_source_token for s in valid)
    conflicts=len(valid)-matches
    invalid=sum(kind=='invalid' for _,kind in parsed)
    blanks=sum(kind=='blank' for _,kind in parsed)
    if not valid:
        status='SECOND_ENGINE_INVALID_OUTPUT_REVIEW' if invalid else 'SECOND_ENGINE_NO_READINGS_REVIEW'
    elif conflicts:
        # One matching variant must never mask a different numeric reading.
        status='SECOND_ENGINE_MIXED_DISAGREEMENT_REVIEW' if matches else 'SECOND_ENGINE_CONFLICT_REVIEW'
    elif invalid:
        status='SECOND_ENGINE_INCOMPLETE_AGREEMENT_REVIEW'
    else:
        status='CORRELATED_SECOND_ENGINE_AGREEMENT_REVIEW'
    return {
        'status':status,
        'source_token_sha256':hashlib.sha256(raw_source_token.encode('ascii')).hexdigest(),
        'source_image_sha256':source_image_sha256,
        'original_source_box':list(source_box),
        'secondary_total_variants':len(reads),
        'secondary_nonempty_variants':len(valid),
        'secondary_invalid_variants':invalid,
        'secondary_blank_variants':blanks,
        'matching_secondary_variants':matches,
        'conflicting_secondary_variants':conflicts,
        'secondary_engine_views_independent':False,
        'source_characters_certified':0,
        'source_text_replaced':False,
        'automatic_value_correction':False,
        'human_source_review_required':True,
        'posting_eligible':False,
        'release_approved':False,
    }
