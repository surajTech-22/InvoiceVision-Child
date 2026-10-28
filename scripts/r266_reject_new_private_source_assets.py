"""R266 public-repo addition guard. This does NOT rewrite old Git history.

Only newly committed paths are checked, not existing baseline assets. Keep all
customer photographs, signed PDFs and private OCR evidence outside public Git.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

PRIVATE_BINARY_EXTENSIONS={
    ".jpg",".jpeg",".png",".webp",".bmp",".tif",".tiff",".heic",
    ".pdf",".zip",".7z",".rar",".m4a",".mp4",".mov",".onnx",".pt",
}
PRIVATE_SOURCE_PARTS={
    "source_15","private_originals","customer_invoices",
    "real_invoice_photos","private_invoice_evidence",
}

def violation(filename: str)->str|None:
    p=Path(filename.replace("\\","/"))
    if any(part.lower() in PRIVATE_SOURCE_PARTS for part in p.parts):
        return "private original/customer source path"
    if p.suffix.lower() in PRIVATE_BINARY_EXTENSIONS:
        return "binary original/media artifacts cannot be added to public research branch"
    return None

def check(base: str)->int:
    if not base or base.startswith("-") or ".." in base:
        raise ValueError("Unsafe Git base ref")
    merge=subprocess.run(["git","merge-base","HEAD",f"origin/{base}"],
                         text=True,capture_output=True,check=True).stdout.strip()
    result=subprocess.run(["git","diff","--name-only","--diff-filter=A","-z",
                          merge,"HEAD"],capture_output=True,check=True)
    names=[q.decode("utf-8","surrogateescape") for q in result.stdout.split(b"\0") if q]
    failures=[(name,violation(name)) for name in names if violation(name)]
    for name,reason in failures:
        print(f"BLOCKED_PUBLIC_ADDITION: {name}: {reason}",file=sys.stderr)
    print(f"R266 reviewed {len(names)} newly added files; rejected {len(failures)} media/private paths")
    return 1 if failures else 0

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--base",default="research/invoicevision-r153-source-associations")
    args=ap.parse_args()
    raise SystemExit(check(args.base))
