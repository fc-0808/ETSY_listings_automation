"""
Create meta.json in each product subfolder (images-only → ready for the pipeline).

Usage (from repo root):
  python scripts/bootstrap_meta.py --products-dir "C:\\Users\\...\\y2kaseshop_newlistings_0406"

Skips folders that already contain meta.json unless --force.

After running: edit ONE meta.json for real shipping/return IDs and category, then consider
using search-replace across all, or re-run with a hand-crafted template JSON via --from-json.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "products" / "EXAMPLE-SKU-001" / "meta.json"


def _sanitize_folder_name(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]", "_", name.strip())[:32]
    return s.upper() if s else "SKU"


def _sku_for_folder(folder_name: str, prefix: str, digits: int) -> str:
    if folder_name.isdigit():
        body = str(int(folder_name))
        padded = body.zfill(digits)[-digits:] if digits else body
        base = f"{prefix}{padded}"
        return base[:32]
    return _sanitize_folder_name(folder_name)


def main() -> int:
    p = argparse.ArgumentParser(description="Add meta.json to each product image folder")
    p.add_argument(
        "--products-dir",
        type=Path,
        required=True,
        help="Folder whose immediate subfolders are products (each with images)",
    )
    p.add_argument(
        "--sku-prefix",
        default="Y2K-",
        help="When subfolder name is numeric, SKU = prefix + zero-padded number (default: Y2K-)",
    )
    p.add_argument(
        "--digits",
        type=int,
        default=3,
        help="Zero-pad width for numeric folder names (default: 3 → 001)",
    )
    p.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Optional path to a meta.json to clone (instead of EXAMPLE-SKU-001)",
    )
    p.add_argument("--force", action="store_true", help="Overwrite existing meta.json")
    args = p.parse_args()

    base = args.products_dir.resolve()
    if not base.is_dir():
        print(f"Not a directory: {base}", file=sys.stderr)
        return 1

    template_path = args.from_json or EXAMPLE
    if not template_path.is_file():
        print(f"Template meta not found: {template_path}", file=sys.stderr)
        return 1

    raw = json.loads(template_path.read_text(encoding="utf-8"))
    raw.pop("_comment", None)

    created = 0
    skipped = 0
    for child in sorted(base.iterdir(), key=lambda x: x.name):
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if meta_path.exists() and not args.force:
            skipped += 1
            continue

        sku = _sku_for_folder(child.name, args.sku_prefix, args.digits)
        data = json.loads(json.dumps(raw))  # deep copy
        data["parent_sku"] = sku
        data["sku"] = sku
        meta_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        created += 1
        print(f"Wrote {meta_path.relative_to(base)}")

    print(f"\nDone. Created: {created}, skipped (already had meta): {skipped}")
    print(
        "\nNext: replace shipping_profile_id and return_policy_id in these files "
        "(Shop Uploader export or Etsy), fix category/materials, then run:\n"
        f'  python run.py --products-dir "{base}"'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
