"""Domain models for a single product package."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".m4v"}

_SKU_RE = re.compile(r"^[A-Z0-9_\-]{1,32}$")


@dataclass
class CategoryProperties:
    """
    Category-specific attribute columns (_underscore_columns) for Phone Cases.
    These map to the _underscore_columns in the Shop Uploader template.

    Phone Cases category (taxonomy 2848) supports:
      _primary_color   — e.g. "Clear", "Pink", "Purple" (Etsy allowed values)
      _secondary_color — e.g. "Pink", "White"
      _occasion        — e.g. "Birthday"  (optional)
      _holiday         — e.g. "Christmas" (optional)
      _material        — free-text material tag (e.g. "Silicone")
                         NOTE: this is a material *tag* on the listing, not a
                         variation. The buyer-visible Materials field uses this.
      _glitter         — "Yes" / "No"
      _built_in_stand  — "Yes" / "No"
    """
    primary_color: str = ""
    secondary_color: str = ""
    occasion: str = ""
    holiday: str = ""
    material: str = ""       # populates _material if column exists in template
    glitter: str = ""        # "Yes" or "No" — populates _glitter
    built_in_stand: str = "" # "Yes" or "No" — populates _built_in_stand

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CategoryProperties":
        return cls(
            primary_color=d.get("_primary_color", ""),
            secondary_color=d.get("_secondary_color", ""),
            occasion=d.get("_occasion", ""),
            holiday=d.get("_holiday", ""),
            material=d.get("_material", ""),
            glitter=d.get("_glitter", ""),
            built_in_stand=d.get("_built_in_stand", ""),
        )


@dataclass
class StyleOption:
    """One value in option2 (Styles): e.g. 'Case+Grip+Charm' with its price and qty."""
    value: str
    price: float
    quantity: int
    sku_code: str = ""  # short code used in variation SKU, e.g. "CGM"


@dataclass
class VariationMatrix:
    """
    2D variation structure matching the Y2KASEshop listing:
      option1 = Phone Model  (12 options: iPhone 17 Pro Max … iPhone 14/13)
      option2 = Styles       (6 options: Case+Grip+Charm, Case+Grip, …)

    Etsy / Manage Variations shows:
      - Prices vary for each → Styles
      - Quantities vary for each → Styles
      - Photos linked to → Styles

    Each (model × style) combination becomes one row in the Shop Uploader sheet.
    Total rows per product = len(models) × len(styles) = 12 × 6 = 72
    """
    option1_name: str          # "Phone Model"
    models: list[str]          # option1 values (12 iPhone models)

    option2_name: str          # "Styles"
    styles: list[StyleOption]  # option2 values (6 style options, with prices/qty)

    @classmethod
    def default_y2kase(cls) -> "VariationMatrix":
        """Standard Y2KASEshop variation matrix — prices in HKD per live listing."""
        return cls(
            option1_name="Phone Model",
            models=[
                "iPhone 17 Pro Max",
                "iPhone 17 Pro",
                "iPhone 17",
                "iPhone 16 Pro Max",
                "iPhone 16 Pro",
                "iPhone 16",
                "iPhone 15 Pro Max",
                "iPhone 15 Pro",
                "iPhone 15",
                "iPhone 14 Pro Max",
                "iPhone 14 Pro",
                "iPhone 14/13",
            ],
            option2_name="Styles",
            styles=[
                StyleOption("Case+Grip+Charm", price=409.89, quantity=3, sku_code="CGM"),
                StyleOption("Case+Grip",        price=350.11, quantity=3, sku_code="CG"),
                StyleOption("Case+Charm",        price=350.11, quantity=3, sku_code="CC"),
                StyleOption("Case Only",         price=261.86, quantity=3, sku_code="CO"),
                StyleOption("Grip Only",         price=170.76, quantity=3, sku_code="GO"),
                StyleOption("Charm Only",        price=113.82, quantity=3, sku_code="CH"),
            ],
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VariationMatrix":
        styles = []
        for s in d.get("styles", []):
            styles.append(StyleOption(
                value=str(s["value"]),
                price=float(s["price"]),
                quantity=int(s.get("quantity", 3)),
                sku_code=str(s.get("sku_code", s["value"][:3].upper())),
            ))
        return cls(
            option1_name=str(d.get("option1_name", "Phone Model")),
            models=list(d.get("models", [])),
            option2_name=str(d.get("option2_name", "Styles")),
            styles=styles,
        )

    def row_count(self) -> int:
        return len(self.styles) * len(self.models)


@dataclass
class ProductMeta:
    parent_sku: str
    sku: str
    price: float
    quantity: int
    type: str
    category: str
    who_made: str
    is_made_to_order: bool
    year_made: str
    is_vintage: bool
    is_supply: bool
    is_taxable: bool
    auto_renew: bool
    is_customizable: bool
    is_personalizable: bool
    personalization_is_required: bool
    personalization_instructions: str
    personalization_char_count_max: int
    style_1: str
    style_2: str
    shipping_profile_id: str
    return_policy_id: str
    readiness_state_id: str
    dimensions_unit: str
    length: str
    width: str
    height: str
    weight: str
    weight_unit: str
    category_properties: CategoryProperties
    keyword_seeds: list[str]
    banned_phrases: list[str]
    materials: list[str]
    target_buyer: str
    extra_notes: str
    # production_partner_1: Etsy numeric ID for the production partner
    # (ShenZhen Mumusan Technology Co., Ltd. = 5556766)
    production_partner_1: str = ""
    # shop_section_id: numeric ID of the Etsy shop section (iPhone Cases = 57228761)
    shop_section_id: str = ""
    # featured_rank: any positive integer = "Feature this listing" ON; blank = OFF
    featured_rank: str = ""
    # Optional 2D variation matrix; None = no variations (single-row listing)
    variations: VariationMatrix | None = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not _SKU_RE.match(self.parent_sku.upper()):
            errors.append(
                f"parent_sku '{self.parent_sku}' contains invalid characters or is too long. "
                f"Only A-Z 0-9 - _ (max 32) allowed."
            )
        if self.price <= 0 and self.variations is None:
            errors.append("price must be > 0 (or define variations with per-style prices)")
        if self.quantity < 0 and self.variations is None:
            errors.append("quantity must be >= 0 (or define variations)")
        if self.type not in ("physical", "digital"):
            errors.append("type must be 'physical' or 'digital'")
        if self.who_made not in ("i_did", "someone_else", "collective"):
            errors.append("who_made must be 'i_did', 'someone_else', or 'collective'")
        if self.type == "physical" and not self.shipping_profile_id:
            errors.append("shipping_profile_id is required for physical listings")
        if self.type == "physical" and not self.return_policy_id:
            errors.append("return_policy_id is required for physical listings")
        if self.type == "physical" and not self.readiness_state_id:
            errors.append("readiness_state_id is required for physical listings (processing time profile ID from Etsy)")
        return errors


@dataclass
class GeneratedCopy:
    title: str
    description: str
    tags: list[str]
    primary_color: str = ""    # Etsy-allowed value determined from images
    secondary_color: str = ""  # Etsy-allowed value determined from images
    # Maps each Style → LIST of 1-based image indices (best/most representative first).
    # e.g. {"Case+Grip": [2, 5], "Case Only": [3, 7], "Case+Grip+Charm": [1], "Charm Only": []}
    # Used ONLY for variation linked images.
    style_image_mapping: dict = None  # type: ignore[assignment]
    # Per-image structured facts returned by AI (decouples vision recognition from logic).
    # Each entry: {"index": int, "has_grip": bool, "has_charm": bool, "has_case": bool,
    #              "is_edge_or_profile": bool, "thumbnail_quality": int (1-10),
    #              "is_held_in_hand": bool, "shows_back_of_case": bool}
    image_analysis: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.style_image_mapping is None:
            self.style_image_mapping = {}
        if self.image_analysis is None:
            self.image_analysis = []

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.title or len(self.title) > 140:
            errors.append(f"title must be 1–140 chars (got {len(self.title)})")
        if not self.description:
            errors.append("description is empty")
        if len(self.description) > 102400:
            errors.append("description exceeds Etsy 102400 char limit")
        if len(self.tags) > 13:
            errors.append(f"too many tags: {len(self.tags)} (max 13)")
        for tag in self.tags:
            if len(tag) > 20:
                errors.append(f"tag '{tag[:30]}' exceeds 20-char limit")
        return errors


@dataclass
class ProductPackage:
    folder: Path
    meta: ProductMeta
    image_paths: list[Path] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    video_path: Path | None = None
    video_url: str = ""
    generated_copy: GeneratedCopy | None = None
    # Filename order is always trusted — the user renames images manually
    # to set the exact display order before running the pipeline.
    filename_order_trusted: bool = True

    @property
    def is_ready(self) -> bool:
        return bool(self.image_urls) and self.generated_copy is not None


_NATURAL_SORT_RE = re.compile(r'^(\d+)')


def _natural_sort_key(path: Path) -> tuple:
    """Sort images numerically by the leading number in the filename stem.

    Examples: 1.PNG→1, 10.PNG→10, 01_IMG_1284.PNG→1, IMG_foo.PNG→∞
    This ensures 1, 2, 3 … 9, 10 order instead of 1, 10, 2, 3 … 9.
    """
    m = _NATURAL_SORT_RE.match(path.stem)
    return (int(m.group(1)), path.name) if m else (float("inf"), path.name)


def discover_images(folder: Path) -> list[Path]:
    images: list[Path] = sorted(
        [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS],
        key=_natural_sort_key,
    )
    return images[:10]


def discover_video(folder: Path) -> Path | None:
    for p in sorted(folder.iterdir(), key=lambda x: x.name):
        if p.suffix.lower() in VIDEO_EXTENSIONS:
            return p
    return None
