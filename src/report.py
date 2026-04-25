"""Generate a run report (console + optional JSON log)."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


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
