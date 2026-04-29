"""Upload local product images to Cloudinary and return stable direct URLs."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import cloudinary
import cloudinary.uploader

from src.config import Config
from src.models import ProductPackage

log = logging.getLogger(__name__)


def configure_cloudinary(cfg: Config) -> None:
    cloudinary.config(
        cloud_name=cfg.cloudinary_cloud_name,
        api_key=cfg.cloudinary_api_key,
        api_secret=cfg.cloudinary_api_secret,
        secure=True,
    )


def upload_product_images(
    package: ProductPackage,
    cfg: Config,
    force_reupload: bool = False,
) -> list[str]:
    """
    Upload all images for a package to Cloudinary.
    Uses a deterministic public_id so repeated uploads are idempotent
    (Cloudinary will not re-upload if the public_id already exists, unless overwrite=True).

    Returns a list of direct image URLs (up to 10).
    """
    urls: list[str] = []
    sku = package.meta.parent_sku

    for idx, img_path in enumerate(package.image_paths[:10], start=1):
        public_id = _public_id(cfg.cloudinary_folder, sku, idx, img_path)

        try:
            result = cloudinary.uploader.upload(
                str(img_path),
                public_id=public_id,
                overwrite=force_reupload,
                resource_type="image",
                unique_filename=False,
                use_filename=False,
            )
            url = result.get("secure_url", "")
            if url:
                urls.append(url)
                log.info("Uploaded %s → %s", img_path.name, url)
            else:
                log.warning("Upload of %s returned no URL", img_path.name)
        except Exception as exc:
            log.error("Failed to upload %s: %s", img_path.name, exc)

    return urls


def upload_all_packages(
    packages: list[ProductPackage],
    cfg: Config,
    force_reupload: bool = False,
) -> list[str]:
    """Upload images AND video for every package. Returns upload-level error messages."""
    configure_cloudinary(cfg)
    errors: list[str] = []

    for pkg in packages:
        # ── Images ────────────────────────────────────────────────────────────
        urls = upload_product_images(pkg, cfg, force_reupload=force_reupload)
        if not urls:
            errors.append(f"[{pkg.meta.parent_sku}] No images uploaded — check Cloudinary config")
            continue
        pkg.image_urls = urls
        log.info("[%s] %d image URL(s) ready", pkg.meta.parent_sku, len(urls))

        # ── Video (optional) ──────────────────────────────────────────────────
        if pkg.video_path:
            video_url = upload_product_video(pkg, cfg, force_reupload=force_reupload)
            if video_url:
                pkg.video_url = video_url
            else:
                errors.append(f"[{pkg.meta.parent_sku}] Video upload failed — listing will have no video")

    return errors


def upload_product_video(
    package: ProductPackage,
    cfg: Config,
    force_reupload: bool = False,
) -> str:
    """Upload the product video to Cloudinary and return a direct URL."""
    if not package.video_path:
        return ""
    sku = package.meta.parent_sku
    name_hash = hashlib.sha1(package.video_path.name.encode()).hexdigest()[:8]
    safe_sku = sku.replace(" ", "_")
    public_id = f"{cfg.cloudinary_folder}/{safe_sku}/video_{name_hash}"

    try:
        result = cloudinary.uploader.upload(
            str(package.video_path),
            public_id=public_id,
            overwrite=force_reupload,
            resource_type="video",
            unique_filename=False,
            use_filename=False,
        )
        url = result.get("secure_url", "")
        if url:
            log.info("Uploaded video %s → %s", package.video_path.name, url[:80])
            return url
        log.warning("Video upload of %s returned no URL", package.video_path.name)
    except Exception as exc:
        log.error("Failed to upload video %s: %s", package.video_path.name, exc)
    return ""


def _public_id(folder: str, sku: str, position: int, path: Path) -> str:
    """
    Deterministic Cloudinary public_id based on FILE CONTENT hash.

    We hash the actual image bytes (not the filename) so that renaming a file
    — e.g. IMG_1288.PNG → 01_IMG_1288.PNG — never creates a duplicate Cloudinary
    asset. Same pixels = same hash = same public_id = no re-upload.

    Format: <folder>/<sku>/<position>_<sha1-prefix-of-content>
    """
    content_hash = hashlib.sha1(path.read_bytes()).hexdigest()[:8]
    safe_sku = sku.replace(" ", "_")
    return f"{folder}/{safe_sku}/{position:02d}_{content_hash}"
