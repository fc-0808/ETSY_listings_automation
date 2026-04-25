"""
Overwrite incorrect meta.json fields across all product folders
for the Y2KASE phone case batch.

Run from repo root:
    python scripts/fix_meta_phonecase.py
        --products-dir "C:/Users/w088s/Downloads/y2kaseshop_newlistings_0406"

This does NOT touch price/quantity/shipping IDs — only the fields that tell
the AI what kind of product it is.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PHONE_CASE_PATCH = {
    # ── Etsy category — exact string from live export (includes taxonomy ID) ──
    "category": "Phone Cases (873)",

    # ── What to tell the AI ───────────────────────────────────────────────────
    "materials": ["Silicone"],
    "target_buyer": "iPhone users who love kawaii Y2K cute aesthetic accessories",
    "style_1": "Y2K",
    "style_2": "Kawaii",
    "keyword_seeds": [
        "phone case",
        "iPhone case",
        "cute phone case",
        "Y2K phone case",
        "kawaii phone case",
        "clear phone case",
        "luvkase",
        "y2kase",
    ],

    # ── Etsy listing metadata (sourced from live export, not guessed) ─────────
    # Live export confirms: who_made='someone_else' = "Another company or person" in Etsy UI
    "who_made": "someone_else",
    "is_made_to_order": True,
    "year_made": "2020",   # exact value from live Y2KASEshop export
    "is_vintage": False,
    "is_supply": False,
    "is_taxable": True,
    "auto_renew": True,
    "is_customizable": False,
    "is_personalizable": False,
    "personalization_is_required": False,
    "personalization_instructions": "",

    # ── IDs from live export ──────────────────────────────────────────────────
    "shipping_profile_id": "298715350841",
    "readiness_state_id": "1461134928050",
    "return_policy_id": "1462249129999",
    # Production partner: ShenZhen Mumusan Technology Co., Ltd.
    "production_partner_1": "5556766",
    # Shop section: "iPhone Cases" (ID from live export)
    "shop_section_id": "57228761",
    # featured_rank: any positive integer = "Feature this listing" ON in Etsy
    # Set to 1 so new listings appear as featured; Etsy re-ranks automatically
    "featured_rank": "1",

    "extra_notes": "",

    # ── Category-specific attributes (Phone Cases taxonomy 2848) ─────────────
    # These map to _underscore_columns in the regenerated Phone Cases template.
    # _primary_color / _secondary_color must use Etsy allowed values exactly:
    # Beige, Black, Blue, Bronze, Brown, Clear, Copper, Gold, Gray, Green,
    # Orange, Pink, Purple, Rainbow, Red, Rose gold, Silver, White, Yellow
    "category_properties": {
        "_primary_color": "Clear",      # most cases have clear/transparent back
        "_secondary_color": "Pink",     # most kawaii cases have pink accents
        "_occasion": "",
        "_holiday": "",
        "_material": "Silicone",        # matches live listing (buyer-visible Materials field)
        "_glitter": "",                 # "Yes" or "No" — set per product if needed
        "_built_in_stand": "",          # "Yes" or "No" — set per product if needed
    },

    # ── Variation matrix — option1=Phone Model (12), option2=Styles (6) ──────
    # Matches live Y2KASEshop: Prices/Quantities vary for each → Styles
    "variations": {
        "option1_name": "Phone Model",
        "models": [
            "iPhone 17 Pro Max", "iPhone 17 Pro", "iPhone 17",
            "iPhone 16 Pro Max", "iPhone 16 Pro", "iPhone 16",
            "iPhone 15 Pro Max", "iPhone 15 Pro", "iPhone 15",
            "iPhone 14 Pro Max", "iPhone 14 Pro", "iPhone 14/13",
        ],
        "option2_name": "Styles",
        "styles": [
            {"value": "Case+Grip+Charm", "price": 409.89, "quantity": 3, "sku_code": "CGM"},
            {"value": "Case+Grip",        "price": 350.11, "quantity": 3, "sku_code": "CG"},
            {"value": "Case+Charm",       "price": 350.11, "quantity": 3, "sku_code": "CC"},
            {"value": "Case Only",        "price": 261.86, "quantity": 3, "sku_code": "CO"},
            {"value": "Grip Only",        "price": 170.76, "quantity": 3, "sku_code": "GO"},
            {"value": "Charm Only",       "price": 113.82, "quantity": 3, "sku_code": "CH"},
        ],
    },
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--products-dir",
        type=Path,
        required=True,
        help="Folder whose immediate subfolders each contain meta.json",
    )
    p.add_argument(
        "--shipping-id",
        default=None,
        help="Etsy shipping_profile_id (numeric). Get from a Shop Uploader export.",
    )
    p.add_argument(
        "--return-id",
        default=None,
        help="Etsy return_policy_id (numeric). Get from a Shop Uploader export.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without writing",
    )
    args = p.parse_args()

    base = args.products_dir.resolve()
    if not base.is_dir():
        print(f"Not a directory: {base}", file=sys.stderr)
        return 1

    patch = dict(PHONE_CASE_PATCH)
    if args.shipping_id:
        patch["shipping_profile_id"] = str(args.shipping_id)
        print(f"  shipping_profile_id → {args.shipping_id}")
    if args.return_id:
        patch["return_policy_id"] = str(args.return_id)
        print(f"  return_policy_id    → {args.return_id}")
    updated = 0
    missing = 0
    for child in sorted(base.iterdir(), key=lambda x: x.name):
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.exists():
            print(f"  [SKIP] {child.name}: no meta.json")
            missing += 1
            continue

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data.update(patch)

        if args.dry_run:
            print(f"  [DRY]  {child.name}: would patch category → {PHONE_CASE_PATCH['category']}")
        else:
            meta_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(f"  [OK]   {child.name}: patched")
        updated += 1

    action = "Would update" if args.dry_run else "Updated"
    print(f"\n{action}: {updated} folders | skipped (no meta.json): {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
