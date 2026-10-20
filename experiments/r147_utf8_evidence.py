"""Lossless UTF-8 output for source-linked OCR evidence on Windows and Linux.

Export is atomic: partial writes never replace the previous report. This does
not sanitize, transliterate, change OCR readings, or approve accounting fields.
"""
from pathlib import Path
from tempfile import NamedTemporaryFile
import json
import os

def write_utf8(destination, contents):
    path=Path(destination)
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with NamedTemporaryFile(mode="w",encoding="utf-8",errors="strict",newline="\n",
                                dir=str(path.parent),prefix="."+path.name+".",
                                suffix=".incomplete",delete=False) as handle:
            tmp=Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,path)
        tmp=None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

def write_json(destination, value):
    write_utf8(destination,json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False))
