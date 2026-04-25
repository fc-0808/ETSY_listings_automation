# Etsy Listing Automation

Private tooling for bulk-creating Etsy listings across my own shops.

**Pipeline:** product image folders + structured metadata → OpenAI vision generates title / description / tags → Cloudinary hosts images → Shop Uploader–compatible XLSX compiled → upload to [shopuploader.com](https://www.shopuploader.com/) → Etsy drafts created in bulk.

No API keys, tokens, or secrets belong in this repo (use `.env`).

---

## Shop Uploader template (per Etsy shop)

The compiler reads **row 1** of a Shop Uploader–generated workbook to determine **column order** (and any extra category columns for that shop).

- **Default:** `Y2KASEshop.xlsx` in the repo root, if that file exists.
- **Otherwise:** falls back to `temp_3CkpVDwPIrAq7keFNpsulxHru12.xlsx` if you still use it.
- **Override:** set in `.env`:
  ```env
  SHOP_UPLOADER_TEMPLATE=MyOtherShop.xlsx
  ```
  (Path relative to repo root, or absolute.)

When you regenerate a template in Shop Uploader for a different shop or category set, replace or point `SHOP_UPLOADER_TEMPLATE` at that file. Extra columns your compiler does not fill are left blank.

## Architecture

```
products/
  <PARENT_SKU>/
    meta.json        ← price, category, materials, keyword seeds, shop IDs
    01.jpg           ← product images (up to 10, sorted by filename)
    02.jpg
    ...

run.py               ← CLI entry point
src/
  config.py          ← env-var config loader
  models.py          ← domain models + validation
  loader.py          ← load + validate all product packages
  image_uploader.py  ← upload images → Cloudinary → stable URLs
  ai_generator.py    ← OpenAI vision → title / description / tags
  xlsx_builder.py    ← build Shop Uploader XLSX rows
  pipeline.py        ← orchestrate all phases
  report.py          ← console + JSON run report

output/              ← generated XLSX files + run logs (git-ignored)
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in your keys (never commit .env)
```

You need:
- **OpenAI API key** (GPT-4o with vision) — [platform.openai.com](https://platform.openai.com/api-keys)
- **Cloudinary account** (free tier is fine) — [cloudinary.com](https://cloudinary.com/users/register/free)
- **Shop Uploader account** with an Etsy shop connected — [shopuploader.com](https://www.shopuploader.com/)

### 3. Get your Etsy IDs from Shop Uploader

Export one existing listing from Shop Uploader and note:
- `shipping_profile_id`
- `return_policy_id`

These go into each product's `meta.json`.

---

## Bulk folder of images only (e.g. `y2kaseshop_newlistings_0406`)

If you already have **one subfolder per product** with images but **no `meta.json` yet**:

```powershell
cd "…\ETSY_listings_automation"
python scripts/bootstrap_meta.py --products-dir "C:\Users\w088s\Downloads\y2kaseshop_newlistings_0406"
```

That writes a **`meta.json` into each subfolder** (SKUs like `Y2K-001`, `Y2K-002`, … for numeric folder names). Then:

1. **Edit shipping / return policy IDs** (and `category`, `price`, etc.) — use multi-file find/replace in your editor across all `meta.json` files, or fix one and copy.
2. **Do not** manually upload images to Cloudinary; **`python run.py`** uploads them when you point at that folder:

```powershell
python run.py --dry-run --products-dir "C:\Users\w088s\Downloads\y2kaseshop_newlistings_0406"
python run.py --products-dir "C:\Users\w088s\Downloads\y2kaseshop_newlistings_0406"
```

---

## Adding a product

1. Create a folder under `products/` named with your SKU (A–Z, 0–9, `-`, `_`, max 32 chars):
   ```
   products/MY-PRODUCT-001/
   ```
2. Copy `products/EXAMPLE-SKU-001/meta.json` and fill in every field.
3. Drop your product images into the folder (JPG/PNG, named so they sort in the right order: `01.jpg`, `02.jpg`, …).

---

## Running the pipeline

### Dry run (validate only — no API calls)

```bash
python run.py --dry-run
```

### Full run (generates drafts by default)

```bash
python run.py
```

### Publish instead of draft (charges Etsy listing fees)

```bash
python run.py --state published
```

### Custom folder or batch size

```bash
python run.py --products-dir ./my_products --batch-size 100
```

### Force re-upload images (if you replaced images in a folder)

```bash
python run.py --force-reupload
```

---

## Output

Each run writes to `output/`:

| File | Contents |
|------|----------|
| `shopuploader_<timestamp>_batch001_of_003.xlsx` | Upload-ready XLSX for Shop Uploader |
| `run_log_<timestamp>.json` | Full error + warning log |

---

## Uploading to Shop Uploader

1. Open [shopuploader.com](https://www.shopuploader.com/) and connect the target Etsy shop.
2. Upload one `batch*.xlsx` file at a time.
3. Review the per-row error report Shop Uploader returns.
4. Fix any failed rows in `meta.json` or re-run for those SKUs.
5. Once drafts are reviewed on Etsy, publish using Shop Uploader's `state_change` action (or manually).

---

## Troubleshooting

| Symptom | Fix |
|--------|-----|
| `DLL load failed while importing jiter` (Windows) | Use the pinned versions in `requirements.txt` (`openai<1.40`). Reinstall: `pip install -r requirements.txt` |
| `Client.__init__() got an unexpected keyword argument 'proxies'` | Downgrade **httpx** to `<0.28` (see `requirements.txt`), then `pip install -r requirements.txt` |
| `429` / `insufficient_quota` from OpenAI | Add billing / credit at [platform.openai.com/settings/billing](https://platform.openai.com/settings/billing), then re-run `python run.py …` |

---

## Safety rules

- **Always run `--dry-run` first** on a new batch to catch schema issues before any API calls.
- **`LISTING_STATE=draft`** (default) is free on Etsy. Only switch to `published` after spot-checking generated copy.
- **Batch ≤ 200–300 rows** per XLSX to stay well within Shop Uploader's reliability range.
- **Never put secrets in this repo** — `.env` is in `.gitignore`.
