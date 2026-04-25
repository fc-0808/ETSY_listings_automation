"""Build Shop Uploader–compatible XLSX files from processed product packages."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from src.config import Config
from src.models import ProductPackage

log = logging.getLogger(__name__)

# Fallback if template file is missing (same as standard Shop Uploader export).
DEFAULT_COLUMNS: list[str] = [
    "listing_id", "parent_sku", "sku",
    "title", "description",
    "price", "quantity",
    "category",
    "_primary_color", "_secondary_color", "_occasion", "_holiday",
    "_deprecated_diameter", "_deprecated_dimensions", "_deprecated_fabric",
    "_deprecated_finish", "_deprecated_flavor", "_deprecated_height",
    "_deprecated_length", "_deprecated_material", "_deprecated_pattern",
    "_deprecated_scent", "_deprecated_size", "_deprecated_style",
    "_deprecated_weight", "_deprecated_width", "_deprecated_device",
    "option1_name", "option1_value",
    "option2_name", "option2_value",
    "image_1", "image_2", "image_3", "image_4", "image_5",
    "image_6", "image_7", "image_8", "image_9", "image_10",
    "shipping_profile_id", "readiness_state_id", "return_policy_id",
    "length", "width", "height", "dimensions_unit",
    "weight", "weight_unit",
    "type",
    "who_made", "is_made_to_order", "year_made",
    "is_vintage", "is_supply", "is_taxable", "auto_renew",
    "is_customizable", "is_personalizable", "personalization_is_required",
    "personalization_instructions", "personalization_char_count_max",
    "style_1", "style_2",
    "tag_1", "tag_2", "tag_3", "tag_4", "tag_5", "tag_6", "tag_7",
    "tag_8", "tag_9", "tag_10", "tag_11", "tag_12", "tag_13",
    "action", "listing_state", "overwrite_images",
]

_VIDEO_COL = "video_1"  # Shop Uploader column for listing video URL

_cached_columns: tuple[Path, list[str]] | None = None


def load_output_columns(cfg: Config) -> list[str]:
    """
    Read header row from cfg.template_path so each Etsy shop's generated template
    drives column order and any extra category columns.
    """
    global _cached_columns
    path = cfg.template_path.resolve()
    if _cached_columns and _cached_columns[0] == path:
        return list(_cached_columns[1])

    if not path.exists():
        log.warning("Shop Uploader template not found: %s — using DEFAULT_COLUMNS", path)
        cols = list(DEFAULT_COLUMNS)
        _cached_columns = (path, cols)
        return cols

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        row1 = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not row1:
            log.warning("Empty template: %s — using DEFAULT_COLUMNS", path)
            cols = list(DEFAULT_COLUMNS)
        else:
            cols = [str(c).strip() if c is not None else "" for c in row1]
            while cols and cols[-1] == "":
                cols.pop()
            if not cols:
                cols = list(DEFAULT_COLUMNS)
    finally:
        wb.close()

    unknown = [c for c in cols if c and c not in _compiler_column_keys()]
    if unknown:
        log.info(
            "Template has %d column(s) not filled by the compiler (left blank): %s",
            len(unknown),
            ", ".join(unknown[:12]) + ("…" if len(unknown) > 12 else ""),
        )

    _cached_columns = (path, cols)
    log.info("Loaded %d columns from template: %s", len(cols), path.name)
    return list(cols)


def clear_column_cache() -> None:
    """For tests or switching template mid-process."""
    global _cached_columns
    _cached_columns = None


def _safe_label(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "_", name.strip())[:40]


def _compiler_column_keys() -> frozenset[str]:
    return frozenset(DEFAULT_COLUMNS)


_HEADER_FILL = PatternFill("solid", fgColor="1a1a2e")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)


def build_xlsx(
    packages: list[ProductPackage],
    cfg: Config,
    batch_label: str = "",
) -> tuple[Path, int, list[str]]:
    """
    Write one XLSX file for Shop Uploader.

    Returns (output_path, rows_written, warnings).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shop = _safe_label(cfg.run_label or cfg.template_path.stem)
    state = "DRAFT" if cfg.listing_state == "draft" else "LIVE"
    batch_part = f"_{batch_label}" if batch_label else ""
    filename = f"UPLOAD_TO_SHOPUPLOADER__{shop}__{state}__{timestamp}{batch_part}.xlsx"
    output_path = cfg.output_dir / filename

    cols = load_output_columns(cfg)
    # Inject columns that may not exist in older templates
    for extra_col, before_col in [
        (_VIDEO_COL, "action"),
        ("linked_image_url", "action"),
        ("linked_image_position", "action"),
        ("linked_image_for_option", "action"),
        ("production_partner_1", "action"),
        ("shop_section_id", "action"),
        ("featured_rank", "action"),
        # Explicitly set FALSE so "Processing profiles vary" stays OFF
        ("option1_changes_readiness_state", "option1_name"),
        ("option2_changes_readiness_state", "option2_name"),
        # Per Shop Uploader variations_advanced docs:
        # option1 = Phone Model → FALSE for all (price/qty/sku do NOT change per phone model)
        # option2 = Styles      → TRUE  for all (price/qty/sku DO change per style)
        ("option1_changes_price",    "option1_name"),
        ("option1_changes_quantity", "option1_name"),
        ("option1_changes_sku",      "option1_name"),
        ("option2_changes_price",    "option2_name"),
        ("option2_changes_quantity", "option2_name"),
        ("option2_changes_sku",      "option2_name"),
    ]:
        if extra_col not in cols:
            insert_at = cols.index(before_col) if before_col in cols else len(cols)
            cols.insert(insert_at, extra_col)
            log.info("Injected '%s' column before '%s'", extra_col, before_col)
    columns = cols

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Template"

    _write_header(ws, columns)

    rows_written = 0
    warnings: list[str] = []

    for pkg in packages:
        if not pkg.is_ready:
            warnings.append(
                f"[{pkg.meta.parent_sku}] Package not ready "
                f"(images={bool(pkg.image_urls)}, copy={pkg.generated_copy is not None}) — skipped"
            )
            continue

        product_rows = _build_rows(pkg, cfg, columns)
        for row in product_rows:
            ws.append(row)
        rows_written += len(product_rows)

    _auto_fit_columns(ws, columns)
    wb.save(str(output_path))
    log.info("XLSX written: %s (%d rows)", output_path.name, rows_written)

    return output_path, rows_written, warnings


def build_batched_xlsx_files(
    packages: list[ProductPackage],
    cfg: Config,
) -> tuple[list[Path], list[str]]:
    """
    Split packages into cfg.batch_size chunks and write one file per batch.
    Returns (list_of_paths, all_warnings).
    """
    all_paths: list[Path] = []
    all_warnings: list[str] = []

    ready = [p for p in packages if p.is_ready]
    total_batches = max(1, -(-len(ready) // cfg.batch_size))

    for batch_num in range(total_batches):
        start = batch_num * cfg.batch_size
        end = start + cfg.batch_size
        batch = ready[start:end]
        if not batch:
            continue
        label = f"batch{batch_num + 1:03d}_of_{total_batches:03d}"
        path, rows_written, warnings = build_xlsx(batch, cfg, batch_label=label)
        all_paths.append(path)
        all_warnings.extend(warnings)
        log.info("Batch %d/%d: %d rows → %s", batch_num + 1, total_batches, rows_written, path.name)

    return all_paths, all_warnings


def _write_header(ws, columns: list[str]) -> None:
    ws.append(columns)
    for col_idx, _ in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center")


def _build_rows(pkg: ProductPackage, cfg: Config, columns: list[str]) -> list[list]:
    """
    Return a list of spreadsheet rows for one product.
    - No variations → 1 row.
    - With variations (Style × Phone Model) → len(styles) × len(models) rows.
      All rows share the same parent_sku; the first row carries the full listing data.
    """
    meta = pkg.meta
    copy = pkg.generated_copy
    tags = (copy.tags + [""] * 13)[:13]
    urls = (pkg.image_urls + [""] * 10)[:10]

    # ── Base listing fields (shared by every row in this product) ─────────────
    listing_fields: dict[str, object] = {
        "listing_id": "",
        "parent_sku": meta.parent_sku,
        "title": copy.title,
        "description": copy.description,
        "category": meta.category,
        "video_1": pkg.video_url,  # empty string if no video
        # Colors: AI-detected from images takes priority over meta.json defaults
        "_primary_color": copy.primary_color or meta.category_properties.primary_color,
        "_secondary_color": copy.secondary_color or meta.category_properties.secondary_color,
        "_occasion": meta.category_properties.occasion,
        "_holiday": meta.category_properties.holiday,
        # Phone Cases category attributes (present after regenerating template for Phone Cases)
        "_material": meta.category_properties.material,
        "_glitter": meta.category_properties.glitter,
        "_built_in_stand": meta.category_properties.built_in_stand,
        "_deprecated_diameter": "", "_deprecated_dimensions": "",
        "_deprecated_fabric": "", "_deprecated_finish": "",
        "_deprecated_flavor": "", "_deprecated_height": "",
        "_deprecated_length": "", "_deprecated_material": "",
        "_deprecated_pattern": "", "_deprecated_scent": "",
        "_deprecated_size": "", "_deprecated_style": "",
        "_deprecated_weight": "", "_deprecated_width": "",
        "_deprecated_device": "",
        "image_1": urls[0], "image_2": urls[1], "image_3": urls[2],
        "image_4": urls[3], "image_5": urls[4], "image_6": urls[5],
        "image_7": urls[6], "image_8": urls[7], "image_9": urls[8],
        "image_10": urls[9],
        "shipping_profile_id": meta.shipping_profile_id,
        "readiness_state_id": meta.readiness_state_id,
        "return_policy_id": meta.return_policy_id,
        "length": meta.length, "width": meta.width, "height": meta.height,
        "dimensions_unit": meta.dimensions_unit,
        "weight": meta.weight, "weight_unit": meta.weight_unit,
        "type": meta.type,
        "who_made": meta.who_made,
        "is_made_to_order": _bool(meta.is_made_to_order),
        "year_made": meta.year_made,
        "is_vintage": _bool(meta.is_vintage),
        "is_supply": _bool(meta.is_supply),
        "is_taxable": _bool(meta.is_taxable),
        "auto_renew": _bool(meta.auto_renew),
        "is_customizable": _bool(meta.is_customizable),
        "is_personalizable": _bool(meta.is_personalizable),
        "personalization_is_required": _bool(meta.personalization_is_required),
        "personalization_instructions": meta.personalization_instructions,
        "personalization_char_count_max": meta.personalization_char_count_max,
        "style_1": meta.style_1, "style_2": meta.style_2,
        "tag_1": tags[0], "tag_2": tags[1], "tag_3": tags[2],
        "tag_4": tags[3], "tag_5": tags[4], "tag_6": tags[5],
        "tag_7": tags[6], "tag_8": tags[7], "tag_9": tags[8],
        "tag_10": tags[9], "tag_11": tags[10], "tag_12": tags[11],
        "tag_13": tags[12],
        "action": "create",
        "listing_state": cfg.listing_state,
        "overwrite_images": "TRUE",
        # linked image columns — populated per variation row below
        "linked_image_url": "",
        "linked_image_position": "",
        "linked_image_for_option": "",
        # Production partner — same for every listing in this shop
        "production_partner_1": meta.production_partner_1,
        # Shop section — "iPhone Cases" section
        "shop_section_id": meta.shop_section_id,
        # Featured rank — any positive integer enables "Feature this listing"
        "featured_rank": meta.featured_rank,
        # Explicitly FALSE so "Processing profiles vary" stays OFF in Etsy
        "option1_changes_readiness_state": "FALSE",
        "option2_changes_readiness_state": "FALSE",
        # Variations advanced — Phone Model (option1) drives NOTHING
        "option1_changes_price":    "FALSE",
        "option1_changes_quantity": "FALSE",
        "option1_changes_sku":      "FALSE",
        # Styles (option2) drives EVERYTHING
        "option2_changes_price":    "TRUE",
        "option2_changes_quantity": "TRUE",
        "option2_changes_sku":      "TRUE",
    }

    v = meta.variations
    if v is None:
        # ── No variations: single row, use top-level price/qty/sku ───────────
        row = dict(listing_fields)
        row["sku"] = meta.sku
        row["price"] = meta.price
        row["quantity"] = meta.quantity
        row["option1_name"] = ""
        row["option1_value"] = ""
        row["option2_name"] = ""
        row["option2_value"] = ""
        return [[row.get(col, "") for col in columns]]

    # ── 2D variations: one row per (model × style) combination ──────────────
    # option1 = Phone Model (12), option2 = Styles (6) → 72 rows per product
    # Prices/Quantities driven by Styles (per Etsy "vary for each" setting)
    # Linked images attached to Styles (per Etsy "Link photos to this variation")
    rows: list[list] = []
    first_row = True

    # Map style index → image URL for variation-linked images
    # We assign the product images sequentially to each style that has one.
    image_urls_for_style: dict[str, str] = {}
    for idx, style in enumerate(v.styles):
        url_idx = idx  # image_1=CGM, image_2=CG, image_3=CC, image_4=CO, etc.
        if url_idx < len(pkg.image_urls):
            image_urls_for_style[style.value] = pkg.image_urls[url_idx]

    for model in v.models:
        for style in v.styles:
            safe_model = model.replace(" ", "").replace("Pro", "P").replace("Max", "M").replace("/", "")
            sku = f"{meta.parent_sku}-{style.sku_code}-{safe_model}"[:32]

            row = dict(listing_fields)
            # SKU: blank to match live listing (Etsy auto-assigns variation IDs).
            # This is what makes "SKUs vary for Styles only" — when SKU is blank,
            # Etsy ties SKU dimension to the same dimension as price (Styles).
            row["sku"] = ""
            row["price"] = style.price
            row["quantity"] = style.quantity

            # option1 = Phone Model, option2 = Styles (matches live Y2KASEshop)
            row["option1_name"] = v.option1_name   # "Phone Model"
            row["option1_value"] = model
            row["option2_name"] = v.option2_name   # "Styles"
            row["option2_value"] = style.value

            # Link variation image to this style option
            linked_url = image_urls_for_style.get(style.value, "")
            row["linked_image_url"] = linked_url
            row["linked_image_position"] = 1 if linked_url else ""
            row["linked_image_for_option"] = v.option2_name if linked_url else ""  # "Styles"

            # Only first row carries full listing-level data
            if not first_row:
                for blank_col in (
                    "title", "description", "video_1",
                    "image_1", "image_2", "image_3", "image_4", "image_5",
                    "image_6", "image_7", "image_8", "image_9", "image_10",
                    "tag_1", "tag_2", "tag_3", "tag_4", "tag_5", "tag_6",
                    "tag_7", "tag_8", "tag_9", "tag_10", "tag_11", "tag_12", "tag_13",
                ):
                    row[blank_col] = ""
            first_row = False

            rows.append([row.get(col, "") for col in columns])

    return rows


def _build_row(pkg: ProductPackage, cfg: Config, columns: list[str]) -> list:
    """Kept for backward-compat; delegates to _build_rows."""
    return _build_rows(pkg, cfg, columns)[0]


def _bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _bool_to_excel(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _auto_fit_columns(ws, columns: list[str]) -> None:
    for col_idx in range(1, len(columns) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = 0
        for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
            for cell in row:
                try:
                    cell_len = len(str(cell.value or ""))
                    if cell_len > max_len:
                        max_len = cell_len
                except Exception:
                    pass
        adjusted_width = min(max(max_len + 2, 12), 60)
        ws.column_dimensions[col_letter].width = adjusted_width
