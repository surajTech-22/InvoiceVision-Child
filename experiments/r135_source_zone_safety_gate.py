"""R135: review-only invariant gates for semantic child-zone splits.
No library name templates, no synthetic borders, no automatic accounting posts.
"""
from __future__ import annotations

def evaluate_split(parent, candidate_y, evidence, min_gutter=7):
    x0, y0, x1, y1 = parent
    assert 0 <= x0 < x1 and 0 <= y0 < y1
    result = {"approved": False, "posting_eligible": False,
              "physical_border_verified": False,
              "parent_preserved": True, "child_boxes": []}
    if not (y0+12 < candidate_y < y1-12):
        return {**result, "reason": "SPLIT_OUTSIDE_SAFE_PARENT_INTERIOR"}
    if not evidence:
        return {**result, "reason": "MISSING_SOURCE_TEXT_EVIDENCE"}
    item = [w for w in evidence if w.get("role") == "item"]
    tax = [w for w in evidence if w.get("role") == "tax"]
    if len({w["view"] for w in item}) < 2 or len({w["view"] for w in tax}) < 2:
        return {**result, "reason": "INSUFFICIENT_INDEPENDENT_OCR_VIEWS"}
    if any(not (x0 <= w["left"] < w["right"] <= x1 and
                y0 <= w["top"] < w["bottom"] <= y1)
           for w in evidence):
        return {**result, "reason": "OCR_EVIDENCE_OUTSIDE_PARENT"}
    if any(w["top"] < candidate_y < w["bottom"] for w in evidence):
        return {**result, "reason": "SOURCE_TEXT_CROSSES_PROPOSED_CUT"}
    if max(w["bottom"] for w in item) + min_gutter > min(w["top"] for w in tax):
        return {**result, "reason": "NO_SOURCE_SUPPORTED_GUTTER"}
    # Even when the split is supported by text, these are SEMANTIC
    # child hypotheses, NEVER printed physical borders or posting authority.
    return {**result, "reason": "TEXT_ONLY_SEMANTIC_CHILD_CANDIDATES",
            "semantically_separable": True,
            "child_boxes": [[x0,y0,x1,candidate_y],
                            [x0,candidate_y,x1,y1]]}

def self_test():
    item=lambda view,top,bottom: dict(view=view,role="item",
        left=3,right=30,top=top,bottom=bottom)
    tax=lambda view,top,bottom: dict(view=view,role="tax",
        left=3,right=30,top=top,bottom=bottom)
    region=[0,0,100,100]
    safe=[item("raw",10,30),item("clahe",10,30),
          tax("raw",60,80),tax("clahe",60,80)]
    v=evaluate_split(region,45,safe)
    assert v["semantically_separable"] and not v["approved"]
    crossing=safe+[dict(view="shadow",role="unknown",
                        left=12,right=28,top=41,bottom=50)]
    assert evaluate_split(region,45,crossing)["reason"]=="SOURCE_TEXT_CROSSES_PROPOSED_CUT"
    assert evaluate_split(region,5,safe)["reason"]=="SPLIT_OUTSIDE_SAFE_PARENT_INTERIOR"
    assert evaluate_split(region,45,safe[:1])["reason"]=="INSUFFICIENT_INDEPENDENT_OCR_VIEWS"
    assert evaluate_split(region,45,[])["reason"]=="MISSING_SOURCE_TEXT_EVIDENCE"
    touching=[item("raw",20,44),item("clahe",20,44),
              tax("raw",48,66),tax("clahe",48,66)]
    assert evaluate_split(region,46,touching)["reason"]=="NO_SOURCE_SUPPORTED_GUTTER"
    print("R135: six pure safety tests passed; no production zone accepted.")

if __name__=="__main__":
    self_test()
