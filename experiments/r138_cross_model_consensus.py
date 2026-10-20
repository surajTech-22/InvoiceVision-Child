"""R138: conservative cross-engine OCR evidence. NEVER posts or invents values."""
from __future__ import annotations
from .r138_field_evidence import reconstruct,tokens_from_ocr,normalize,amount

def iou(a,b):
    x0=max(a[0],b[0]);y0=max(a[1],b[1]);x1=min(a[2],b[2]);y1=min(a[3],b[3])
    intersection=max(0,x1-x0)*max(0,y1-y0)
    A=(a[2]-a[0])*(a[3]-a[1])
    B=(b[2]-b[0])*(b[3]-b[1])
    return intersection/max(1,A+B-intersection)

def same_value(raw_a,raw_b):
    a=amount(raw_a);b=amount(raw_b)
    if a is not None and b is not None:
        return abs(a-b)<.005
    return bool(normalize(raw_a) and normalize(raw_a)==normalize(raw_b))

def fuse(rapid,paddle):
    """Requires exact original source SHA; fusion never overrides a model."""
    if (not rapid.get("source_sha256") or
        rapid["source_sha256"]!=paddle.get("source_sha256")):
        raise ValueError("Different source images; refuse OCR fusion")
    ra=reconstruct(rapid,"rapidocr");pa=reconstruct(paddle,"paddleocr")
    tokens={
      "rapidocr":{t.index:t for t in tokens_from_ocr(rapid.get("raw_texts",[]),rapid.get("raw_boxes",[]),"rapidocr")},
      "paddleocr":{t.index:t for t in tokens_from_ocr(paddle.get("raw_texts",[]),paddle.get("raw_boxes",[]),"paddleocr")}
    }
    fields={}
    for field in ra["fields"]:
        proposals=[]
        for engine,rows in (("rapidocr",ra["fields"][field]),("paddleocr",pa["fields"][field])):
            other="paddleocr" if engine=="rapidocr" else "rapidocr"
            for row in rows:
                t=tokens[engine].get(row["source_tokens"][-1])
                adjacent=sorted(((iou(t.box,q.box),q) for q in tokens[other].values()
                                 if t and iou(t.box,q.box)>=.45),
                                key=lambda x:-x[0])
                if not adjacent:status="INDEPENDENT_RECHECK_REQUIRED"
                elif any(same_value(row["value"],q.text) for _,q in adjacent):
                    status="CROSS_ENGINE_TEXT_SUPPORTED_UNVERIFIED"
                else:status="CROSS_ENGINE_TEXT_CONFLICT_REVIEW_REQUIRED"
                proposals.append({"value":row["value"],"engine":engine,
                    "source_tokens":row["source_tokens"],
                    "support_status":status,
                    "other_readings":[{"value":q.text,"token_index":q.index,"region_iou":round(score,3)}
                                      for score,q in adjacent[:2]],
                    "posting_eligible":False,"physical_border_verified":False})
        fields[field]=proposals
    return {"filename":rapid.get("file"),"source_sha256":rapid["source_sha256"],
            "fields":fields,"posting_eligible":False,
            "physical_layout_approved":False,
            "no_override_on_conflicts":True}
