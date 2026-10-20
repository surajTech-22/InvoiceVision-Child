#!/usr/bin/env python3
"""Source-coordinate PaddleOCR 3.x adapter for InvoiceVision Child.

Never treats OCR values as verified invoice truth. Converts detected line polygons
into Tesseract-compatible TSV rows for the existing recursive zone analyzer.
All inference uses local image arrays. No cloud API, accounting side effects,
or image modifications. Source images are not overwritten.
"""
import importlib.util
import os
import math
import re
from pathlib import Path

_instance=None
_gpu_instance=None
_gpu_failed=False

def present():
    return importlib.util.find_spec('paddleocr') is not None and importlib.util.find_spec('paddle') is not None

def _pipeline(device='cpu'):
    global _instance, _gpu_instance
    if device not in ('cpu','gpu:0'):
        raise ValueError('Unsupported OCR device')
    cached = _instance if device == 'cpu' else _gpu_instance
    if cached is None:
        if device == 'gpu:0':
            # PaddleX silently substitutes CPU for an unavailable GPU. Check
            # capability first so diagnostics never claim CPU work ran on GPU.
            import paddle
            if not paddle.device.is_compiled_with_cuda() or paddle.device.cuda.device_count()<1:
                raise RuntimeError('Requested CUDA GPU is unavailable in this runtime')
        # Avoid surprise model-host probing if cached models exist. PaddleX may
        # fetch model weights on first initialization if they have not been cached;
        # the dedicated Windows verifier checks for this before certification.
        from paddleocr import PaddleOCR
        # CRITICAL: PaddlePaddle 3.3.0/3.3.1 CPU oneDNN regression (PIR
        # ArrayAttribute<DoubleAttribute>) crashes PP-OCRv6 during inference.
        # The flag must be set on PaddleOCR itself; environment-only flags can
        # be silently overridden by PaddleX's default MKLDNN runner.
        # This is an inference setting, not a model/data transformation.
        # Explicit, documented small CPU models; never download/use a heavy
        # default OCRv6 model without the operator knowing which model ran.
        # The Windows verifier records model-init and per-invoice progress.
        cached=PaddleOCR(use_doc_orientation_classify=False,
                            use_doc_unwarping=False,use_textline_orientation=False,
                            text_detection_model_name='PP-OCRv5_mobile_det',
                            text_recognition_model_name='PP-OCRv5_mobile_rec',
                            enable_mkldnn=False, cpu_threads=4,
                            text_recognition_batch_size=1,
                            device=device)
        if device == 'cpu': _instance=cached
        else: _gpu_instance=cached
    return cached


def _recognize_tile(work, width, height, args, progress=None):
    # GPU is opt-in. A failed GPU is not re-created for every tile/invoice.
    # Materialize and validate the entire tile before accepting partial output.
    global _gpu_failed, _gpu_instance
    preference=os.environ.get('INVOICEVISION_OCR_DEVICE','cpu').strip().lower()
    if preference not in ('cpu','auto','gpu'):
        raise ValueError('INVOICEVISION_OCR_DEVICE must be cpu, auto or gpu')
    devices=['gpu:0','cpu'] if preference != 'cpu' and not _gpu_failed else ['cpu']
    for device in devices:
        try:
            result=[]
            page_count=0
            for res in _pipeline(device).predict(input=work, **args):
                page_count+=1
                if page_count>1: raise ValueError("Multiple OCR pages returned for one source tile")
                result.extend(normalized_lines(res,width,height))
            if page_count!=1: raise ValueError("OCR backend returned no result for source tile")
            if progress: progress('OCR_BACKEND_COMPLETE', device=device, fallback_used=_gpu_failed)
            return result
        except Exception as exc:
            if progress: progress('OCR_BACKEND_FAILED', device=device, error_type=type(exc).__name__, message=str(exc)[:300])
            if device == 'cpu': raise
            _gpu_failed=True
            _gpu_instance=None
    raise RuntimeError('No local OCR backend completed')

def normalized_lines(result, w, h):
    """Read official PP-OCR v3 result metadata; preserve text and source boxes."""
    payload=getattr(result,'json',result)
    if callable(payload): payload=payload()
    if isinstance(payload,dict):
        payload=payload.get('res',payload)
    if not isinstance(payload,dict): raise ValueError('PaddleOCR v3 metadata is not a dictionary')
    def sequence(value, name):
        if hasattr(value, 'tolist'): value=value.tolist()
        if not isinstance(value, (list, tuple)):
            raise ValueError('PaddleOCR missing or invalid '+name)
        return value
    texts=sequence(payload.get('rec_texts'), 'rec_texts')
    scores=sequence(payload.get('rec_scores'), 'rec_scores')
    boxes=payload.get('rec_polys')
    if boxes is None: boxes=payload.get('rec_boxes')
    # Detection polygons need not align with recognition after score filtering.
    # Never assign a recognized value to a dt_polys position by array index.
    boxes=sequence(boxes, 'recognized-text positions')
    if len(texts)!=len(scores) or len(texts)!=len(boxes):
        raise ValueError('PaddleOCR recognized text/score/position counts differ')
    if not all(math.isfinite(v) and v>0 for v in (w,h)):
        raise ValueError('Invalid source dimensions')
    out=[]
    for txt, score, box in zip(texts, scores, boxes):
        if not isinstance(txt,str): raise ValueError('PaddleOCR text is not a string')
        try: conf=float(score)
        except (ValueError,TypeError): raise ValueError('Invalid OCR confidence')
        if not math.isfinite(conf) or not 0<=conf<=1:
            raise ValueError('Invalid OCR confidence')
        box=sequence(box,'recognized-text geometry')
        try:
            if len(box)==4 and all(isinstance(q,(int,float)) for q in box):
                x0,y0,x1,y1=map(float,box)
                polygon=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
            else:
                if len(box)!=4 or any(len(q)!=2 for q in box):
                    raise ValueError('Expected four source polygon vertices')
                polygon=[[float(x),float(y)] for x,y in box]
                x0=min(q[0] for q in polygon);y0=min(q[1] for q in polygon)
                x1=max(q[0] for q in polygon);y1=max(q[1] for q in polygon)
            if any(not math.isfinite(v) for q in polygon for v in q):
                raise ValueError('Nonfinite OCR geometry')
            if not (0<=x0<x1<=w and 0<=y0<y1<=h):
                raise ValueError('OCR geometry lies outside source or has no area')
            area=abs(sum(polygon[i][0]*polygon[(i+1)%4][1]-
                         polygon[(i+1)%4][0]*polygon[i][1] for i in range(4)))/2
            if area<=0: raise ValueError('Degenerate OCR polygon')
        except (TypeError,IndexError,OverflowError) as exc:
            raise ValueError('Invalid OCR geometry') from exc
        # Validate every entry before applying the deliberate confidence filter.
        # A malformed low-score entry still invalidates the whole tile.
        if not txt.strip() or conf<.18: continue
        x0=math.floor(x0);y0=math.floor(y0)
        x1=math.ceil(x1);y1=math.ceil(y1)
        out.append(dict(text=txt.strip(),raw_text=txt,conf=round(conf*100,3),
                        source_polygon=polygon,box=(x0,y0,x1-x0,y1-y0)))
    return sorted(out,key=lambda x:(x['box'][1],x['box'][0]))

def lines_to_tsv(lines):
    header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext'
    rows=[header]
    # One OCR-detected line per Tesseract line ID. Its raw text remains intact.
    for i,item in enumerate(lines,1):
        x,y,w,h=item['box']
        txt=re.sub(r'[\t\r\n]+',' ',item['text']).strip()
        rows.append(f"5\t1\t{i}\t1\t1\t1\t{x}\t{y}\t{w}\t{h}\t{item['conf']}\t{txt}")
    return '\n'.join(rows)+'\n'

def _portrait_tiles(width, height):
    """(crop top, crop bottom, ownership top, ownership bottom).

    Portrait, text-dense receipts are recognized in bounded bands; overlaps
    allow a text line straddling a band boundary to remain fully visible.
    Ownership is assigned using the center of the recognized text line so no
    duplicate is created in the overlap.  No pixels in the input are modified.
    """
    if height < 1200 or height < 1.35 * width:
        return [(0, height, 0, height)]
    count = max(3, min(6, (height + 549) // 550))
    boundaries = [round(i * height / count) for i in range(count + 1)]
    overlap = max(48, min(96, round(height * .04)))
    return [(max(0, boundaries[i] - overlap),
             min(height, boundaries[i + 1] + overlap),
             boundaries[i], boundaries[i + 1]) for i in range(count)]



def qr_like_graphics(image):
    """High-precision candidates for densely printed square *graphics*, not text.

    This is a source-preserving QR-like graphic locator, not a QR decoder and
    never an invoice field detector. It produces source-coordinate exclusions
    ONLY for a derivative OCR view. Inspect/review the original as-is.
    """
    import cv2
    import numpy as np
    h,w=image.shape[:2]
    if min(h,w)<250: return []
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY_INV,31,8)
    kernel=40 if min(h,w)>=400 else 28
    density=cv2.boxFilter((ink>0).astype('float32'),-1,(kernel,kernel),normalize=True)
    mask=(density>0.34).astype('uint8')
    count, _, stats, _=cv2.connectedComponentsWithStats(mask)
    candidates=[]
    for x,y,bw,bh,area in stats[1:]:
        x,y,bw,bh,area=map(int,(x,y,bw,bh,area))
        if not (70<=bw<=int(.38*w) and 70<=bh<=int(.38*h)):
            continue
        if not (.72<=bw/bh<=1.30) or area < .45*bw*bh:
            continue
        # Unlike words or logos, a dense QR-style block covers its enclosing
        # square. Reject sparse handwriting and ordinary invoice table cells.
        px=max(0,x-12);py=max(0,y-12)
        qx=min(w,x+bw+12);qy=min(h,y+bh+12)
        if cv2.countNonZero(ink[py:qy,px:qx]) / max(1, (qx-px)*(qy-py)) < .30:
            continue
        margin=max(8,round(.13*max(bw,bh)))
        candidates.append((max(0,x-margin),max(0,y-margin),
                           min(w,x+bw+margin),min(h,y+bh+margin)))
    # Avoid overlapping or duplicate exclusions from connected-component noise.
    candidates.sort(key=lambda q:(q[1],q[0]))
    selected=[]
    for rect in candidates:
        if any(max(0,min(rect[2],r[2])-max(rect[0],r[0])) *
               max(0,min(rect[3],r[3])-max(rect[1],r[1])) > .5*
               min((rect[2]-rect[0])*(rect[3]-rect[1]),
                   (r[2]-r[0])*(r[3]-r[1])) for r in selected):
            continue
        selected.append(rect)
    return selected


def make_graphics_safe_view(image):
    """Return an OCR-only image and excluded QR-like rects; original untouched."""
    import numpy as np
    rectangles=qr_like_graphics(image)
    if not rectangles:return image,[]
    work=image.copy()
    h,w=image.shape[:2]
    for x0,y0,x1,y1 in rectangles:
        # Sample a small *exterior* band, never the dark graphic itself.
        ext=image[max(0,y0-9):min(h,y1+9),max(0,x0-9):min(w,x1+9)]
        yy0=y0-max(0,y0-9);xx0=x0-max(0,x0-9)
        region_mask=np.ones(ext.shape[:2],dtype=bool)
        region_mask[yy0:yy0+(y1-y0),xx0:xx0+(x1-x0)]=False
        bg=np.median(ext[region_mask],axis=0) if region_mask.any() else np.array([245,245,245])
        work[y0:y1,x0:x1]=np.clip(bg,0,255).astype('uint8')
    return work,rectangles

def image_to_tsv(image, progress=None):
    """Produce original-photo-coordinate TSV, even if OCR uses local crops.

    progress(event, **info) is optional; callers may stream stage diagnostics.
    All child-zone coordinates refer to the same original input image.
    """
    if not present():
        raise RuntimeError('PaddleOCR 3.x and PaddlePaddle are not installed in selected Python runtime')
    h, w = image.shape[:2]
    tiles = _portrait_tiles(w, h)
    lines = []
    if progress:
        progress('OCR_TILE_PLAN', total=len(tiles), image_width=w, image_height=h)
    for i, (top, bottom, own_top, own_bottom) in enumerate(tiles, 1):
        if progress:
            progress('OCR_TILE_START', index=i, total=len(tiles), source_y0=top,
                     source_y1=bottom, ownership_y0=own_top,
                     ownership_y1=own_bottom)
        # Each predict call has bounded dimensions for portrait invoices.
        # The parent verifier enforces a per-stage watchdog on our events.
        crop = image[top:bottom, :]
        # Only dense portrait receipts need graphics isolation. Large square
        # QR motifs can generate extreme false detections and stall some CPU
        # kernels; the original photo is never written or modified.
        if len(tiles)>1:
            work, excluded=make_graphics_safe_view(crop)
            if progress:
                progress('OCR_TILE_GRAPHIC_SCREEN', index=i, excluded_rects=[
                    [x0, y0+top, x1, y1+top] for x0,y0,x1,y1 in excluded])
        else:
            work=crop
        candidates = []
        # Per-inference kwargs are strictly restricted to those accepted by
        # PaddleOCR 3.7 predict(). The recognition batch limit belongs to
        # PaddleOCR() INITIALIZATION, not predict(). Earlier passing it here
        # raised TypeError on every Metro portrait tile on Windows.
        args=({'text_det_limit_side_len':640,
               'text_det_limit_type':'max'} if len(tiles)>1 else {})
        candidates = _recognize_tile(work, w, bottom-top, args, progress)
        count = 0
        for line in candidates:
            x, local_y, bw, bh = line['box']
            global_y = local_y + top
            center = global_y + bh / 2.0
            if not own_top <= center < own_bottom and not (center == h and own_bottom == h):
                continue
            # Keep exact source geometry rather than the crop's local origin.
            lines.append({**line, 'box': (x, global_y, bw, bh)})
            count += 1
        if progress:
            progress('OCR_TILE_COMPLETE', index=i, total=len(tiles),
                     accepted_lines=count, detected_lines=len(candidates))
    lines.sort(key=lambda x: (x['box'][1], x['box'][0]))
    return lines_to_tsv(lines)
