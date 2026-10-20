#!/usr/bin/env python3
"""R129: optional-accelerator vision-model trial; Child and AAH remain untouched.

CUDA: Qwen3-VL 2B. CPU: separate compact SmolVLM2-256M model.
Never mislabel SmolVLM results as Qwen inference. All readings unverified.
"""
from __future__ import annotations
import argparse, importlib.util, json, os, time, traceback, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def samples(out):
    spec=importlib.util.spec_from_file_location("fixture",ROOT/"scripts/benchmark-ocr.py")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.generate(out/"images")
def main():
    p=argparse.ArgumentParser();p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-new-tokens",type=int,default=48)
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    report={"experiment":"r129-adaptive-vlm","status":"STARTED","approved":False,
      "source_basis":"SYNTHETIC_NOT_REAL_INVOICES","actual_model":None,
      "cases":[],"posting_eligible":False}
    start=time.monotonic()
    try:
        from PIL import Image
        import torch
        from transformers import AutoProcessor,AutoModelForImageTextToText
        cases=samples(args.out)
        has_gpu=torch.cuda.is_available()
        report["gpu_available"]=bool(has_gpu)
        report["selected_device"]="cuda" if has_gpu else "cpu"
        preferred_model=("Qwen/Qwen3-VL-2B-Instruct" if has_gpu else
            "HuggingFaceTB/SmolVLM2-256M-Video-Instruct")
        report["selection_reason"]=(
          "CUDA available: larger Qwen candidate" if has_gpu else
          "No CUDA: small CPU VLM instead of unbounded 2B CPU timeout")
        def load(model_id,device):
            dtype=torch.float16 if device=="cuda" else torch.float32
            proc=AutoProcessor.from_pretrained(model_id)
            mdl=AutoModelForImageTextToText.from_pretrained(
                model_id,dtype=dtype,low_cpu_mem_usage=True).eval().to(device)
            return proc,mdl
        selected=preferred_model
        try:
            proc,mdl=load(selected,report["selected_device"])
        except (RuntimeError,ValueError,OSError) as e:
            if not has_gpu:raise
            report["gpu_fallback_error"]=str(e)
            report["selected_device"]="cpu"
            selected="HuggingFaceTB/SmolVLM2-256M-Video-Instruct"
            proc,mdl=load(selected,"cpu")
        report["actual_model"]=selected
        report["model_family"]="Qwen3-VL" if "Qwen/" in selected else "SmolVLM2"
        for case in cases[:1]:
            path=case["path"]; im=Image.open(path).convert("RGB")
            prompt=[{"role":"user","content":[
                {"type":"image","image":im},
                {"type":"text","text":"Read visible invoice supplier, buyer, invoice number and total. Say unknown if not visible; do not guess."}
            ]}]
            t0=time.monotonic()
            inputs=proc.apply_chat_template(prompt,tokenize=True,
                add_generation_prompt=True,return_dict=True,return_tensors="pt").to(report["selected_device"])
            with torch.inference_mode():
                gen=mdl.generate(**inputs,max_new_tokens=args.max_new_tokens,do_sample=False)
            text=proc.decode(gen[0,inputs["input_ids"].shape[-1]:],skip_special_tokens=True)
            report["cases"].append({"image":case["name"],"source_sha256":case["sha256"],
                  "seconds":round(time.monotonic()-t0,2),
                  "reading_unverified":text,"coordinates_verified":False})
        report["status"]="COMPLETED_UNVERIFIED_ACCURACY"
    except Exception as e:
        report.update(status="FAILED",error=f"{type(e).__name__}: {e}",
                    traceback=traceback.format_exc()[-7500:])
    report["total_seconds"]=round(time.monotonic()-start,2)
    (args.out/"REPORT.json").write_text(json.dumps(report,ensure_ascii=False,
                                                   indent=2),encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("cases","traceback")}),flush=True)
    return 1 if report["status"]=="FAILED" else 0
if __name__=="__main__":sys.exit(main())
