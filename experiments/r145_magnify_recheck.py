"""Source-bound non-generative crop magnification, preserving competing OCR views."""
import hashlib
import cv2
import numpy as np
from .r143_orientation_evidence import point


def recheck(source_bytes, box, reader, turns=0, scale=4, margin=12):
    image=cv2.imdecode(np.frombuffer(source_bytes,np.uint8),1)
    if image is None:raise ValueError('Invalid source image')
    h,w=image.shape[:2]
    if turns not in (0,1,2,3) or scale not in (1,2,4,8) or not 0<=margin<=24:
        raise ValueError('Unsupported magnification parameters')
    if len(box)!=4 or not all(np.isfinite(x) for x in box):raise ValueError('Invalid source crop')
    a,b,c,d=box
    if not (0<=a<c<=w and 0<=b<d<=h):raise ValueError('Crop outside original image')
    x0,y0=max(0,int(np.floor(a))-margin),max(0,int(np.floor(b))-margin)
    x1,y1=min(w,int(np.ceil(c))+margin),min(h,int(np.ceil(d))+margin)
    crop=image[y0:y1,x0:x1].copy();ch,cw=crop.shape[:2]
    if turns:crop=np.ascontiguousarray(np.rot90(crop,turns))
    rh,rw=crop.shape[:2]
    enlarged=cv2.resize(crop,(rw*scale,rh*scale),interpolation=cv2.INTER_CUBIC)
    gray=cv2.cvtColor(enlarged,cv2.COLOR_BGR2GRAY)
    variants={'colour_cubic':enlarged,'grayscale_cubic':gray,
              'otsu_cubic':cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]}
    records=[]
    for name,view in variants.items():
        texts,polygons=reader(view)
        if len(texts)!=len(polygons):raise ValueError('Mismatched OCR text and crop geometry')
        mapped=[]
        for poly in polygons:
            source=[]
            for x,y in poly:
                if not (0<=x<=rw*scale and 0<=y<=rh*scale):raise ValueError('OCR outside magnified crop')
                sx,sy=point(x/scale,y/scale,rw,rh,-turns)
                source.append([sx+x0,sy+y0])
            mapped.append(source)
        records.append({'view':name,'raw_texts':list(texts),'source_polygons':mapped,
                        'posting_eligible':False,'validated_against_pixels':False})
    return {'source_sha256':hashlib.sha256(source_bytes).hexdigest(),
            'crop_source_xyxy':[x0,y0,x1,y1], 'context_margin_pixels':margin,
            'quarter_turns_ccw':turns,'scale':scale,'views':records,
            'conflicts_preserved':True,'posting_eligible':False}
