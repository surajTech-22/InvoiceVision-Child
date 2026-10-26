"""R246: review-only long-ruling-line suppression for printed invoice tables.

This never changes the uploaded JPEG, decoded source pixels, first OCR TSV,
source-linked zone layout, or approved financial fields. It temporarily
suppresses detected LONG ruled lines in an OCR view, not arbitrary edges,
then maps every OCR word back to original oriented source pixel coordinates.
"""
from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path

def remove_long_ruling_lines(image):
    import cv2
    if not hasattr(image,"shape") or image.ndim not in (2,3):
        raise ValueError("Original decoded image required")
    h,w=image.shape[:2]
    if not (180<=h<=6000 and 180<=w<=6000 and h*w<=24_000_000):
        raise ValueError("Unsafe source dimensions for ruled-table OCR")
    original=hashlib.sha256(image.tobytes(order="C")).hexdigest()
    gray=(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
          if image.ndim==3 else image.copy())
    # A clipped all-black/near-black frame does not contain recoverable
    # printed document geometry. Adaptive thresholds may return zero ink
    # on that source; do not classify it as a valid blank invoice.
    if float(gray.mean())<18 and float(gray.std())<6:
        raise ValueError("Unreadable dark source frame; refuse grid OCR")
    up=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    # Uniform Otsu threshold mistakes grey phone-photo shadows/background
    # for continuous black table lines; this falsely deletes real source ink.
    # Locally adaptive foreground isolates printed rules despite vignetting.
    binary=cv2.adaptiveThreshold(
        up,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,61,18)
    # Kernel sizes are proportional to whole-page source geometry, not
    # invoice/vendor-specific coordinates.
    kw=max(110,min(650,round(w*2*.085)))
    kh=max(75,min(600,round(h*2*.045)))
    hkernel=cv2.getStructuringElement(cv2.MORPH_RECT,(kw,1))
    vkernel=cv2.getStructuringElement(cv2.MORPH_RECT,(1,kh))
    hlines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,hkernel)
    vlines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,vkernel)
    mask=cv2.bitwise_or(hlines,vlines)
    source_line_pixels=cv2.countNonZero(mask)
    ratio=source_line_pixels/(up.shape[0]*up.shape[1])
    if ratio>.12:raise ValueError("Excessive long-line removal refused")
    if source_line_pixels<100:
        cleaned=up.copy()
        detected=False
    else:
        # Repair background only on temporary OCR view. Never write pixels
        # to original image, and keep source geometry exactly reversible.
        dilated=cv2.dilate(mask,cv2.getStructuringElement(cv2.MORPH_RECT,(3,3)))
        cleaned=cv2.inpaint(up,dilated,3,cv2.INPAINT_TELEA)
        detected=True
    if hashlib.sha256(image.tobytes(order="C")).hexdigest()!=original:
        raise RuntimeError("Ruled-table preprocessing mutated original pixels")
    return cleaned,{"source_decoded_sha256":original,
                    "original_source_dimensions":[w,h],
                    "detected_long_ruling_lines":detected,
                    "ruling_line_pixel_fraction":round(ratio,6),
                    "temporary_image_scale":2,
                    "source_pixels_modified":False}

def _load(name,module_name):
    path=Path(__file__).with_name(name)
    spec=importlib.util.spec_from_file_location(module_name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Staged trusted OCR evidence module unavailable")
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def distinct_source_rows(proposals,max_rows=24):
    """Deduplicate *physical rows*, preserving disagreeing OCR alternatives.

    Repeated PSM views of the same source line are not distinct invoice items.
    If quantities/amounts conflict, preserve BOTH literal OCR readings and
    refuse to certify the grouped row.
    """
    if not isinstance(proposals,list) or len(proposals)>80:
        raise ValueError("Excessive source-row proposals")
    groups=[]
    for item in proposals:
        if not isinstance(item,dict) or item.get("posting_eligible") is not False:
            raise ValueError("Unsafe row candidate")
        b=item.get("row_box")
        if (not isinstance(b,list) or len(b)!=4 or
            any(type(x)!=int for x in b) or not (b[0]<b[2] and b[1]<b[3])):
            raise ValueError("Source row lacks physical source coordinates")
        center_y=(b[1]+b[3])/2
        height=b[3]-b[1]
        group=None
        for existing in groups:
            e=existing["source_row_box"]
            y=(e[1]+e[3])/2
            height2=e[3]-e[1]
            x_intersection=max(0,min(e[2],b[2])-max(e[0],b[0]))
            x_support=x_intersection/max(1,min(e[2]-e[0],b[2]-b[0]))
            if abs(center_y-y)<=max(7,min(height,height2)*.65) and x_support>=.5:
                group=existing
                break
        value={
            "source_view":item["source_view"],
            "original_description":item["description_original_ocr"],
            "original_quantity":item["quantity_original_ocr"],
            "original_amount":item["amount_original_ocr"],
            "source_row_box":list(b),
            "field_value_verified":False,"posting_eligible":False
        }
        if group is None:
            group={"source_row_box":list(b),"source_variants":[value],
                   "conflicting_ocr_alternatives":False,
                   "distinct_row_certified":False,
                   "posting_eligible":False}
            groups.append(group)
        else:
            group["source_variants"].append(value)
            group["source_row_box"]=[
                min(group["source_row_box"][0],b[0]),
                min(group["source_row_box"][1],b[1]),
                max(group["source_row_box"][2],b[2]),
                max(group["source_row_box"][3],b[3])]
            pairs={(v["original_description"],v["original_quantity"],
                    v["original_amount"]) for v in group["source_variants"]}
            group["conflicting_ocr_alternatives"]=len(pairs)>1
        if len(groups)>max_rows:
            raise ValueError("Too many physical table rows; fail closed")
    return groups

def review(image,reader):
    """reader(temp_image, psm) returns unmodified local Tesseract TSV."""
    if not callable(reader):raise ValueError("Offline OCR callback unavailable")
    processed,evidence=remove_long_ruling_lines(image)
    out={"status":"GRID_RULING_SOURCE_REVIEW_ONLY",
         "source_evidence":evidence,
         "source_views":[],
         "source_field_row_anchors":{},
         "original_first_pass_ocr_replaced":False,
         "accepted_invoice_fields":0,
         "accepted_item_rows":0,
         "accounting_write_permitted":False,
         "posting_eligible":False,
         "release_approved":False}
    if not evidence["detected_long_ruling_lines"]:
        out["status"]="NO_LONG_RULING_LINES_FOUND"
        return out
    parser=_load("INVOICE_OCR_MULTISCALE_REVIEW_R243.py","_r246_staged_multiscale")
    anchors=_load("INVOICE_OCR_FIELD_ROW_ANCHORS_R245.py","_r246_staged_field_anchors")
    h,w=image.shape[:2]
    views=[]
    for variant,psm in (("grid_removed_psm11_2x",11),
                        ("grid_removed_psm6_2x",6)):
        raw=reader(processed,psm)
        obs=parser.source_words(raw,w,h,scale=2)
        view={"variant":variant,"posting_eligible":False,
              "source_boxes_are_original_pixels":True,
              "source_ocr_words_total":len(obs),
              "source_words":obs[:480]}
        views.append(view)
        out["source_views"].append({
             "variant":variant,"word_count":len(obs),
             "source_boxes_are_original_pixels":True,
             "posting_eligible":False})
    alt={"status":"SOURCE_MULTISCALE_ALTERNATIVES_REVIEW_ONLY",
         "posting_eligible":False,"variants":views}
    proposals=anchors.propose(alt,w,h,max_fields=24,max_rows=12)
    out["source_field_row_anchors"]=proposals
    physical_rows=distinct_source_rows(proposals["table_header_anchored_row_proposals"])
    out["source_unique_item_rows"]=physical_rows
    out["source_unique_item_row_count"]=len(physical_rows)
    out["physical_row_duplicate_evidence_count"]=max(0,proposals["row_proposals_count"]-len(physical_rows))
    out["provisional_table_rows"]=proposals["row_proposals_count"]
    out["provisional_label_fields"]=proposals["field_proposals_count"]
    if hashlib.sha256(image.tobytes(order="C")).hexdigest()!=evidence["source_decoded_sha256"]:
        raise RuntimeError("Source image changed during line-removed OCR")
    return out
