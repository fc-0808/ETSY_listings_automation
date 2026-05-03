"""Generate a run report (console + optional JSON log)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Glob patterns for files the pipeline manages in the output folder.
_OUTPUT_XLSX_GLOB = "UPLOAD_TO_SHOPUPLOADER__*.xlsx"
_OUTPUT_LOG_GLOB  = "RUN_LOG__*.json"


def clean_old_output(output_dir: Path, keep_files: list[Path]) -> None:
    """Delete all pipeline-managed files in output_dir except those in keep_files.

    Called after a successful run so only the latest XLSX + log remain,
    keeping the output folder uncluttered.
    """
    keep = {p.resolve() for p in keep_files}
    removed: list[str] = []
    for pattern in (_OUTPUT_XLSX_GLOB, _OUTPUT_LOG_GLOB):
        for f in output_dir.glob(pattern):
            if f.resolve() not in keep:
                try:
                    f.unlink()
                    removed.append(f.name)
                except OSError as exc:
                    log.warning("Could not remove old output file %s: %s", f.name, exc)
    if removed:
        log.info("Cleaned %d old output file(s): %s", len(removed), ", ".join(removed))
    else:
        log.debug("Output folder already clean — nothing to remove.")


def print_run_report(
    load_errors: list[str],
    upload_errors: list[str],
    ai_errors: list[str],
    xlsx_warnings: list[str],
    output_files: list[Path],
    rows_total: int,
) -> None:
    border = "=" * 64
    print(f"\n{border}")
    print("  LISTING COMPILER RUN REPORT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(border)

    _section("Load errors", load_errors)
    _section("Image upload errors", upload_errors)
    _section("AI generation errors", ai_errors)
    _section("XLSX warnings", xlsx_warnings)

    all_errors = load_errors + upload_errors + ai_errors + xlsx_warnings
    print(f"\n  Total rows written : {rows_total}")
    print(f"  Total issues       : {len(all_errors)}")
    print(f"  Output files       : {len(output_files)}")
    for f in output_files:
        print(f"    → {f}")
    print(border)

    if all_errors:
        print("\n  ACTION REQUIRED: Review issues above before uploading to Shop Uploader.\n")
    else:
        print("\n  All packages processed cleanly. Ready to upload to Shop Uploader.\n")


def save_json_log(
    load_errors: list[str],
    upload_errors: list[str],
    ai_errors: list[str],
    xlsx_warnings: list[str],
    output_files: list[Path],
    rows_total: int,
    log_dir: Path,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"RUN_LOG__{timestamp}.json"
    payload = {
        "timestamp": timestamp,
        "rows_written": rows_total,
        "output_files": [str(f) for f in output_files],
        "load_errors": load_errors,
        "upload_errors": upload_errors,
        "ai_errors": ai_errors,
        "xlsx_warnings": xlsx_warnings,
    }
    log_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Run log saved: %s", log_path)
    return log_path


def _section(title: str, items: list[str]) -> None:
    if not items:
        print(f"\n  {title}: none")
        return
    print(f"\n  {title} ({len(items)}):")
    for item in items:
        print(f"    **  {item}")
