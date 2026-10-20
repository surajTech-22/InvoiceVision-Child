"""Quarter-turn hypotheses with reversible source geometry; no orientation approval."""
from .r138_field_evidence import box_of
from .r143_source_evidence import inspect


def point(x, y, width, height, turns):
    turns %= 4
    if turns == 0: return [x, y]
    if turns == 1: return [y, width-x]
    if turns == 2: return [width-x, height-y]
    return [height-y, x]


def rotate_case(case, turns):
    if turns not in (0, 1, 2, 3): raise ValueError('Quarter turns required')
    width, height = case['source_width'], case['source_height']
    result = dict(case)
    result['source_width'], result['source_height'] = (height, width) if turns % 2 else (width, height)
    boxes = []
    for poly in case.get('raw_boxes', []):
        b = box_of(poly)
        if b is None:
            boxes.append([]); continue
        corners = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]
        boxes.append([point(x, y, width, height, turns) for x, y in corners])
    result['raw_boxes'] = boxes
    return result


def hypotheses(case, engine, source_bytes):
    # Validate original frame and byte identity before evaluating transformed views.
    inspect(case, engine, source_bytes)
    records = []
    for turns in range(4):
        rotated = rotate_case(case, turns)
        result = inspect(rotated, engine, source_bytes)
        for row in result['candidates']:
            row['reading_frame_quarter_turns_ccw'] = turns
            row['reading_regions'] = row.pop('source_regions')
            row['source_regions'] = [list(box_of(case['raw_boxes'][i])) for i in row['source_tokens']]
            row['source_polygons'] = [case['raw_boxes'][i] for i in row['source_tokens']]
            row['orientation_verified'] = False
        records.append(result)
    return records
