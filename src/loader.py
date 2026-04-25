"""Load product packages from the products/ directory."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.models import (
    CategoryProperties,
    ProductMeta,
    ProductPackage,
    VariationMatrix,
    discover_images,
    discover_video,
)

log = logging.getLogger(__name__)


def load_all_packages(products_dir: Path) -> tuple[list[ProductPackage], list[str]]:
    """
    Walk products_dir. Each immediate subdirectory is a product folder.
    Returns (valid_packages, error_strings).
    """
    packages: list[ProductPackage] = []
    errors: list[str] = []

    if not products_dir.exists():
        errors.append(f"Products directory does not exist: {products_dir}")
        return packages, errors

    candidates = sorted([d for d in products_dir.iterdir() if d.is_dir()])
    if not candidates:
        errors.append(f"No product folders found in: {products_dir}")
        return packages, errors

    for folder in candidates:
        meta_path = folder / "meta.json"
        if not meta_path.exists():
            errors.append(f"[{folder.name}] Missing meta.json — skipping")
            continue

        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"[{folder.name}] meta.json parse error: {exc} — skipping")
            continue

        try:
            meta = _parse_meta(raw, folder.name)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"[{folder.name}] meta.json schema error: {exc} — skipping")
            continue

        validation_errors = meta.validate()
        if validation_errors:
            for ve in validation_errors:
                errors.append(f"[{folder.name}] Validation: {ve}")
            errors.append(f"[{folder.name}] Skipping due to validation errors above")
            continue

        images = discover_images(folder)
        if not images:
            errors.append(f"[{folder.name}] No images found — skipping")
            continue

        packages.append(ProductPackage(
            folder=folder,
            meta=meta,
            image_paths=images,
            video_path=discover_video(folder),
        ))
        log.info("Loaded %s (%d image(s)%s)", folder.name, len(images),
                 ", 1 video" if discover_video(folder) else "")

    return packages, errors


def _parse_meta(raw: dict[str, Any], folder_name: str) -> ProductMeta:
    cat_props_raw = raw.get("category_properties", {})
    if isinstance(cat_props_raw, str):
        cat_props_raw = {}

    return ProductMeta(
        parent_sku=raw.get("parent_sku", folder_name).upper(),
        sku=raw.get("sku", folder_name).upper(),
        price=float(raw["price"]),
        quantity=int(raw["quantity"]),
        type=raw.get("type", "physical").lower(),
        category=raw.get("category", ""),
        who_made=raw.get("who_made", "i_did"),
        is_made_to_order=bool(raw.get("is_made_to_order", False)),
        year_made=str(raw.get("year_made", "2020_2024")),
        is_vintage=bool(raw.get("is_vintage", False)),
        is_supply=bool(raw.get("is_supply", False)),
        is_taxable=bool(raw.get("is_taxable", True)),
        auto_renew=bool(raw.get("auto_renew", True)),
        is_customizable=bool(raw.get("is_customizable", False)),
        is_personalizable=bool(raw.get("is_personalizable", False)),
        personalization_is_required=bool(raw.get("personalization_is_required", False)),
        personalization_instructions=raw.get("personalization_instructions", ""),
        personalization_char_count_max=int(raw.get("personalization_char_count_max", 256)),
        style_1=raw.get("style_1", ""),
        style_2=raw.get("style_2", ""),
        shipping_profile_id=str(raw.get("shipping_profile_id", "")),
        return_policy_id=str(raw.get("return_policy_id", "")),
        readiness_state_id=str(raw.get("readiness_state_id", "")),
        dimensions_unit=raw.get("dimensions_unit", "in"),
        length=str(raw.get("length", "")),
        width=str(raw.get("width", "")),
        height=str(raw.get("height", "")),
        weight=str(raw.get("weight", "")),
        weight_unit=raw.get("weight_unit", "oz"),
        category_properties=CategoryProperties.from_dict(cat_props_raw),
        keyword_seeds=list(raw.get("keyword_seeds", [])),
        banned_phrases=list(raw.get("banned_phrases", [])),
        materials=list(raw.get("materials", [])),
        target_buyer=raw.get("target_buyer", ""),
        extra_notes=raw.get("extra_notes", ""),
        production_partner_1=str(raw.get("production_partner_1", "")),
        shop_section_id=str(raw.get("shop_section_id", "")),
        featured_rank=str(raw.get("featured_rank", "")),
        variations=_parse_variations(raw),
    )


def _parse_variations(raw: dict[str, Any]) -> VariationMatrix | None:
    v = raw.get("variations")
    if not v:
        return None
    try:
        return VariationMatrix.from_dict(v)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("Could not parse variations: %s — treating as no-variations listing", exc)
        return None
