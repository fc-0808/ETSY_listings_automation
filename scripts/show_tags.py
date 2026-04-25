"""Print tags from first row of each product in the most recent output XLSX."""
from __future__ import annotations
import os, re, zipfile, xml.etree.ElementTree as ET

def main() -> None:
    out = "output"
    files = sorted([f for f in os.listdir(out) if f.endswith(".xlsx")], reverse=True)
    if not files:
        print("No XLSX in output/"); return
    path = os.path.join(out, files[0])
    print(f"Reading: {files[0]}\n")

    z = zipfile.ZipFile(path)
    ss: list[str] = []
    try:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for si in root.findall(".//a:si", ns):
            parts = [t.text for t in si.findall(".//a:t", ns) if t.text]
            ss.append("".join(parts))
    except KeyError:
        pass

    wb = ET.fromstring(z.read("xl/workbook.xml"))
    ns2 = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
           "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rid = wb.findall("a:sheets/a:sheet", ns2)[0].attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    nsr = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    target = None
    for rel in rels.findall("r:Relationship", nsr):
        if rel.attrib["Id"] == rid:
            target = rel.attrib["Target"]; break
    # resolve sheet path — target from workbook rels may be relative or absolute
    t = target.lstrip("/")
    if t.startswith("worksheets/"):
        ws_path = "xl/" + t
    elif t.startswith("xl/"):
        ws_path = t
    else:
        ws_path = "xl/" + t
    sheet = ET.fromstring(z.read(ws_path))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def cv(c: ET.Element) -> str:
        t = c.attrib.get("t")
        v = c.find("a:v", ns)
        if v is None or v.text is None: return ""
        if t == "s": return ss[int(v.text)]
        return v.text

    def col_idx(ref: str) -> int:
        m = re.match(r"([A-Z]+)", ref)
        n = 0
        for ch in m.group(1): n = n * 26 + (ord(ch) - 64)
        return n - 1

    rows = list(sheet.findall(".//a:sheetData/a:row", ns))
    header: dict[int, str] = {}
    for c in rows[0].findall("a:c", ns):
        header[col_idx(c.attrib["r"])] = cv(c)

    seen: set[str] = set()
    for row in rows[1:]:
        cells: dict[int, str] = {}
        for c in row.findall("a:c", ns):
            cells[col_idx(c.attrib["r"])] = cv(c)
        psku_idx = next((i for i, n in header.items() if n == "parent_sku"), None)
        title_idx = next((i for i, n in header.items() if n == "title"), None)
        psku = cells.get(psku_idx, "") if psku_idx is not None else ""
        if not psku or psku in seen: continue
        seen.add(psku)
        title = cells.get(title_idx, "")[:80] if title_idx is not None else ""
        tag_indices = sorted([i for i, n in header.items() if n.startswith("tag_")])
        tags = [cells.get(i, "") for i in tag_indices]
        tags = [t for t in tags if t]
        print(f"SKU: {psku}")
        print(f"Title: {title}")
        print(f"Tags ({len(tags)}):")
        for idx, t in enumerate(tags, 1):
            flag = "  ⚠ TOO LONG" if len(t) > 20 else ""
            print(f"  {idx:2}. {t!r:25} ({len(t)} chars){flag}")
        print()

if __name__ == "__main__":
    main()
