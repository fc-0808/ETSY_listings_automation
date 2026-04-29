"""
Regenerate AI descriptions only — reuses existing Cloudinary URLs from the latest XLSX.

This skips Phase 2 (Cloudinary upload) entirely, saving time and API quota.
Only runs: Phase 3 (AI copy generation) → Phase 4 (XLSX build).

Usage:
    python scripts/regen_descriptions.py
    python scripts/regen_descriptions.py --products-dir Samples
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.ai_generator import generate_copy_for_all
from src.loader import load_all_packages
from src.report import print_run_report, save_json_log
from src.xlsx_builder import build_batched_xlsx_files

import openpyxl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("regen_descriptions")


def _load_existing_urls(output_dir: Path) -> dict[str, dict]:
    """Read image_N and video_1 URLs from the most recent XLSX, keyed by parent_sku."""
    xlsx_files = sorted(
        [f for f in output_dir.iterdir() if f.name.startswith("UPLOAD_TO_SHOPUPLOADER") and f.suffix == ".xlsx"],
        reverse=True,
    )
    if not xlsx_files:
        log.error("No existing XLSX found in %s — cannot reuse URLs. Run full pipeline first.", output_dir)
        sys.exit(1)

    fname = xlsx_files[0]
    log.info("Loading existing URLs from: %s", fname.name)

    wb = openpyxl.load_workbook(str(fname), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    h = {v: i for i, v in enumerate(header) if v}

    result: dict[str, dict] = {}
    for row in rows[1:]:
        psku = str(row[h["parent_sku"]] or "").strip()
        if not psku or psku in result:
            continue

        img_urls = []
        for n in range(1, 11):
            col = f"image_{n}"
            if col in h:
                u = str(row[h[col]] or "").strip()
                if u:
                    img_urls.append(u)

        video_url = ""
        if "video_1" in h:
            video_url = str(row[h["video_1"]] or "").strip()

        result[psku] = {"image_urls": img_urls, "video_url": video_url}

    wb.close()
    log.info("Found URLs for %d SKUs: %s", len(result), list(result.keys()))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate AI copy only, reusing existing Cloudinary URLs")
    parser.add_argument("--products-dir", default=None,
                        help="Products folder (default: auto from config / Samples if present)")
    args = parser.parse_args()

    cfg = load_config()

    # Determine products directory
    if args.products_dir:
        products_dir = Path(args.products_dir)
        if not products_dir.is_absolute():
            products_dir = ROOT / products_dir
    else:
        samples = ROOT / "Samples"
        products_dir = samples if samples.exists() else cfg.products_dir
    log.info("Products dir: %s", products_dir)

    # Phase 1: Load packages
    log.info("--- Phase 1: Loading product packages ---")
    packages, load_errors = load_all_packages(products_dir)
    log.info("Loaded %d packages, %d errors", len(packages), len(load_errors))
    if not packages:
        for e in load_errors:
            log.error("  %s", e)
        sys.exit(1)

    # Inject existing Cloudinary URLs — no re-upload
    log.info("--- Phase 2 (SKIP upload): Injecting existing URLs from latest XLSX ---")
    existing = _load_existing_urls(cfg.output_dir)
    for pkg in packages:
        sku = pkg.meta.parent_sku
        if sku in existing:
            pkg.image_urls = existing[sku]["image_urls"]
            pkg.video_url = existing[sku]["video_url"]
            log.info("[%s] Injected %d image URL(s)%s",
                     sku, len(pkg.image_urls),
                     f" + video" if pkg.video_url else "")
        else:
            log.warning("[%s] Not found in existing XLSX — will skip XLSX build for this SKU", sku)

    ready = [p for p in packages if p.image_urls]
    if not ready:
        log.error("No packages have image URLs — cannot proceed")
        sys.exit(1)

    # Phase 3: AI copy generation with the UPDATED prompt
    log.info("--- Phase 3: Generating AI copy (new prompt) ---")
    ai_errors = generate_copy_for_all(ready, cfg)
    ready_for_xlsx = [p for p in ready if p.is_ready]
    log.info("%d packages ready for XLSX, %d AI errors", len(ready_for_xlsx), len(ai_errors))
    if ai_errors:
        for e in ai_errors:
            log.warning("  AI error: %s", e)
    if not ready_for_xlsx:
        log.error("No packages ready — aborting")
        sys.exit(1)

    # Phase 4: Build XLSX
    log.info("--- Phase 4: Building XLSX ---")
    output_files, xlsx_warnings = build_batched_xlsx_files(ready_for_xlsx, cfg)

    print_run_report(
        load_errors=load_errors,
        upload_errors=[],
        ai_errors=ai_errors,
        xlsx_warnings=xlsx_warnings,
        output_files=output_files,
        rows_total=len(ready_for_xlsx),
    )
    save_json_log(
        load_errors=load_errors,
        upload_errors=[],
        ai_errors=ai_errors,
        xlsx_warnings=xlsx_warnings,
        output_files=output_files,
        rows_total=len(ready_for_xlsx),
        log_dir=cfg.output_dir,
    )
    log.info("Done. %d XLSX file(s) written.", len(output_files))


if __name__ == "__main__":
    main()
