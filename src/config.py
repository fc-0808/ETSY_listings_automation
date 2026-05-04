"""Central configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def _default_shop_uploader_template() -> Path:
    override = os.getenv("SHOP_UPLOADER_TEMPLATE", "").strip()
    if override:
        p = Path(override)
        return p if p.is_absolute() else (ROOT_DIR / p)
    y2k = ROOT_DIR / "Y2KASEshop.xlsx"
    if y2k.exists():
        return y2k
    legacy = ROOT_DIR / "temp_3CkpVDwPIrAq7keFNpsulxHru12.xlsx"
    return legacy


def _default_products_dir() -> Path:
    override = os.getenv("PRODUCTS_DIR", "").strip()
    if override:
        p = Path(override)
        return p if p.is_absolute() else (ROOT_DIR / p)
    return ROOT_DIR / "input"


@dataclass
class Config:
    # ── OpenAI ───────────────────────────────────────────────────────────────
    openai_api_key: str = field(default_factory=lambda: _require("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))

    # ── Cloudinary (image hosting) ────────────────────────────────────────────
    cloudinary_cloud_name: str = field(default_factory=lambda: _require("CLOUDINARY_CLOUD_NAME"))
    cloudinary_api_key: str = field(default_factory=lambda: _require("CLOUDINARY_API_KEY"))
    cloudinary_api_secret: str = field(default_factory=lambda: _require("CLOUDINARY_API_SECRET"))
    cloudinary_folder: str = field(default_factory=lambda: os.getenv("CLOUDINARY_FOLDER", "etsy_products"))

    # ── Pipeline defaults ────────────────────────────────────────────────────
    # Override with PRODUCTS_DIR=input/IPlistings_0503 (relative to repo root or absolute).
    products_dir: Path = field(default_factory=_default_products_dir)
    output_dir: Path = field(default_factory=lambda: ROOT_DIR / "output")
    # Shop Uploader workbook whose row 1 defines column order (per shop / category set).
    # Override with SHOP_UPLOADER_TEMPLATE=my_template.xlsx (relative to repo root or absolute).
    template_path: Path = field(default_factory=_default_shop_uploader_template)

    # listing_state: "draft" for safe runs, "published" for live
    listing_state: str = field(default_factory=lambda: os.getenv("LISTING_STATE", "draft"))
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "200")))
    # Human-readable shop/batch label used in output filenames (e.g. "Y2KASEshop")
    run_label: str = field(default_factory=lambda: os.getenv("RUN_LABEL", ""))
    # Shop display name used in the listing description Promise section and run label.
    # Set SHOP_NAME=Y2KASEowo in your .env (or override per-run).
    shop_name: str = field(default_factory=lambda: os.getenv("SHOP_NAME", "Y2KASEshop"))
    # Comma-separated brand identity tags forced into every listing's tag list.
    # Default is derived from shop_name; override with BRAND_TAGS=tag1,tag2 in .env.
    brand_tags: list = field(default_factory=lambda: _default_brand_tags())

    # ── Shop-level Etsy / Shop Uploader IDs ──────────────────────────────────
    # Set these once per shop in .env — they are used as fallbacks when a
    # product's meta.json leaves the field blank, so you never need to repeat
    # the same ID in every single meta.json file.
    #
    # How to find these values:
    #   • Log into Shop Uploader → Shop page → copy the ID shown next to each item
    #   • Or export any existing listing from that shop and read the column value
    #
    production_partner_id: str = field(default_factory=lambda: os.getenv("PRODUCTION_PARTNER_ID", ""))
    shipping_profile_id:   str = field(default_factory=lambda: os.getenv("SHIPPING_PROFILE_ID", ""))
    return_policy_id:      str = field(default_factory=lambda: os.getenv("RETURN_POLICY_ID", ""))
    readiness_state_id:    str = field(default_factory=lambda: os.getenv("READINESS_STATE_ID", ""))
    shop_section_id:       str = field(default_factory=lambda: os.getenv("SHOP_SECTION_ID", ""))

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.products_dir.mkdir(parents=True, exist_ok=True)


def _default_brand_tags() -> list:
    raw = os.getenv("BRAND_TAGS", "").strip()
    if raw:
        return [t.strip().lower()[:20] for t in raw.split(",") if t.strip()]
    # Derive two compact brand tags from SHOP_NAME
    name = os.getenv("SHOP_NAME", "Y2KASEshop").lower().replace(" ", "")
    short = name[:20]
    # If name is long, also include a prefix slice as second tag
    prefix = name[:7] if len(name) > 7 else name
    tags = list(dict.fromkeys([short, prefix]))  # deduplicated, order-preserved
    return [t for t in tags if t][:2]


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in your credentials."
        )
    return value


def load_config(skip_api_keys: bool = False) -> Config:
    _load_dotenv()
    if skip_api_keys:
        # Inject safe placeholders so dataclass instantiation doesn't raise.
        # Real keys are never needed for --dry-run (load + validate only).
        for key in (
            "OPENAI_API_KEY",
            "CLOUDINARY_CLOUD_NAME",
            "CLOUDINARY_API_KEY",
            "CLOUDINARY_API_SECRET",
        ):
            if not os.getenv(key):
                os.environ[key] = "__dry_run_placeholder__"
    return Config()


def _load_dotenv() -> None:
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    with env_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
