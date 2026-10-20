#!/usr/bin/env python3
"""R128 conservative semantic/geometry adapter: review-only, never posts invoices.

Reads raw model evidence and derives *candidate* semantic groups. Does NOT
silently clip predicted boxes, create printed lines, or treat OCR envelopes as
printed table borders. Recursion is limited to evidence-supported child groups.
"""
from __future__ import annotations
import argparse
import html
from html.parser import HTMLParser
import json
import re
from pathlib import Path

# General vocabulary; no vendor, GSTIN, ledger or customer-specific constants.
TERMS={
 "supplier":("supplier","sold by","seller","from","bill from"),
 "buyer":("buyer","bill to","billed to","ship to","customer"),
 "invoice_number":("invoice no","invoice #","invoice number","bill no","reference no","ref no"),
 "invoice_date":("invoice date","dated","date"),
 "tax":("gst","cgst","sgst","igst","vat","tax"),
 "totals":("grand total","net payable","total amount","amount payable","total","balance due"),
 "item_header":("description","particulars","item","quantity","qty","rate","amount","units"),
}
def norm(s):return re.sub(r"[^a-z0-9]+"," ",str(s).casefold()).strip()
def classify(text):
    s=norm(text)
    scores=[]
    for key,words in TERMS.items():
        for phrase in words:
            p=norm(phrase)
            if s==p or s.startswith(p+" ") or s.startswith(p+":"):
                scores.append((len(p),key))
    if not scores:return "unclassified"
    # Longer matching phrases outrank generic 'amount', 'date' and 'total'.
    return max(scores)[1]
class TableRows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=="tr":self.row=[]
        if tag in ("td","th") and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None and self.row is not None:
            self.row.append(html.unescape("".join(self.cell)).strip());self.cell=None
        if tag=="tr" and self.row is not None:
            self.rows.append(self.row);self.row=None
def parse_rows(markup):
    parser=TableRows();parser.feed(markup);return parser.rows
def proposal(text,box,source,kind=None,physical=False):
    return {"meaning":kind or classify(text),"source_text":text,"source_box":box,
            "evidence_engine":source,"physically_verified":physical,
            "posting_eligible":False}
def inspect_table(text,box,source,issues):
    candidate=proposal(text,box,source,"table_composite")
    rows=parse_rows(text) if "<table" in text.lower() else []
    if not rows:
        issues.append("No supported table-cell segmentation; do not invent row or column boundaries")
        candidate["children"]=[]
        return candidate
    children=[]
    for row_idx,row in enumerate(rows):
        values=[s for s in row if s]
        if not values:continue
        special=next((classify(v) for v in values if classify(v) in ("totals","tax")),None)
        kind=special if special else ("item_header" if row_idx==0 else "item_row")
        children.append(proposal(" | ".join(row),None,source,kind=kind))
    if any(c["meaning"]=="totals" for c in children):
        issues.append("Total embedded in predicted table: create separate semantic candidate only; physical split needs source evidence")
    candidate["children"]=children
    return candidate
def inspect_model(model,out):
    roots=[];issues=[]
    if model=="paddleocr-vl":
        for p in sorted(out.glob("synthetic_*.png.*.raw.json")):
            data=json.loads(p.read_text(encoding="utf8"));r=data.get("res",data)
            page={"image":p.name.split(".png")[0]+".png","roots":[],"issues":[]}
            for b in r.get("parsing_res_list",[]):
                kind=b.get("block_label")
                content=str(b.get("block_content",""))
                bbox=b.get("block_bbox")
                if kind=="table":
                    page["roots"].append(inspect_table(content,bbox,model,page["issues"]))
                else:
                    page["roots"].append(proposal(content,bbox,model))
            # Preserve model bbox in all circumstances; never clamp/accept it.
            roots.append(page)
    elif model=="docling":
        for p in sorted(out.glob("synthetic_*.png.docling.json")):
            data=json.loads(p.read_text(encoding="utf8"))
            page={"image":p.name.split(".png")[0]+".png","roots":[],"issues":[]}
            for table in data.get("tables",[]):
                cells=table.get("data",{}).get("table_cells",[])
                classified=set()
                for cell in cells:
                    value=cell.get("text","");tag=classify(value)
                    if tag!="unclassified":classified.add(tag)
                    page["roots"].append(proposal(value,cell.get("bbox"),model))
                if len(classified & {"supplier","buyer","invoice_number","invoice_date"})>1:
                    page["issues"].append("Detected table mixes invoice header semantics; do not accept as physical item-table authority")
            roots.append(page)
    else:
        for p in sorted((out/"images").glob("*.png")):
            roots.append({"image":p.name,"roots":[],"issues":[
              "No source-aligned semantic coordinates available; leave zones unresolved"]})
    return {"model":model,"status":"REVIEW_ONLY_NOT_PRODUCTION","source_inputs":"SYNTHETIC",
            "roots":roots,"issues":issues,"automatic_posting_enabled":False,
            "physical_layout_approved":False}
def main():
    a=argparse.ArgumentParser();a.add_argument("--model",required=True)
    a.add_argument("--out",required=True,type=Path)
    args=a.parse_args()
    data=inspect_model(args.model,args.out)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/"SEMANTIC_ZONE_REVIEW.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2),encoding="utf8")
    print("R128 candidate zones reviewed:",len(data["roots"]))
if __name__=="__main__":main()
