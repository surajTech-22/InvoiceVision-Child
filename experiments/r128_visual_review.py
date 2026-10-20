#!/usr/bin/env python3
"""R128 research-only original-versus-detection comparisons. Never updates Child.

Coordinates and text remain model evidence, not verified printed layout.
Emits an annotated source comparison and geometry warnings per available sample.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def font(size=20):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "C:/Windows/Fonts/arial.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def safe_rect(box, width, height):
    try:
        if isinstance(box, dict):
            if box.get("coord_origin") == "BOTTOMLEFT":
                x0, y0, x1, y1 = (box["l"], height-box["t"],
                                  box["r"], height-box["b"])
            else:
                x0, y0, x1, y1 = (box["l"], box["t"], box["r"], box["b"])
        elif len(box) == 4 and isinstance(box[0], (list, tuple)):
            x0, x1 = min(p[0] for p in box), max(p[0] for p in box)
            y0, y1 = min(p[1] for p in box), max(p[1] for p in box)
        else:
            x0,y0,x1,y1 = box
        vals = [float(v) for v in (x0,y0,x1,y1)]
        if not all(abs(v) < 1e9 for v in vals) or vals[0]>=vals[2] or vals[1]>=vals[3]:
            return None
        return vals
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return None

def labels_from_model(result):
    if not isinstance(result, dict):
        return []
    if "res" in result:
        return result["res"].get("parsing_res_list", [])
    return result.get("parsing_res_list", [])

def collect_predictions(model, out, image, width, height):
    predictions = []
    warnings = []
    name = image.name
    try:
        if model == "docling":
            data = json.loads((out / (name + ".docling.json")).read_text(encoding="utf8"))
            for table in data.get("tables", []):
                for prov in table.get("prov", []):
                    predictions.append(("table",prov.get("bbox"),"red"))
                for cell in table.get("data",{}).get("table_cells",[]):
                    predictions.append(("cell",cell.get("bbox"),"blue"))
        elif model == "paddleocr-vl":
            for path in sorted(out.glob(name+".*.raw.json")):
                data = json.loads(path.read_text(encoding="utf8"))
                for b in labels_from_model(data):
                    predictions.append((str(b.get("block_label","unknown")),
                                        b.get("block_bbox"),"red" if b.get("block_label")=="table" else "purple"))
                    if b.get("block_label")=="table":
                        txt = str(b.get("block_content",""))
                        if any(k in txt.casefold() for k in ("total","grand total","amount payable")):
                            warnings.append("Table contains TOTAL-like text; check independent totals zone and source geometry")
        elif model in ("qwen3-vl","layoutlmv3","uie","pp-chatocrv4"):
            warnings.append("No ground-truthed block coordinates: showing source without invented polygons")
        else:
            warnings.append("No coordinate visualization adapter installed for this model")
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append("Prediction file unavailable or malformed: "+str(exc))
    return predictions,warnings

def single(out, model, path):
    original = Image.open(path).convert("RGB")
    w,h=original.size
    panel=Image.new("RGB",(w*2,max(h+65,730)),"#edf2f7")
    panel.paste(original,(0,61)); panel.paste(original,(w,61))
    d=ImageDraw.Draw(panel)
    d.text((15,15),"SOURCE: unchanged synthetic test",font=font(22),fill="#1a2739")
    d.text((w+15,15),model+" detections (UNVERIFIED)",font=font(22),fill="#1a2739")
    predictions,warnings=collect_predictions(model,out,path,w,h)
    color={"red":"#dc334b","blue":"#2466cc","purple":"#8650ad"}
    for label,raw,c in predictions:
        box=safe_rect(raw,w,h)
        if box is None:
            warnings.append("Invalid bounds for "+label);continue
        if box[0]<0 or box[1]<0 or box[2]>w or box[3]>h:
            warnings.append("Detected "+label+" extends outside image")
        d.rectangle((int(w+box[0]),int(61+box[1]),int(w+box[2]),int(61+box[3])),
                    outline=color[c],width=3 if label!="table" else 5)
    name=path.stem
    output=out/("comparison_"+name+".png")
    panel.save(output)
    return {"sample":path.name,"comparison_file":output.name,
            "predicted_regions":len(predictions),"review_warnings":sorted(set(warnings)),
            "source_pixels":[w,h],"source_preserved":True,"approved_geometry":False}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--model",required=True)
    ap.add_argument("--out",type=Path,required=True)
    x=ap.parse_args()
    images=sorted((x.out/"images").glob("*.png"))
    findings=[single(x.out,x.model,p) for p in images]
    (x.out/"VISUAL_REVIEW.json").write_text(json.dumps({
      "source":"generated_synthetic_samples_not_customer_invoices",
      "model":x.model,"geometry_accepted":False,
      "review_required":True,"cases":findings},indent=2),encoding="utf8")
    print("R128 visual comparisons:",len(findings))
if __name__=="__main__":
    main()
