"""Verify image_1 is the correct hero (grip/case) image for each product."""
import openpyxl, os

out = "output"
files = sorted([f for f in os.listdir(out) if f.endswith(".xlsx")], reverse=True)
print("File:", files[0])

wb = openpyxl.load_workbook(os.path.join(out, files[0]), read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(values_only=True))
header = list(rows[0])
cols = {h: i for i, h in enumerate(header) if h}

seen: set = set()
for row in rows[1:]:
    psku = row[cols["parent_sku"]] or ""
    if not psku or psku in seen:
        continue
    seen.add(psku)
    title = str(row[cols.get("title", 0)] or "")
    img1 = str(row[cols.get("image_1", 0)] or "")[-40:]
    img2 = str(row[cols.get("image_2", 0)] or "")[-40:]
    mapping_styles = {}
    # also check linked images
    li_url = str(row[cols.get("linked_image_url", 0)] or "")[-35:]
    li_opt = row[cols.get("linked_image_for_option", 0)]
    print(f"[{psku}]")
    print(f"  title ({len(title)} chars): {title[:70]}")
    print(f"  image_1 (THUMBNAIL): ...{img1}")
    print(f"  image_2:             ...{img2}")
    print(f"  linked_image_url:    ...{li_url}")
    print(f"  linked_for:          {li_opt!r}")
    print()
