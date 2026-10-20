"""Recover a date ONLY if an OCR token contains a valid directly attached clock time.

No inferred characters, calendar coercion, trained guesses, or automatic posting.
The complete original OCR token is retained as the source evidence.
"""
import re
from datetime import datetime

JOINED = re.compile(
    r"^(?P<date>\d{1,2}(?P<sep>[-/.])\d{1,2}(?P=sep)\d{4})"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<ampm>AM|PM)$",re.I
)

def read_glued_datetime(raw):
    if not isinstance(raw,str) or len(raw)>48:return None
    original=raw
    m=JOINED.fullmatch(raw.strip())
    if not m:return None
    date=m.group("date")
    sep=m.group("sep")
    fmt={"-":"%d-%m-%Y", "/":"%d/%m/%Y", ".":"%d.%m.%Y"}[sep]
    try:
        parsed=datetime.strptime(date,fmt)
        if parsed.year<1900 or parsed.year>2100:return None
        hour=int(m.group("hour"));minute=int(m.group("minute"))
        if not (1<=hour<=12 and 0<=minute<=59):return None
        _=datetime.strptime(f"{hour}:{minute:02d}{m.group('ampm').upper()}","%I:%M%p")
    except ValueError:return None
    return {"date":date, "clock_text":raw.strip()[len(date):],
            "raw_source_text":original,
            "source_evidence":"GLUED_DATE_CLOCK_OCR_SEGMENT",
            "calendar_checked":True,
            "transcription_verified":False,"posting_eligible":False}
