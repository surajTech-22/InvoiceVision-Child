"""Audit provisional boxes against closed source-mask components, without repairs.

A closed ink-mask contour is supporting evidence, not proof of a printed box.
Glyphs, watermarks and shadows still require source-image visual review.
"""
import cv2
import numpy as np


def closed_ink_contours(layers):
    """Rotation-tolerant enclosed contours in source-threshold ink.

    No closing/dilation or synthetic lines. A hole contour proves enclosure in
    this threshold view only; it does not independently certify a printed box.
    """
    ink=layers['ink']
    contours,hierarchy=cv2.findContours(ink,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:return []
    found=[];height,width=ink.shape
    for i,contour in enumerate(contours):
        if hierarchy[0,i,3]<0:continue  # Only enclosed background contours.
        area=float(cv2.contourArea(contour))
        rect=cv2.minAreaRect(contour);rw,rh=rect[1]
        if min(rw,rh)<13 or max(rw,rh)<35 or area<1000:continue
        if area/max(1,rw*rh)<.85:continue
        polygon=cv2.boxPoints(rect)
        if np.min(polygon)<1 or np.max(polygon[:,0])>=width-1 or np.max(polygon[:,1])>=height-1:continue
        coverages=[]
        for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
            n=max(20,int(np.linalg.norm(b-a)))
            points=np.rint(np.linspace(a,b,n)).astype(int)
            supported=[]
            for x,y in points:
                supported.append(bool(np.any(ink[max(0,y-2):min(height,y+3),max(0,x-2):min(width,x+3)])))
            coverages.append(float(np.mean(supported)))
        if min(coverages)<.95:continue
        found.append({'source_polygon':polygon.astype(float).tolist(),
                      'source_contour_area':area,'side_coverage':coverages,
                      'evidence':'ENCLOSED_SOURCE_INK_CONTOUR_NO_REPAIRS',
                      'physical_border_verified':False})
    return found


def closed_regions(layers):
    """Closed background components, including full-width tables/outer frames.

    No maximum box width/height filter: a full-page frame remains valid evidence.
    Long observed horizontal/vertical source strokes must support all four sides.
    """
    raw = layers['raw']; height,width = raw.shape
    _,_,stats,_ = cv2.connectedComponentsWithStats((raw == 0).astype('uint8'),8)
    found=[]
    for x,y,w,h,area in stats[1:]:
        x,y,w,h,area=map(int,(x,y,w,h,area))
        if x == 0 or y == 0 or x+w == width or y+h == height: continue
        if w < 20 or h < 13 or area < 260 or area/(w*h) < .65: continue
        # Sampling nearby source evidence never adds or joins border pixels.
        def cover(axis,coord,start,end):
            mask=layers['h35'] if axis == 'h' else layers['v35']
            if axis == 'h':
                band=mask[max(0,coord-5):min(height,coord+6),start:end]
                return float(np.mean(np.any(band,axis=0))) if band.size else 0.
            band=mask[start:end,max(0,coord-5):min(width,coord+6)]
            return float(np.mean(np.any(band,axis=1))) if band.size else 0.
        sides=[cover('h',y,x,x+w),cover('h',y+h-1,x,x+w),
               cover('v',x,y,y+h),cover('v',x+w-1,y,y+h)]
        if min(sides)<.46 or np.mean(sides)<.67: continue
        found.append({'xyxy':[x,y,x+w,y+h],
                      'side_coverage':dict(zip(('top','bottom','left','right'),map(float,sides))),
                      'certainty':'CLOSED_SOURCE_COMPONENT_REVIEW_REQUIRED',
                      'physical_border_verified':False})
    return found


def audit(layers, candidates):
    raw = layers['raw']
    n, labels, stats, _ = cv2.connectedComponentsWithStats((raw == 0).astype('uint8'), 8)
    height, width = raw.shape
    rows = []
    for candidate in candidates:
        x0,y0,x1,y1 = candidate['xyxy']
        if not (0 < x0 < x1 < width and 0 < y0 < y1 < height):
            rows.append({**candidate,'closed_source_component':False,'reason':'OUTSIDE_SOURCE_INTERIOR'})
            continue
        inner = labels[y0+1:y1-1,x0+1:x1-1]
        ids, counts = np.unique(inner[inner > 0], return_counts=True)
        if len(ids) == 0:
            rows.append({**candidate,'closed_source_component':False,'reason':'NO_SOURCE_BACKGROUND_INTERIOR'})
            continue
        component = int(ids[np.argmax(counts)])
        x,y,w,h,area = map(int,stats[component])
        touches_page = x == 0 or y == 0 or x+w == width or y+h == height
        intersection = max(0,min(x+w,x1)-max(x,x0))*max(0,min(y+h,y1)-max(y,y0))
        union = w*h+(x1-x0)*(y1-y0)-intersection
        overlap = intersection/max(1,union)
        fraction = float(np.max(counts))/max(1,inner.size)
        supported = not touches_page and overlap >= .8 and fraction >= .65
        rows.append({**candidate,'closed_source_component':supported,
                     'reason':'SOURCE_MASK_CLOSED_REVIEW_REQUIRED' if supported else 'OPEN_OR_MISMATCHED_SOURCE_COMPONENT',
                     'source_component_xyxy':[x,y,x+w,y+h],
                     'component_bbox_iou':round(overlap,4),
                     'interior_component_fraction':round(fraction,4),
                     'physical_border_verified':False})
    return rows
