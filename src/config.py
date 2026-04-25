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


@dataclass
class Config:
    # ── OpenAI ───────────────────────────────────────────────────────────────
    openai_api_key: str = field(default_factory=lambda: _require("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4.1"))

    # ── Cloudinary (image hosting) ────────────────────────────────────────────
    cloudinary_cloud_name: str = field(default_factory=lambda: _require("CLOUDINARY_CLOUD_NAME"))
    cloudinary_api_key: str = field(default_factory=lambda: _require("CLOUDINARY_API_KEY"))
    cloudinary_api_secret: str = field(default_factory=lambda: _require("CLOUDINARY_API_SECRET"))
    cloudinary_folder: str = field(default_factory=lambda: os.getenv("CLOUDINARY_FOLDER", "etsy_products"))

    # ── Pipeline defaults ────────────────────────────────────────────────────
    products_dir: Path = field(default_factory=lambda: ROOT_DIR / "products")
    output_dir: Path = field(default_factory=lambda: ROOT_DIR / "output")
    # Shop Uploader workbook whose row 1 defines column order (per shop / category set).
    # Override with SHOP_UPLOADER_TEMPLATE=my_template.xlsx (relative to repo root or absolute).
    template_path: Path = field(default_factory=_default_shop_uploader_template)

    # listing_state: "draft" for safe runs, "published" for live
    listing_state: str = field(default_factory=lambda: os.getenv("LISTING_STATE", "draft"))
    batch_size: int = field(default_factory=lambda: int(os.getenv("BATCH_SIZE", "200")))
    # Human-readable shop/batch label used in output filenames (e.g. "Y2KASEshop")
    run_label: str = field(default_factory=lambda: os.getenv("RUN_LABEL", ""))

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)


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
