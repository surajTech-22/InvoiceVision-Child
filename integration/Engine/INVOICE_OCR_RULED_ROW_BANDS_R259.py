"""R259: inspect repeated physical ruled-table rows on immutable source pixels.

No source OCR values, line-item fields, or accounting records are written. An
inferred row boundary is geometrical evidence, not a verified printed cell.
"""
from __future__ import annotations
import hashlib
import re
from statistics import median


def _words(variants, width, height):
    if not isinstance(variants, list) or len(variants) != 2:
        raise ValueError('Two original-coordinate OCR source views required')
    ans = []
    seen = set()
    for view in variants:
        if (not isinstance(view, dict) or view.get('posting_eligible') is not False
            or view.get('source_boxes_are_original_pixels') is not True
            or not isinstance(view.get('variant'), str) or view['variant'] in seen):
            raise ValueError('Untrusted source-view provenance')
        seen.add(view['variant'])
        wds = view.get('source_words')
        if not isinstance(wds,list) or len(wds) > 480:
            raise ValueError('Unbounded source evidence')
        for idx, obs in enumerate(wds):
            b=obs.get('original_source_box') if isinstance(obs,dict) else None
            t=obs.get('original_source_text') if isinstance(obs,dict) else None
            if (not isinstance(t,str) or not t.strip() or len(t)>1500 or
                not isinstance(b,list) or len(b)!=4 or
                any(type(v)!=int for v in b) or
                not (0<=b[0]<b[2]<=width and 0<=b[1]<b[3]<=height)):
                raise ValueError('Malformed source OCR rectangle')
            ans.append({'text':t.strip(),'box':b,'view':view['variant'],'index':idx})
    return ans


def _center(word):
    b=word['box'];return ((b[0]+b[2])/2,(b[1]+b[3])/2)


def review(image, variants, reader=None, max_rows=12):
    """Return bounded, unapproved source row-band hypotheses.

    reader is an OPTIONAL callback accepting (temporary crop image, psm)
    and returning Tesseract TSV. OCR crop words remain separate from original
    first-pass words and are explicitly unverified. No accounting posting.
    """
    import cv2
    import numpy as np
    if not hasattr(image,'shape') or image.ndim!=3 or image.shape[2]!=3:
        raise ValueError('Original oriented BGR frame required')
    h,w=image.shape[:2]
    if not (180<=h<=6000 and 180<=w<=6000 and h*w<=24_000_000 and 1<=max_rows<=12):
        raise ValueError('Unsafe frame size or row limit')
    if reader is not None and not callable(reader):
        raise ValueError('Invalid read-only OCR callback')
    sha=hashlib.sha256(image.tobytes()).hexdigest()
    words=_words(variants,w,h)
    result={'status':'NO_SOURCE_RULED_TABLE_IDENTIFIED',
            'source_decoded_sha256':sha,'row_bands':[],
            'detected_physical_row_bands':0,'verified_item_rows':0,
            'source_pixels_modified':False,'first_pass_ocr_modified':False,
            'accounting_write_permitted':False,'posting_eligible':False,
            'release_approved':False}
    descriptions=[q for q in words if re.fullmatch(r'(?i:PRODUCT|DESCRIPTION|PARTICULARS)',q['text'].strip(' :;.,'))]
    # A repeated printed item grid must expose genuine *spatially separate*
    # source descriptions, quantity and amount/total headings.
    quantities=[q for q in words if re.fullmatch(r'(?i:PCS|PES|QTY|QUANTITY)',q['text'].strip(' :;.,'))]
    amounts=[q for q in words if re.fullmatch(r'(?i:TAXABLE|AMOUNT|NET)',q['text'].strip(' :;.,'))]
    footer=[q for q in words if re.fullmatch(r'(?i:TOTAL|SUBTOTAL)',q['text'].strip(' :;.,'))]
    headers=[]
    for d in descriptions:
        dx,dy=_center(d)
        for q in quantities:
            qx,qy=_center(q)
            if not (dx+45<qx and abs(dy-qy)<38):continue
            for a in amounts:
                ax,ay=_center(a)
                if not(qx+75<ax and abs(dy-ay)<40):continue
                trailing=[f for f in footer if f['box'][0] < dx and _center(f)[1]>max(dy,qy,ay)+60]
                if not trailing:continue
                stop=min(trailing,key=lambda f:_center(f)[1])
                headers.append((d,q,a,stop))
    if not headers:return result
    # Prefer the leftmost source-printed product heading; labels from two OCR
    # modes may duplicate but no supplier words or print values are hardcoded.
    d,q,a,stop=min(headers,key=lambda item:(item[0]['box'][0],_center(item[0])[1]))
    header_bottom=max(d['box'][3],q['box'][3],a['box'][3])
    stop_top=stop['box'][1]
    if stop_top-header_bottom<72:
        return result
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    if float(gray.mean())<18 and float(gray.std())<6:
        raise ValueError('Unreadable dark source frame')
    fg=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                             cv2.THRESH_BINARY_INV,41,12)
    kw=max(80,min(180,round(w*.060)))
    ink=cv2.morphologyEx(fg,cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT,(kw,1)))
    _,_,stats,_=cv2.connectedComponentsWithStats(ink,8)
    right=[];left=[]
    for x,y,ww,hh,area in stats[1:]:
        if (ww<kw or hh>5 or y <= header_bottom+8 or
            y>=stop_top-8):continue
        # Require source-printed line evidence in a distinct amount region.
        if x+ww > a['box'][0]-min(150,w*.10) and x < w*.97:
            right.append((float(y)+(hh-1)/2,int(ww),int(x)))
        if x < d['box'][0]+25 and x+ww>d['box'][0]-50:
            left.append((float(y)+(hh-1)/2,int(ww),int(x)))
    right.sort()
    # Coalesce slightly sloped right-column rulings into one source divider.
    groups=[]
    for item in right:
        if groups and item[0]-groups[-1][-1][0]<=5:
            groups[-1].append(item)
        else: groups.append([item])
    ruler=[sum(yy*weight for yy,weight,_ in g)/sum(weight for _,weight,_ in g)
           for g in groups if sum(weight for _,weight,_ in g)>=max(130,w*.09)]
    if len(ruler)<4 or len(ruler)>max_rows+1:
        return result
    pitch=median([b-a for a,b in zip(ruler,ruler[1:])])
    if not (12<=pitch<=70):return result
    if any(abs((b-a)-pitch)>max(5,pitch*.31) for a,b in zip(ruler,ruler[1:])):
        return result
    # Top source-boundary is only an extrapolated estimate, not printed truth.
    ruler=[max(float(header_bottom-6),ruler[0]-pitch)]+ruler
    if len(ruler)-1>max_rows:return result
    left_levels=[]
    left_witness=[]
    for idx,y in enumerate(ruler[1:]):
        predicted=(left_levels[-1]+(y-ruler[idx])
                   if left_levels and left_levels[-1] is not None else y+3)
        candidates=[v for v in left if abs(v[0]-y)<=max(14,pitch*.75)
                    and abs(v[0]-predicted)<=max(7,pitch*.48)]
        if candidates:
            # Prefer the *next* repeating ruling at the expected local pitch,
            # not an earlier longer segment which would collapse two rows.
            chosen=min(candidates,key=lambda t:(abs(t[0]-predicted),-t[1]))
            left_levels.append(chosen[0]);left_witness.append(True)
        else:left_levels.append(None);left_witness.append(False)
    if sum(v is not None for v in left_levels)<max(3,len(left_levels)*.55):
        return result
    # Missing left evidence is extrapolated from the detected row pitch;
    # never represent that edge as an observed source ruling.
    left_all=[]
    for i,(y,v) in enumerate(zip(ruler[1:],left_levels)):
        left_all.append((left_all[-1]+(y-ruler[i])
                         if left_all else y+3) if v is None else v)
    left_levels=[left_all[0]-pitch]+left_all
    dx0=max(0,int(d['box'][0]-min(140,w*.10)))
    dx1=min(w,int(q['box'][0]-max(30,w*.06)))
    if dx1-dx0<80:return result
    # Widen back to the product/right description boundary if UPC is OCRed.
    colmark=[t for t in words if t['text'].upper().strip(' :;.,')=='UPC'
             and _center(t)[0]>_center(d)[0]+45 and abs(_center(t)[1]-_center(d)[1])<50]
    if colmark:dx1=min(dx1,min(t['box'][0] for t in colmark)-8)
    if dx1-dx0<80:return result
    bands=[]
    for idx in range(len(ruler)-1):
        tr,br=ruler[idx:idx+2];tl,bl=left_levels[idx:idx+2]
        if min(br-tr,bl-tl)<8 or max(br-tr,bl-tl)>70:continue
        # Independent printed evidence: both repeated right-ruling and a
        # left-side ruling witness, or mark the latter inferred explicitly.
        # Right-line centers occur far beyond the description crop. Project
        # both observed separator heights to each crop edge rather than
        # copying a far-right y coordinate to the middle of the table.
        xleft=float(d['box'][0]-110)
        xright=max(xleft+100,float(a['box'][0]+40))
        def at_x(yy_left,yy_right,x):
            return round(yy_left+(yy_right-yy_left)*(x-xleft)/(xright-xleft))
        quad=[[dx0,at_x(tl,tr,dx0)],[dx1,at_x(tl,tr,dx1)],
              [dx1,at_x(bl,br,dx1)],[dx0,at_x(bl,br,dx0)]]
        band={'row_number_is_proposal':idx+1,'source_description_quad':quad,
              'left_divider_source_detected':idx>0 and left_witness[idx-1],
              'right_divider_source_detected':idx>0,
              'source_values_verified':False,'description_fragment_only':True,
              'posting_eligible':False,'text_view_alternatives':[]}
        if reader is not None:
            pts=np.float32(quad)
            width=dx1-dx0; height=max(14,int(round((br-tr+bl-tl)/2)))
            dst=np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]])
            matrix=cv2.getPerspectiveTransform(pts,dst)
            temporary=cv2.warpPerspective(image,matrix,(width,height),
                                         flags=cv2.INTER_CUBIC,borderValue=(255,255,255))
            scaled=cv2.resize(temporary,None,fx=4,fy=4,interpolation=cv2.INTER_CUBIC)
            tsv=reader(scaled,7)
            # Bounded TSV words are evidence, not approved original text.
            if not isinstance(tsv,str) or len(tsv)>100_000:
                raise ValueError('Unsafe row-crop OCR output')
            import csv,io
            raw=list(csv.DictReader(io.StringIO(tsv),delimiter='\t'))
            literal=[r.get('text','').strip() for r in raw
                     if r.get('level')=='5' and r.get('text','').strip()]
            band['text_view_alternatives']=[{'source':'TEMP_RECTIFIED_DESCRIPTION_PSM7',
                 'original_description_ocr':' '.join(literal)[:240],
                 'source_word_count':len(literal),'source_pixel_quad':quad,
                 'field_value_verified':False,'posting_eligible':False}]
        bands.append(band)
    result.update(status='SOURCE_REPEATED_RULING_ROW_BANDS_REVIEW_ONLY',
                  row_bands=bands,detected_physical_row_bands=len(bands),
                  physical_divider_y_at_amount_column=[round(v,2) for v in ruler],
                  first_divider_top_extrapolated=True,
                  source_table_header_boxes={'description':d['box'],
                        'quantity':q['box'],'amount':a['box']},
                  source_table_footer_box=stop['box'])
    if hashlib.sha256(image.tobytes()).hexdigest()!=sha:
        raise RuntimeError('Original pixels mutated by row-band analysis')
    return result
