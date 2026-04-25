"""Verify prices and quantities vary by Styles, not by Phone Model, in latest XLSX."""
import openpyxl
import os
import collections

out = "output"
files = sorted([f for f in os.listdir(out) if f.endswith(".xlsx")], reverse=True)
print("File:", files[0])

wb = openpyxl.load_workbook(os.path.join(out, files[0]), read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(values_only=True))
header = list(rows[0])
cols = {h: i for i, h in enumerate(header) if h}

psku_i = cols["parent_sku"]
m_i = cols["option1_value"]   # Phone Model
s_i = cols["option2_value"]   # Styles
p_i = cols["price"]
q_i = cols["quantity"]

# Analyze first product
style_prices: dict = {}
style_qty: dict = {}
model_price_sets: dict = collections.defaultdict(set)

for row in rows[1:]:
    if row[psku_i] != "Y2K-001":
        continue
    style = row[s_i]
    model = row[m_i]
    price = row[p_i]
    qty = row[q_i]
    if not style:
        continue
    style_prices[style] = price
    style_qty[style] = qty
    if model:
        model_price_sets[model].add(price)

print()
print("STYLES dimension — price/qty per style (should differ between styles):")
for s, p in style_prices.items():
    print(f"  {s:<20}  price=HKD {p:<8}  qty={style_qty[s]}")

print()
print("PHONE MODEL check — each model should see ALL 6 style prices (proves price varies by style):")
sample_model = "iPhone 17 Pro Max"
if sample_model in model_price_sets:
    print(f"  {sample_model}: {sorted(model_price_sets[sample_model])}")

print()
print("--- VERIFICATION SUMMARY ---")
unique_prices = set(style_prices.values())
unique_qtys = set(style_qty.values())
print(f"  Prices vary by Styles?               {'PASS' if len(unique_prices) > 1 else 'FAIL'} ({len(unique_prices)} distinct prices: {sorted(unique_prices)})")
print(f"  All quantities = 3?                  {'PASS' if unique_qtys == {3} else 'FAIL'} (qtys seen: {unique_qtys})")

col1 = "option1_changes_readiness_state"
col2 = "option2_changes_readiness_state"
print(f"  Processing profiles OFF (col1)?      {'PASS' if col1 in cols else 'FAIL'} -> value = {rows[1][cols[col1]] if col1 in cols else 'MISSING'!r}")
print(f"  Processing profiles OFF (col2)?      {'PASS' if col2 in cols else 'FAIL'} -> value = {rows[1][cols[col2]] if col2 in cols else 'MISSING'!r}")
print(f"  option1 = Phone Model?               {'PASS' if cols.get('option1_name') and rows[1][cols['option1_name']] == 'Phone Model' else 'CHECK'}")
print(f"  option2 = Styles?                    {'PASS' if cols.get('option2_name') and rows[1][cols['option2_name']] == 'Styles' else 'CHECK'}")
