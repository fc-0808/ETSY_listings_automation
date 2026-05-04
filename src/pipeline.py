"""Orchestrates the full listing compilation pipeline."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.ai_generator import generate_copy_for_all
from src.config import Config
from src.image_uploader import upload_all_packages
from src.loader import load_all_packages
from src.models import ProductPackage
from src.report import print_run_report, save_json_log, clean_old_output
from src.xlsx_builder import build_batched_xlsx_files

log = logging.getLogger(__name__)


def run_pipeline(cfg: Config) -> int:
    """
    Full pipeline: load → upload images → generate AI copy → compile XLSX.
    Returns the number of rows written (0 on failure).
    On interruption, a checkpoint file saves progress so the run can resume
    without re-uploading images or regenerating completed AI copy.
    """
    log.info("=== Pipeline start ===")
    log.info("Products dir : %s", cfg.products_dir)
    log.info("SU template  : %s", cfg.template_path)
    log.info("Output dir   : %s", cfg.output_dir)
    log.info("Listing state: %s", cfg.listing_state)
    log.info("Batch size   : %d", cfg.batch_size)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = cfg.output_dir / f"_checkpoint_{cfg.run_label or 'run'}.json"

    # ── Load checkpoint ───────────────────────────────────────────────────────
    checkpoint = _load_checkpoint(checkpoint_path)
    if checkpoint:
        log.info("Checkpoint found: %d/%d SKUs already processed — resuming",
                 sum(1 for v in checkpoint.values() if v.get("copy_done")),
                 len(checkpoint))

    # ── Phase 1: Load packages ────────────────────────────────────────────────
    log.info("--- Phase 1: Loading product packages ---")
    packages, load_errors = load_all_packages(cfg.products_dir, cfg)
    log.info("Loaded %d valid packages, %d errors", len(packages), len(load_errors))

    if not packages:
        _abort(load_errors)
        return 0

    # ── Phase 2: Upload images (skip if URLs already checkpointed) ────────────
    needs_upload = []
    for pkg in packages:
        sku = pkg.meta.parent_sku
        saved = checkpoint.get(sku, {})
        if saved.get("image_urls") and saved.get("video_url") is not None:
            pkg.image_urls = saved["image_urls"]
            pkg.video_url = saved.get("video_url", "")
            log.info("[%s] Image URLs restored from checkpoint — skipping upload", sku)
        else:
            needs_upload.append(pkg)

    upload_errors: list[str] = []
    if needs_upload:
        log.info("--- Phase 2: Uploading images to Cloudinary (%d packages) ---",
                 len(needs_upload))
        upload_errors = upload_all_packages(needs_upload, cfg)
        # Save newly uploaded URLs to checkpoint immediately
        for pkg in needs_upload:
            if pkg.image_urls:
                sku = pkg.meta.parent_sku
                if sku not in checkpoint:
                    checkpoint[sku] = {}
                checkpoint[sku]["image_urls"] = pkg.image_urls
                checkpoint[sku]["video_url"] = pkg.video_url
        _save_checkpoint(checkpoint_path, checkpoint)
        log.info("Image URLs checkpointed for %d packages",
                 sum(1 for p in needs_upload if p.image_urls))
    else:
        log.info("--- Phase 2: Skipped — all image URLs restored from checkpoint ---")

    ready_after_upload = [p for p in packages if p.image_urls]
    log.info("%d packages have image URLs, %d upload errors",
             len(ready_after_upload), len(upload_errors))

    if not ready_after_upload:
        _abort(upload_errors)
        return 0

    # ── Phase 3: AI generation ────────────────────────────────────────────────
    log.info("--- Phase 3: Generating AI copy ---")
    ai_errors = generate_copy_for_all(
        ready_after_upload, cfg, checkpoint_path=checkpoint_path
    )
    ready_for_xlsx = [p for p in ready_after_upload if p.is_ready]
    log.info("%d packages ready for XLSX, %d AI errors",
             len(ready_for_xlsx), len(ai_errors))

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
    log_file = save_json_log(
        load_errors=load_errors,
        upload_errors=upload_errors,
        ai_errors=ai_errors,
        xlsx_warnings=xlsx_warnings,
        output_files=output_files,
        rows_total=rows_total,
        log_dir=cfg.output_dir,
    )

    # Keep only the files written in this run — delete everything older.
    clean_old_output(cfg.output_dir, keep_files=list(output_files) + [log_file])

    # Delete checkpoint now that the run completed successfully.
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        log.info("Checkpoint deleted — run complete")

    log.info("=== Pipeline complete: %d rows, %d files ===", rows_total, len(output_files))
    return rows_total


def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not read checkpoint %s: %s — starting fresh", path, exc)
    return {}


def _save_checkpoint(path: Path, data: dict) -> None:
    """Atomic write: write to a temp file then rename to avoid corruption from concurrent processes."""
    import tempfile, os
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # atomic on all platforms
    except Exception as exc:
        log.warning("Could not save checkpoint: %s", exc)


def _abort(errors: list[str]) -> None:
    log.error("Pipeline aborted. Errors:")
    for e in errors:
        log.error("  %s", e)
