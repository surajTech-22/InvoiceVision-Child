#!/usr/bin/env python3
"""Side-by-side source versus VLM reading (not geometry), no fabricated boxes."""
from __future__ import annotations
import argparse, json, textwrap
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

def font(n):
  for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","C:/Windows/Fonts/arial.ttf"):
    if Path(f).is_file():return ImageFont.truetype(f,n)
  return ImageFont.load_default()
def main():
  p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
  x=p.parse_args()
  report=json.loads((x.out/"REPORT.json").read_text(encoding="utf8"))
  images=sorted((x.out/"images").glob("*.png"))
  for src in images:
    im=Image.open(src).convert("RGB")
    w,h=im.size
    canvas=Image.new("RGB",(w*2,max(h+80,720)),"white")
    canvas.paste(im,(0,68))
    d=ImageDraw.Draw(canvas)
    d.rectangle((w,68,w*2,max(h+68,720)),fill="#eff3fa")
    d.text((22,14),"SOURCE: synthetic fixture",font=font(24),fill="#15223c")
    d.text((w+22,14),"MODEL READING: NOT SOURCE-VERIFIED",font=font(23),fill="#15223c")
    item=next((r for r in report.get("cases",[]) if r.get("image")==src.name),None)
    if item:
      body=item.get("reading_unverified","(empty model output)")
    else:
      body="No inference result for this sample. Status: "+str(report.get("status"))
    y=98
    for line in textwrap.wrap(str(body),width=70,replace_whitespace=False):
      d.text((w+25,y),line,font=font(20),fill="#254163");y+=32
    d.text((w+25,660),"No position/field accuracy approval. No posting enabled.",
           font=font(17),fill="#bd3d44")
    canvas.save(x.out/("comparison_"+src.stem+".png"),optimize=True)
  print("Source-versus-VLM reading comparisons:",len(images))
if __name__=="__main__":main()
