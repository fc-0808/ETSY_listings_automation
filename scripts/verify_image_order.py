"""Full image ordering + style mapping + Charm Only verification."""
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
    model = row[cols["option1_value"]] or ""
    style = row[cols["option2_value"]] or ""
    if model != "iPhone 17 Pro Max":
        continue
    if psku in seen:
        continue
    seen.add(psku)

    title = str(row[cols.get("title", 0)] or "")
    print(f"\n[{psku}] title={len(title)} chars: {title[:70]}")

    # Image order
    for n in range(1, 11):
        col = f"image_{n}"
        if col in cols:
            url = str(row[cols[col]] or "")
            if url:
                print(f"  image_{n}: ...{url[-38:]}")

    # Linked images per style
    print("  --- linked images per style ---")

for row in rows[1:]:
    psku = row[cols["parent_sku"]] or ""
    model = row[cols["option1_value"]] or ""
    style = row[cols["option2_value"]] or ""
    if model != "iPhone 17 Pro Max":
        continue
    url = str(row[cols.get("linked_image_url", 0)] or "")[-35:]
    opt = row[cols.get("linked_image_for_option", 0)]
    charm_ok = ""
    if style == "Charm Only" and url:
        charm_ok = "  ** SHOULD BE EMPTY **"
    elif style == "Charm Only" and not url:
        charm_ok = "  [CORRECT: empty]"
    elif url:
        charm_ok = "  [CORRECT: linked]"
    print(f"  [{psku}] {style:<22} linked={url!r}{charm_ok}")
