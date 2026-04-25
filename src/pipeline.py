"""Orchestrates the full listing compilation pipeline."""
from __future__ import annotations

import logging
from pathlib import Path

from src.ai_generator import generate_copy_for_all
from src.config import Config
from src.image_uploader import upload_all_packages
from src.loader import load_all_packages
from src.report import print_run_report, save_json_log
from src.xlsx_builder import build_batched_xlsx_files

log = logging.getLogger(__name__)


def run_pipeline(cfg: Config) -> int:
    """
    Full pipeline: load → upload images → generate AI copy → compile XLSX.
    Returns the number of rows written (0 on failure).
    """
    log.info("=== Pipeline start ===")
    log.info("Products dir : %s", cfg.products_dir)
    log.info("SU template  : %s", cfg.template_path)
    log.info("Output dir   : %s", cfg.output_dir)
    log.info("Listing state: %s", cfg.listing_state)
    log.info("Batch size   : %d", cfg.batch_size)

    # ── Phase 1: Load packages ────────────────────────────────────────────────
    log.info("--- Phase 1: Loading product packages ---")
    packages, load_errors = load_all_packages(cfg.products_dir)
    log.info("Loaded %d valid packages, %d errors", len(packages), len(load_errors))

    if not packages:
        _abort(load_errors)
        return 0

    # ── Phase 2: Upload images ────────────────────────────────────────────────
    log.info("--- Phase 2: Uploading images to Cloudinary ---")
    upload_errors = upload_all_packages(packages, cfg)
    ready_after_upload = [p for p in packages if p.image_urls]
    log.info("%d packages have image URLs, %d upload errors", len(ready_after_upload), len(upload_errors))

    if not ready_after_upload:
        _abort(upload_errors)
        return 0

    # ── Phase 3: AI generation ────────────────────────────────────────────────
    log.info("--- Phase 3: Generating AI copy ---")
    ai_errors = generate_copy_for_all(ready_after_upload, cfg)
    ready_for_xlsx = [p for p in ready_after_upload if p.is_ready]
    log.info("%d packages ready for XLSX, %d AI errors", len(ready_for_xlsx), len(ai_errors))

    if not ready_for_xlsx:
        _abort(ai_errors)
        return 0

    # ── Phase 4: Build XLSX ───────────────────────────────────────────────────
    log.info("--- Phase 4: Building XLSX batch files ---")
    output_files, xlsx_warnings = build_batched_xlsx_files(ready_for_xlsx, cfg)
    rows_total = sum(1 for _ in ready_for_xlsx)

    # ── Report ────────────────────────────────────────────────────────────────
    print_run_report(
        load_errors=load_errors,
        upload_errors=upload_errors,
        ai_errors=ai_errors,
        xlsx_warnings=xlsx_warnings,
        output_files=output_files,
        rows_total=rows_total,
    )
    save_json_log(
        load_errors=load_errors,
        upload_errors=upload_errors,
        ai_errors=ai_errors,
        xlsx_warnings=xlsx_warnings,
        output_files=output_files,
        rows_total=rows_total,
        log_dir=cfg.output_dir,
    )

    log.info("=== Pipeline complete: %d rows, %d files ===", rows_total, len(output_files))
    return rows_total


def _abort(errors: list[str]) -> None:
    log.error("Pipeline aborted. Errors:")
    for e in errors:
        log.error("  %s", e)
