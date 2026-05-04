"""
CLI entry point.

Usage:
    python run.py                           # full pipeline (all products)
    python run.py --products-dir ./products # custom folder
    python run.py --state published         # publish immediately (costs listing fees)
    python run.py --batch-size 100          # override batch size
    python run.py --force-reupload          # re-upload images even if already on Cloudinary
    python run.py --dry-run                 # load + validate only; skip upload + AI + xlsx
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Etsy Listing Automation — image-to-Shop-Uploader compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--products-dir",
        type=Path,
        default=None,
        help="Path to the products/ folder (default: ./products)",
    )
    p.add_argument(
        "--state",
        choices=["draft", "published"],
        default=None,
        help="listing_state written to the XLSX (default: draft — safe)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Max rows per output XLSX file (default: 200)",
    )
    p.add_argument(
        "--force-reupload",
        action="store_true",
        default=False,
        help="Re-upload images to Cloudinary even if they already exist",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Load and validate product packages only; do not upload or generate AI copy",
    )
    return p.parse_args()


def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)
    args = _parse_args()

    from src.config import load_config
    cfg = load_config(skip_api_keys=args.dry_run)

    if args.products_dir:
        cfg.products_dir = args.products_dir.resolve()
    if args.state:
        cfg.listing_state = args.state
    if args.batch_size:
        cfg.batch_size = args.batch_size

    if args.dry_run:
        _run_dry(cfg)
        return

    from src.image_uploader import upload_all_packages
    from src.pipeline import run_pipeline

    if args.force_reupload:
        log.info("--force-reupload enabled: images will be re-uploaded to Cloudinary")
        from src.loader import load_all_packages
        from src.image_uploader import configure_cloudinary
        configure_cloudinary(cfg)
        packages, load_errors = load_all_packages(cfg.products_dir, cfg)
        for e in load_errors:
            log.warning(e)
        errors = upload_all_packages(packages, cfg, force_reupload=True)
        for e in errors:
            log.warning(e)
        log.info("Force re-upload complete. Re-run without --force-reupload to compile XLSX.")
        return

    rows = run_pipeline(cfg)
    sys.exit(0 if rows > 0 else 1)


def _run_dry(cfg) -> None:
    log = logging.getLogger(__name__)
    log.info("=== DRY RUN — load and validate only ===")
    from src.loader import load_all_packages
    packages, errors = load_all_packages(cfg.products_dir, cfg)

    if errors:
        log.warning("Issues found:")
        for e in errors:
            log.warning("  %s", e)
    else:
        log.info("No issues found.")

    log.info("Valid packages: %d", len(packages))
    for pkg in packages:
        log.info(
            "  [%s] images=%d  price=%.2f  category=%s",
            pkg.meta.parent_sku,
            len(pkg.image_paths),
            pkg.meta.price,
            pkg.meta.category,
        )
    log.info("=== DRY RUN complete ===")


if __name__ == "__main__":
    main()
