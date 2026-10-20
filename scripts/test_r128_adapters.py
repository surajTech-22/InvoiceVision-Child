#!/usr/bin/env python3
"""Run deterministic, hardware-independent regression checks for R128 adapters."""
from __future__ import annotations
import importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[1]
p=root/"experiments"/"r128_semantic_zone_review.py"
spec=importlib.util.spec_from_file_location("zone_adapter",p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
assert m.classify("SUPPLIER: BLUE COMPANY")=="supplier"
assert m.classify("Billed to GREEN ENTERPRISES")=="buyer"
assert m.classify("Invoice No: 12345")=="invoice_number"
assert m.classify("Grand Total 500")=="totals"
assert m.classify("CGST 5%")=="tax"
rows=m.parse_rows("<table><tr><td>ITEM</td><td>QTY</td></tr><tr><td>Rice</td><td>10</td></tr><tr><td>TOTAL 500</td><td></td></tr></table>")
assert len(rows)==3
issues=[]
node=m.inspect_table("<table><tr><td>ITEM</td><td>QTY</td></tr><tr><td>Rice</td><td>10</td></tr><tr><td>TOTAL 500</td><td></td></tr></table>",
                     [27,247,1229,597],"fixture",issues)
assert [n["meaning"] for n in node["children"]]==["item_header","item_row","totals"],node
assert "Total embedded" in " ".join(issues)
assert not node["physically_verified"] and not node["posting_eligible"]
assert all(not child["physically_verified"] and child["source_box"] is None for child in node["children"])
# Original model physical box is preserved, even when wrong.
assert node["source_box"]==[27,247,1229,597]
print("R128 adapter unit checks PASS; synthetic fixture is not invoice inference")
