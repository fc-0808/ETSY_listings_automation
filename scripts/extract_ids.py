"""Extract shipping_profile_id and return_policy_id from a Shop Uploader export."""
from __future__ import annotations
import re, sys, zipfile, xml.etree.ElementTree as ET

def col_to_idx(col: str) -> int:
    n = 0
    for c in col:
        n = n * 26 + (ord(c) - 64)
    return n - 1

def main(path: str) -> None:
    z = zipfile.ZipFile(path)
    ss: list[str] = []
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for si in root.findall(".//a:si", ns):
            parts = []
            for t in si.findall(".//a:t", ns):
                if t.text:
                    parts.append(t.text)
            ss.append("".join(parts))
    except KeyError:
        pass

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    ns2 = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
           "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    sheets = wb.findall("a:sheets/a:sheet", ns2)
    rid = sheets[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    nsr = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    target = None
    for rel in rels.findall("r:Relationship", nsr):
        if rel.attrib["Id"] == rid:
            target = rel.attrib["Target"]; break
    ws_path = "xl/" + target.replace("xl/", "")
    sheet = ET.fromstring(z.read(ws_path))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def cell_val(c: ET.Element) -> str:
        t = c.attrib.get("t")
        v = c.find("a:v", ns)
        if v is None or v.text is None: return ""
        if t == "s": return ss[int(v.text)]
        return v.text

    rows = list(sheet.findall(".//a:sheetData/a:row", ns))
    if not rows: print("empty"); return

    # parse header
    header: dict[int, str] = {}
    for c in rows[0].findall("a:c", ns):
        ref = c.attrib["r"]
        m = re.match(r"([A-Z]+)", ref)
        if m: header[col_to_idx(m.group(1))] = cell_val(c)

    print("Header columns found:")
    for idx, name in sorted(header.items()):
        if name in ("shipping_profile_id", "return_policy_id", "readiness_state_id"):
            print(f"  col {idx}: {name}")

    # find first data row with values
    targets = {"shipping_profile_id", "return_policy_id", "readiness_state_id"}
    for row in rows[1:5]:
        cells: dict[int, str] = {}
        for c in row.findall("a:c", ns):
            ref = c.attrib["r"]
            m = re.match(r"([A-Z]+)", ref)
            if m: cells[col_to_idx(m.group(1))] = cell_val(c)
        for col_idx, col_name in header.items():
            if col_name in targets:
                val = cells.get(col_idx, "")
                if val:
                    print(f"  {col_name} = {val}")

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "export_for_job_3Cn2nRdSASSkqvOChgsYWfiw12f.xlsx"
    main(p)
