"""Parse Shop Uploader upload report and show all errors/results."""
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
                if t.text: parts.append(t.text)
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
    if not rows:
        print("Empty report")
        return

    header: dict[int, str] = {}
    for c in rows[0].findall("a:c", ns):
        ref = c.attrib["r"]
        m = re.match(r"([A-Z]+)", ref)
        if m: header[col_to_idx(m.group(1))] = cell_val(c)

    print("Columns:", list(header.values()))
    print(f"Total rows (excluding header): {len(rows)-1}\n")

    status_counts: dict[str, int] = {}
    for row in rows[1:]:
        cells: dict[int, str] = {}
        for c in row.findall("a:c", ns):
            ref = c.attrib["r"]
            m = re.match(r"([A-Z]+)", ref)
            if m: cells[col_to_idx(m.group(1))] = cell_val(c)
        row_data = {header[i]: cells.get(i, "") for i in header}

        status = row_data.get("results", row_data.get("status", row_data.get("Status", "")))
        error_msg = ""
        for key in ("error", "Error", "message", "Message", "errors", "Errors"):
            if row_data.get(key):
                error_msg = row_data[key]
                break
        sku = row_data.get("sku", row_data.get("parent_sku", ""))
        listing_id = row_data.get("listing_id", "")

        status_counts[status] = status_counts.get(status, 0) + 1

        # Show first 5 rows regardless + all non-success rows
        row_num = rows.index(row) + 1
        if row_num <= 5 or (status and status.lower() not in ("success", "ok", "created", "")):
            safe_status = status.encode("ascii", "replace").decode("ascii")
            safe_error = error_msg.encode("ascii", "replace").decode("ascii")[:150]
            safe_sku = sku.encode("ascii", "replace").decode("ascii")
            print(f"row {row_num}: status={safe_status!r} sku={safe_sku} listing_id={listing_id} err={safe_error}")

    print("\n--- Status summary ---")
    for k, v in sorted(status_counts.items()):
        print(f"  {k!r}: {v} rows")

if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "report_for_shop_3ClA2vKCzroOGwJA4UubEUEYe1e_job_3Cn5lGPi8Nk6fufQymQjvvAO0V5.xlsx"
    main(p)
