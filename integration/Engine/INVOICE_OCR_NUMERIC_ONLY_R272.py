"""R272: bounded in-memory Tesseract NUMERIC ONLY OCR, for source review.

Never accepts a financial value, never writes source crops to disk, and never
modifies the original frame. Operates only with an explicitly installed local
Tesseract binary; PATH shell lookup, arbitrary extra arguments and external
services are deliberately not used.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess

_ALLOWED_PSM=(7,13)
_ALLOWED_WHITELIST="0123456789.,-"

def read_numeric_source(executable,image,psm=7):
    import cv2
    import numpy as np
    if type(executable) not in (str,Path):
        raise ValueError("Installed local Tesseract path required")
    exe=Path(executable)
    if (not exe.is_absolute() or not exe.is_file() or not os.access(exe,os.X_OK)
        or "tesseract" not in exe.name.lower()):
        raise ValueError("Verified local Tesseract executable required")
    if type(psm)!=int or psm not in _ALLOWED_PSM:
        raise ValueError("Unsupported numeric OCR page segment mode")
    if (not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or
        image.ndim not in (2,3) or (image.ndim==3 and image.shape[2]!=3) or
        not (16<=image.shape[0]<=2048 and 16<=image.shape[1]<=4096) or
        image.size>8_000_000):
        raise ValueError("Unsafe temporary original-source OCR view")
    ok,encoded=cv2.imencode(".png",image)
    if not ok or len(encoded)>2_000_000:
        raise ValueError("Unbounded temporary OCR PNG")
    cmd=[str(exe),"stdin","stdout","--psm",str(psm),
         "-c","tessedit_char_whitelist="+_ALLOWED_WHITELIST,"tsv"]
    try:
        output=subprocess.run(cmd,input=encoded.tobytes(),
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              timeout=15,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ValueError("Local numeric-only OCR unavailable") from exc
    if output.returncode or len(output.stdout)>100_000:
        raise ValueError("Local source numeric OCR failed or oversized")
    try:
        return output.stdout.decode("utf-8-sig",errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Malformed numeric OCR TSV encoding") from exc

def reader_for(executable):
    """Construct a local-only OCR callback for an already verified executable."""
    # Callers are required to provide the exact file path. No PATH searches,
    # shell commands, app installation, networking or persistent temp files.
    exe=Path(str(executable))
    if (not exe.is_absolute() or not exe.is_file() or
        "tesseract" not in exe.name.lower()):
        raise ValueError("Explicit Tesseract executable unavailable")
    def read(image,psm):
        return read_numeric_source(exe,image,psm)
    return read
