#!/usr/bin/env python3
"""Experimental InvoiceVision VLM adapter: CPU always supported, CUDA optional.
No accounting posting, no alteration of Child source. Evidence is synthetic until validated.
"""
from __future__ import annotations
import argparse, gc, hashlib, json, os, time, traceback
from pathlib import Path

MODELS = {
    "smolvlm2": "HuggingFaceTB/SmolVLM2-256M-Video-Instruct",
    "qwen3-vl": "Qwen/Qwen3-VL-2B-Instruct",
}
PROMPT = (
    "Inspect only the visible invoice image. Return a short factual account of "
    "supplier, buyer, invoice number, date, table header and grand total. "
    "If something is not legible, state UNKNOWN. Do not invent values, borders "
    "or additional table rows. Keep item rows distinct from the grand total."
)

def preferred_device(torch, minimum_free_gib=1.8):
    """Deterministic CPU default; use CUDA only when functional and big enough."""
    if not torch.cuda.is_available():
        return "cpu", "CUDA_UNAVAILABLE"
    try:
        torch.empty(1, device="cuda:0")
        free, _ = torch.cuda.mem_get_info(0)
        if free < minimum_free_gib * (1024 ** 3):
            return "cpu", "INSUFFICIENT_FREE_VRAM"
        return "cuda:0", "CUDA_AVAILABLE"
    except Exception as exc:
        return "cpu", "CUDA_CHECK_FAILED_" + type(exc).__name__

def inference(path, model_name, device, max_new_tokens=120):
    import torch
    from transformers import AutoProcessor, AutoModelForImageTextToText
    from PIL import Image
    identifier = MODELS[model_name]
    proc = AutoProcessor.from_pretrained(identifier, trust_remote_code=False)
    # Never use GPU half precision for CPU fallback.
    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    model = AutoModelForImageTextToText.from_pretrained(
        identifier, torch_dtype=dtype, trust_remote_code=False
    ).to(device).eval()
    with Image.open(path) as im:
        image = im.convert("RGB")
        conversation = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": PROMPT}
        ]}]
        inputs = proc.apply_chat_template(
            conversation, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt"
        ).to(device)
        input_length = inputs["input_ids"].shape[-1]
        with torch.inference_mode():
            output = model.generate(**inputs, do_sample=False, max_new_tokens=max_new_tokens)
        decoded = proc.batch_decode(output[:, input_length:], skip_special_tokens=True)[0]
    del model
    return decoded

def compare_image(path, raw_text, filename, device, model_name, output_file):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    with Image.open(path) as src:
        src = ImageOps.exif_transpose(src).convert("RGB")
        src.thumbnail((960, 1000))
    w, h = 1750, max(720, src.height + 132)
    result = Image.new("RGB", (w, h), "#f7f7f7")
    draw = ImageDraw.Draw(result)
    try:
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except OSError:
        bold = font = ImageFont.load_default()
    draw.text((28, 20), "SOURCE IMAGE (unaltered)", font=bold, fill="#101828")
    draw.text((1010, 20), model_name + " / " + device + " / raw answer", font=bold, fill="#101828")
    result.paste(src, (28, 72))
    words = raw_text.replace("\r", " ").split()
    lines, line = [], ""
    for word in words:
        candidate = word if not line else line + " " + word
        if draw.textbbox((0,0),candidate,font=font)[2] > 665 and line:
            lines.append(line)
            line=word
        else:
            line=candidate
    if line: lines.append(line)
    for i, txt in enumerate(lines[:int((h-180)/30)]):
        draw.text((1010, 84+i*30),txt,font=font,fill="#182230")
    draw.text((28,h-48),"UNVERIFIED model output - not field or zone accuracy certification",font=font,fill="#b42318")
    result.save(output_file)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--model",choices=MODELS,default="smolvlm2")
    ap.add_argument("--image",type=Path,action="append",required=True)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--device",choices=["auto","cpu","cuda"],default="auto")
    ap.add_argument("--max-new-tokens",type=int,default=120)
    args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    import torch
    device,reason=preferred_device(torch,8.0 if args.model=="qwen3-vl" else 1.8)
    if args.device=="cpu":
        device,reason="cpu","MANUAL_CPU"
    elif args.device=="cuda" and device=="cpu":
        raise RuntimeError("CUDA explicitly required but unusable: "+reason)
    elif args.device=="cuda":
        reason="MANUAL_CUDA"
    result={"model":MODELS[args.model],"device_selected":device,
            "device_reason":reason,"items":[],"production_approved":False,
            "contains_real_invoice_accuracy":False}
    failed=False
    for index,path in enumerate(args.image,1):
        if not path.is_file():
            result["items"].append({"image":str(path),"status":"FAILED","error":"file missing"})
            failed=True
            continue
        sha=hashlib.sha256(path.read_bytes()).hexdigest()
        used=device; fallback_reason=None
        began=time.perf_counter()
        try:
            try:
                raw=inference(path,args.model,used,args.max_new_tokens)
            except (RuntimeError,MemoryError) as error:
                message=str(error).lower()
                if not used.startswith("cuda") or not any(t in message for t in ("cuda","cublas","cudnn","out of memory")):
                    raise
                gc.collect()
                torch.cuda.empty_cache()
                used="cpu";fallback_reason=type(error).__name__ + " GPU_RUNTIME_FALLBACK"
                raw=inference(path,args.model,"cpu",args.max_new_tokens)
            output=args.out/("comparison_%02d.png"%index)
            compare_image(path,raw,path.name,used,args.model,output)
            result["items"].append({"image":str(path),"sha256":sha,"status":"COMPLETED_UNVERIFIED",
                                    "device":used,"fallback_reason":fallback_reason,
                                    "seconds":round(time.perf_counter()-began,2),
                                    "raw_response":raw,"comparison_image":output.name})
        except Exception as error:
            failed=True
            result["items"].append({"image":str(path),"sha256":sha,"status":"FAILED",
                                   "device":used,"error":type(error).__name__+": "+str(error),
                                   "traceback":traceback.format_exc()[-3000:]})
        (args.out/"REPORT.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        print(json.dumps(result["items"][-1],ensure_ascii=False)[:1300],flush=True)
    raise SystemExit(1 if failed else 0)

if __name__=="__main__":main()
