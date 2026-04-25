"""Dump first row(s) of Shop Uploader xlsx template (headers + sample)."""
from __future__ import annotations

import re
import sys
import zipfile
import xml.etree.ElementTree as ET


def col_to_idx(col: str) -> int:
    n = 0
    for c in col:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def main(path: str) -> int:
    z = zipfile.ZipFile(path)
    ss: list[str] = []
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for si in root.findall(".//a:si", ns):
            parts: list[str] = []
            for t in si.findall(".//a:t", ns):
                if t.text:
                    parts.append(t.text)
            ss.append("".join(parts))
    except KeyError:
        pass

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    sheets = wb.findall("a:sheets/a:sheet", ns)
    if not sheets:
        print("No sheets found")
        return 1
    rid = sheets[0].attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    nsr = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    target = None
    for rel in rels.findall("r:Relationship", nsr):
        if rel.attrib["Id"] == rid:
            target = rel.attrib["Target"]
            break
    if not target:
        print("Could not resolve sheet target")
        return 1
    ws_path = "xl/" + target.replace("xl/", "")
    sheet = ET.fromstring(z.read(ws_path))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def cell_val(c: ET.Element) -> str:
        t = c.attrib.get("t")
        v = c.find("a:v", ns)
        if v is None or v.text is None:
            return ""
        if t == "s":
            return ss[int(v.text)]
        return v.text

    rows: list[list[str]] = []
    for row in sheet.findall(".//a:sheetData/a:row", ns):
        cells: dict[int, str] = {}
        for c in row.findall("a:c", ns):
            ref = c.attrib["r"]
            m = re.match(r"([A-Z]+)", ref)
            if not m:
                continue
            cells[col_to_idx(m.group(1))] = cell_val(c)
        if not cells:
            continue
        maxc = max(cells)
        arr = [""] * (maxc + 1)
        for i, v in cells.items():
            arr[i] = v
        rows.append(arr)

    print(f"Sheet: {sheets[0].attrib.get('name')!r}")
    print(f"Rows parsed: {len(rows)}")
    if not rows:
        return 0
    print(f"Header columns: {len(rows[0])}")
    nonempty = [(i, h) for i, h in enumerate(rows[0]) if str(h).strip()]
    for i, h in nonempty:
        print(f"{i}\t{h}")
    print("\n--- First 3 data rows (non-empty cells preview) ---")
    for r_i, r in enumerate(rows[1:4], start=2):
        preview = [x for x in r if str(x).strip()][:12]
        safe = [str(x).encode("ascii", "replace").decode("ascii") for x in preview]
        print(f"row {r_i}: {safe}")
    return 0


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "temp_3CkpVDwPIrAq7keFNpsulxHru12.xlsx"
    raise SystemExit(main(p))
