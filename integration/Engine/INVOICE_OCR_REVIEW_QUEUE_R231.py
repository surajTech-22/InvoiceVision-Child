"""R231 immutable-source manual review queue for InvoiceVision Child.

Turns provisional R223/R229 row groups and date warnings into individually
addressable review items for a future Child UI. It never certifies OCR text,
rewrites values, or authorizes exporting/accounting transactions.
"""
import hashlib
import json


def _source_record(case, indices, kind, ordinal, status='UNVERIFIED'):
    if not isinstance(indices,(list,tuple)) or not indices or len(set(indices))!=len(indices):
        raise ValueError('Review source indices must be unique within each item')
    texts=case['raw_texts'];boxes=case['raw_boxes']
    w=case['source_width'];h=case['source_height']
    members=[]
    for index in indices:
        if type(index) is not int or not 0<=index<len(texts):
            raise ValueError('Review source index invalid')
        b=boxes[index]
        if (not isinstance(b,(list,tuple)) or len(b)!=4 or
            any(type(x) not in (float,int) for x in b) or
            not 0<=b[0]<b[2]<=w or not 0<=b[1]<b[3]<=h):
            raise ValueError('Untrusted source rectangle')
        if not isinstance(texts[index],str) or not texts[index].strip():
            raise ValueError('Missing original OCR evidence')
        members.append({'source_token_index':index,
                        'original_box':list(b),'original_ocr_text':texts[index]})
    original_hash=case['source_sha256']
    if not isinstance(original_hash,str) or len(original_hash)!=64:
        raise ValueError('Missing decoded-source SHA256')
    identity=json.dumps([original_hash,kind,members],sort_keys=True,ensure_ascii=False,separators=(',',':'))
    digest=hashlib.sha256(identity.encode('utf-8')).hexdigest()
    return {'review_id':'IVR231-'+digest[:24],
            'review_kind':kind,'source_frame_sha256':original_hash,
            'original_uploaded_file_sha256_known':False,
            'source_token_indices':list(indices),
            'original_observations':members,
            'geometry_status':status,'review_required':True,
            'human_annotation':None,'field_value_verified':False,
            'physical_cells_verified':False,
            'posting_eligible':False,'automatic_correction_permitted':False,
            'release_approved':False}


def build(case,r223_rows,r229_recovery,date_flags):
    if (r223_rows.get('posting_eligible') is not False or
        r229_recovery.get('posting_eligible') is not False):
        raise ValueError('Unsafe input marked postable')
    merged={tuple(w['source_indices']) for w in r229_recovery.get('baseline_merged_row_warnings',[])}
    queue=[]
    for table in r223_rows.get('tables',[]):
        for row in table.get('rows',[]):
            if tuple(row['source_indices']) in merged:
                continue
            queue.append(_source_record(case,row['source_indices'],'ITEM_ROW_BASELINE',len(queue)))
    for table in r229_recovery.get('orientation_tables',[]):
        for row in table.get('rows',[]):
            queue.append(_source_record(case,row['source_indices'],'ITEM_ROW_SIDEWAYS',len(queue),
                                        'LOGICALLY_ROTATED_UNVERIFIED'))
    for row in r229_recovery.get('hsn_anchor_rows',[]):
        queue.append(_source_record(case,row['source_indices'],'ITEM_ROW_HSN_ANCHOR',len(queue)))
    counted=len(queue)
    if counted!=r229_recovery.get('total_provisional_rows'):
        raise ValueError('Item proposal count not consistent with original source evidence')
    for row in date_flags:
        queue.append(_source_record(case,[row['source_token_index']],'DATE_ANOMALY',len(queue)))
    unique={r['review_id'] for r in queue}
    if len(unique)!=len(queue):
        raise ValueError('Repeated identical source proposal; manual review would be ambiguous')
    return {'status':'IMMUTABLE_SOURCE_REVIEW_REQUIRED',
            'item_proposals':counted,'date_proposals':len(date_flags),
            'total_review_items':len(queue),'items':queue,
            'original_source_tokens_rewritten':False,
            'original_photo_bytes_changed':False,
            'user_approval_recorded':False,
            'accounting_write_permitted':False,'posting_eligible':False,
            'release_approved':False}
