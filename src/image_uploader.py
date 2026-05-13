"""Upload local product images to Cloudinary and return stable direct URLs."""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import cloudinary
import cloudinary.uploader

from src.config import Config
from src.models import ProductPackage

log = logging.getLogger(__name__)

_MAX_RETRIES = 4          # total attempts per file (1 initial + 3 retries)
_RETRY_BASE_DELAY = 3.0   # seconds; doubles on each retry (3 → 6 → 12)


def configure_cloudinary(cfg: Config) -> None:
    _patch_ssl_for_python312()
    cloudinary.config(
        cloud_name=cfg.cloudinary_cloud_name,
        api_key=cfg.cloudinary_api_key,
        api_secret=cfg.cloudinary_api_secret,
        secure=True,
    )


def _patch_ssl_for_python312() -> None:
    """
    Python 3.12 tightened TLS: it now raises SSLEOFError for connections where
    the server does not send a proper TLS close_notify before closing the socket.
    Cloudinary's CDN edge nodes sometimes skip close_notify, causing
    'UNEXPECTED_EOF_WHILE_READING' on every upload attempt.

    Setting OP_IGNORE_UNEXPECTED_EOF restores the pre-3.12 tolerant behaviour.
    Certificate verification and hostname checking remain fully enabled — this
    only changes how the TLS teardown is handled.
    """
    import ssl
    try:
        import urllib3.util.ssl_ as _urllib3_ssl
        _orig = _urllib3_ssl.create_urllib3_context

        def _patched(*args, **kwargs):
            ctx = _orig(*args, **kwargs)
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
            return ctx

        _urllib3_ssl.create_urllib3_context = _patched
        log.debug("Applied OP_IGNORE_UNEXPECTED_EOF SSL patch (Python 3.12 / Cloudinary compatibility)")
    except Exception as exc:
        log.warning("SSL patch could not be applied: %s — uploads may hit SSL EOF errors", exc)


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
        url = _upload_with_retry(img_path, public_id, force_reupload, resource_type="image")
        if url:
            urls.append(url)
        else:
            log.warning("[%s] image_%d (%s) failed after %d attempts — slot left blank",
                        sku, idx, img_path.name, _MAX_RETRIES)

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

    url = _upload_with_retry(package.video_path, public_id, force_reupload, resource_type="video")
    if url:
        log.info("Uploaded video %s → %s", package.video_path.name, url[:80])
        return url
    log.error("Video upload of %s failed after %d attempts", package.video_path.name, _MAX_RETRIES)
    return ""


def _upload_with_retry(
    path: Path,
    public_id: str,
    force_reupload: bool,
    resource_type: str,
) -> str:
    """
    Upload a single file to Cloudinary with exponential-backoff retries.
    Returns the secure_url on success, empty string after all attempts fail.
    Transient network errors (ProtocolError, RemoteDisconnected, timeout) are
    retried; genuine API errors (invalid credentials, quota exceeded) are not.
    """
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = cloudinary.uploader.upload(
                str(path),
                public_id=public_id,
                overwrite=force_reupload,
                resource_type=resource_type,
                unique_filename=False,
                use_filename=False,
            )
            url = result.get("secure_url", "")
            if url:
                if attempt > 1:
                    log.info("Uploaded %s (attempt %d) → %s", path.name, attempt, url)
                else:
                    log.info("Uploaded %s → %s", path.name, url)
                return url
            log.warning("Upload of %s returned no URL (attempt %d)", path.name, attempt)
            return ""
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # The Cloudinary SDK wraps ALL network errors (ProtocolError,
            # RemoteDisconnected, SSLError, timeout) as:
            #   cloudinary.exceptions.Error("Unexpected error - <original>")
            # Only true API errors (bad credentials, quota exceeded, invalid
            # params) have different message prefixes — never retry those.
            msg = str(exc)
            is_hard_api_error = (
                isinstance(exc, cloudinary.exceptions.Error)
                and not msg.startswith("Unexpected error")
            )
            if is_hard_api_error:
                log.error(
                    "Cloudinary API error for %s: %s — not retrying",
                    path.name, msg,
                )
                return ""
            # Transient network / connection error — retry with backoff
            if attempt < _MAX_RETRIES:
                log.warning(
                    "Upload of %s failed (attempt %d/%d): %s — retrying in %.0fs",
                    path.name, attempt, _MAX_RETRIES, msg, delay,
                )
                time.sleep(delay)
                delay *= 2
            else:
                log.error(
                    "Upload of %s failed after %d attempts: %s — giving up",
                    path.name, _MAX_RETRIES, msg,
                )
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
