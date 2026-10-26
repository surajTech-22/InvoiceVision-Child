"""R230 strict source-text disagreement triage; never OCR repair or posting.

Reprocessing variants of ONE secondary engine are correlated, not independent
truth. Original source pixels, OCR digits and bounding boxes are not altered.
"""
import hashlib
import re
_DIGITS=re.compile(r'^\d{6,10}$')

def review(raw_source_token,variants,source_image_sha256,source_box):
    if not isinstance(raw_source_token,str) or not _DIGITS.fullmatch(raw_source_token):
        raise ValueError('Only original 6-to-10-digit OCR tokens may be reviewed')
    if not isinstance(variants,(dict,list,tuple)) or isinstance(variants,str):
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
    parsed=[re.sub(r'[^0-9]','',v) for v in reads]
    nonempty=[v for v in parsed if v]
    matches=sum(v==raw_source_token for v in nonempty)
    conflicts=len(nonempty)-matches
    status=('SECOND_ENGINE_NO_READINGS_REVIEW' if not nonempty else
            'SECOND_ENGINE_CONFLICT_REVIEW' if matches==0 else
            'CORRELATED_SECOND_ENGINE_AGREEMENT_REVIEW')
    return {'status':status,
            'source_token_sha256':hashlib.sha256(raw_source_token.encode()).hexdigest(),
            'source_image_sha256':source_image_sha256,'original_source_box':list(source_box),
            'secondary_total_variants':len(reads),
            'secondary_nonempty_variants':len(nonempty),
            'matching_secondary_variants':matches,
            'conflicting_secondary_variants':conflicts,
            'source_characters_certified':0,'source_text_replaced':False,
            'automatic_value_correction':False,'posting_eligible':False,
            'release_approved':False}
