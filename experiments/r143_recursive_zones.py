"""Whitespace semantic subdivision; never claims a printed physical border.

Every source token is assigned exactly once. Straddling or malformed evidence
prevents subdivision. Role classification remains a separate, reviewable input.
"""
from __future__ import annotations
import math


def rectangle(box):
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        raise ValueError('Invalid region')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) for v in box):
        raise ValueError('Invalid region coordinate')
    if not (0 <= box[0] < box[2] and 0 <= box[1] < box[3]):
        raise ValueError('Empty or inverted region')
    return tuple(box)


def subdivide(parent, tokens, min_gutter=7, max_depth=8):
    parent = rectangle(parent)
    if min_gutter <= 0 or not math.isfinite(min_gutter):
        raise ValueError('Invalid gutter')
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or not 0 <= max_depth <= 32:
        raise ValueError('Invalid recursion limit')
    identities = set()
    for t in tokens:
        if t['id'] in identities:
            raise ValueError('Duplicate source token identity')
        identities.add(t['id'])
        b = rectangle(t['box'])
        if not (parent[0] <= b[0] < b[2] <= parent[2] and
                parent[1] <= b[1] < b[3] <= parent[3]):
            raise ValueError('Source token outside parent')

    def build(bounds, members, depth):
        node = {'box': list(bounds), 'source_tokens': [t['id'] for t in members],
                'kind': 'SEMANTIC_REGION_HYPOTHESIS', 'physical_border_verified': False,
                'posting_eligible': False, 'children': []}
        roles = {t.get('role', 'unknown') for t in members}
        # Unknown evidence stays with its parent; geometry cannot invent a role.
        if depth >= max_depth or len(members) < 2 or 'unknown' in roles or len(roles) < 2:
            return node
        cuts = []
        for axis in (0, 1):
            ordered = sorted(members, key=lambda t: t['box'][axis])
            end = ordered[0]['box'][axis+2]
            for t in ordered[1:]:
                start = t['box'][axis]
                if start-end >= min_gutter:
                    cut = (start+end)/2
                    left = [q for q in members if q['box'][axis+2] <= cut]
                    right = [q for q in members if q['box'][axis] >= cut]
                    if left and right and len(left)+len(right) == len(members):
                        # Never separate tokens belonging to one label/value group.
                        a = {q['group'] for q in left if q.get('group') is not None}
                        b = {q['group'] for q in right if q.get('group') is not None}
                        if not a & b:
                            cuts.append(((start-end)/(bounds[axis+2]-bounds[axis]),
                                         axis, cut, left, right))
                end = max(end, t['box'][axis+2])
        if not cuts:
            return node
        _, axis, cut, left, right = max(cuts, key=lambda c: c[0])
        a, b = list(bounds), list(bounds)
        a[axis+2], b[axis] = cut, cut
        node['children'] = [build(a, left, depth+1), build(b, right, depth+1)]
        return node
    return build(parent, list(tokens), 0)
