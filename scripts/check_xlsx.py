"""Verify Case Only qty and readiness columns in latest output XLSX."""
import openpyxl, os

out = "output"
files = sorted([f for f in os.listdir(out) if f.endswith(".xlsx")], reverse=True)
if not files:
    print("No XLSX found"); exit()

print("Checking:", files[0])
wb = openpyxl.load_workbook(os.path.join(out, files[0]), read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(values_only=True))
header = list(rows[0])
cols = {h: i for i, h in enumerate(header) if h}

qty_idx = cols.get("quantity")
opt2_idx = cols.get("option2_value")

for row in rows[1:]:
    if opt2_idx is not None and row[opt2_idx] == "Case Only":
        print(f"Case Only qty = {row[qty_idx]!r}")
        break

for c in ["option1_changes_readiness_state", "option2_changes_readiness_state"]:
    status = "IN XLSX" if c in cols else "MISSING"
    print(f"{c}: {status}")
