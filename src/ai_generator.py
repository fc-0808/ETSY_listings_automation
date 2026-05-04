"""AI-powered title, description, and tag generation using OpenAI vision.

Role: Elite Etsy SEO expert with deep understanding of kawaii/Y2K phone case market.
Each product folder represents ONE phone case product (multiple images = different angles).
"""
from __future__ import annotations

import base64
import logging
import re
import time
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from src.config import Config
from src.models import GeneratedCopy, ProductMeta, ProductPackage

log = logging.getLogger(__name__)


# ── Pydantic schemas for Phase 1 Structured Outputs ──────────────────────────
# Using client.beta.chat.completions.parse guarantees every field is present
# with the correct type — no missing keys, no bad casts, no JSON parse errors.

class _ImageClass(BaseModel):
    index: int
    description: str
    accessory_reasoning: str  # explicit chain-of-thought before booleans — reduces hallucinations
    has_grip: bool
    has_charm: bool
    has_case: bool
    is_edge_or_profile: bool
    has_magsafe_ring: bool
    grip_shape: str
    thumbnail_quality: int

class _ProductSummary(BaseModel):
    character_name: str
    case_primary_color: str
    case_secondary_color: str
    design_features: str

class _Phase1Response(BaseModel):
    product_summary: _ProductSummary
    image_classifications: list[_ImageClass]

class _Phase2Response(BaseModel):
    title: str
    description: str
    tags: list[str]
    primary_color: str
    secondary_color: str


_MAX_RETRIES = 3
_RETRY_DELAY = 5.0


def generate_copy_for_all(
    packages: list[ProductPackage],
    cfg: Config,
    checkpoint_path: Path | None = None,
) -> list[str]:
    """Generate AI copy for every package. Returns error messages.

    If checkpoint_path is given, completed SKUs are saved there after each
    success and reloaded on restart — so the run continues from where it stopped.
    """
    import dataclasses, json as _json

    client = OpenAI(api_key=cfg.openai_api_key)
    errors: list[str] = []

    # ── Load existing checkpoint ──────────────────────────────────────────────
    done: dict[str, dict] = {}
    if checkpoint_path and checkpoint_path.exists():
        try:
            raw = _json.loads(checkpoint_path.read_text(encoding="utf-8"))
            # Normalise every entry to the unified format:
            #   {image_urls: [...], video_url: "...", copy_done: {title: ...}}
            # Previous runs may have written entries in different shapes:
            #   a) new:         {copy_done: {...}, image_urls: [...]}
            #   b) flat copy:   {title: ..., description: ...}          ← old AI-only run
            #   c) hybrid:      {title: ..., image_urls: [...]}         ← Phase-2 merged into old copy
            #   d) url-only:    {image_urls: [...], video_url: "..."}   ← Phase-2 with no copy yet
            _COPY_KEYS = {"title", "description", "tags"}
            for sku, val in raw.items():
                if not isinstance(val, dict):
                    continue
                if "copy_done" in val:
                    # Already in new format — keep as-is
                    done[sku] = val
                elif _COPY_KEYS.issubset(val.keys()):
                    # Has copy data at top level (shapes b & c) — wrap it
                    copy_data = {k: val[k] for k in val if k not in ("image_urls", "video_url")}
                    entry: dict = {"copy_done": copy_data}
                    if "image_urls" in val:
                        entry["image_urls"] = val["image_urls"]
                    if "video_url" in val:
                        entry["video_url"] = val["video_url"]
                    done[sku] = entry
                else:
                    # url-only (shape d) — no copy to restore
                    done[sku] = val
            copy_count = sum(1 for v in done.values() if v.get("copy_done"))
            log.info("Checkpoint loaded: %d/%d SKUs have AI copy — resuming",
                     copy_count, len(packages))
        except Exception as exc:
            log.warning("Could not read checkpoint %s: %s — starting fresh", checkpoint_path, exc)

    for pkg in packages:
        sku = pkg.meta.parent_sku

        # ── Resume: restore copy from checkpoint ─────────────────────────────
        if sku in done and done[sku].get("copy_done"):
            saved = done[sku]["copy_done"]
            pkg.generated_copy = GeneratedCopy(
                title=saved["title"],
                description=saved["description"],
                tags=saved["tags"],
                primary_color=saved.get("primary_color", ""),
                secondary_color=saved.get("secondary_color", ""),
                style_image_mapping=saved.get("style_image_mapping", {}),
                image_analysis=saved.get("image_analysis", []),
            )
            log.info("[%s] Restored from checkpoint: %s", sku, pkg.generated_copy.title[:60])
            continue

        # ── Generate fresh ────────────────────────────────────────────────────
        if not pkg.image_paths:
            errors.append(f"[{sku}] No images — skipping AI generation")
            continue
        try:
            pkg.generated_copy = _generate_with_retry(
                client, pkg.meta, pkg.image_paths, cfg,
            )
            copy_errors = pkg.generated_copy.validate()
            if copy_errors:
                for ce in copy_errors:
                    errors.append(f"[{sku}] Copy validation: {ce}")
            else:
                log.info("[%s] Copy generated OK: %s", sku, pkg.generated_copy.title[:60])

            # ── Save to checkpoint immediately after each success ─────────────
            if checkpoint_path:
                if sku not in done:
                    done[sku] = {}
                done[sku]["copy_done"] = dataclasses.asdict(pkg.generated_copy)
                try:
                    import os
                    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = checkpoint_path.with_suffix(".tmp")
                    tmp.write_text(
                        _json.dumps(done, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    os.replace(tmp, checkpoint_path)
                except Exception as exc:
                    log.warning("Could not save checkpoint: %s", exc)

        except Exception as exc:
            errors.append(f"[{sku}] AI generation failed: {exc}")

    return errors


def _generate_with_retry(
    client: OpenAI,
    meta: ProductMeta,
    image_paths: list[Path],
    cfg: Config,
) -> GeneratedCopy:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return _call_openai(client, meta, image_paths, cfg)
        except Exception as exc:
            last_exc = exc
            log.warning("Attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY * attempt)
    raise RuntimeError(f"All {_MAX_RETRIES} attempts failed") from last_exc


def _call_openai(
    client: OpenAI,
    meta: ProductMeta,
    image_paths: list[Path],
    cfg: Config,
) -> GeneratedCopy:
    """
    Two-phase pipeline for maximum reliability with any OpenAI model:

    Phase 1 — Visual Classification (dedicated, focused, deterministic)
        A single tight prompt that ONLY classifies each image. No copy writing.
        Returns structured per-image facts (has_grip, has_charm, MagSafe, etc.).
        Temperature = 0.0 for maximum consistency.

    Phase 2 — SEO Copy Generation (informed by Phase 1 facts)
        Phase 1 classification is injected as structured context.
        The model writes copy knowing exactly what is in the images.
        This produces far better titles/descriptions/tags than asking one
        model to classify AND write simultaneously.

    style_image_mapping is built algorithmically from Phase 1 — it is
    NEVER hallucinated by the AI.
    """
    images_to_send = image_paths[:10]
    image_blocks = _encode_images(images_to_send)

    # ── Phase 1: Visual Classification + Product Summary ─────────────────────
    log.info("Phase 1 — visual classification (%d images)", len(image_blocks))
    image_analysis, product_summary = _phase1_classify_images(
        client, cfg, len(image_blocks), image_blocks
    )

    # Build style_image_mapping algorithmically from Phase 1 facts
    style_map = _derive_style_mapping(image_analysis)
    log.info("Phase 1 complete — character=%r, style_map: %s",
             product_summary.get("character_name", "?"),
             {k: v for k, v in style_map.items() if v})

    # ── Phase 2: SEO Copy Generation (text-only — images NOT re-sent) ────────
    log.info("Phase 2 — SEO copy generation (text-only)")
    phase2_result = _phase2_generate_copy(client, cfg, meta, image_analysis, product_summary)

    # ── Merge Phase 1 + Phase 2 into final GeneratedCopy ──────────────────────
    return _parse_response(phase2_result, meta, cfg.brand_tags,
                           image_analysis=image_analysis,
                           style_image_mapping=style_map)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — Dedicated Visual Classification
# ═══════════════════════════════════════════════════════════════════════════════

def _phase1_classify_images(
    client: OpenAI,
    cfg: Config,
    n_images: int,
    image_blocks: list[dict],
) -> tuple[list[dict], dict]:
    """
    Runs a dedicated, focused classification pass over all product images.

    Returns (image_classifications, product_summary) where:
      image_classifications — list of per-image fact dicts (with boolean correction applied)
      product_summary       — dict with character_name, case colors, and design_features
                              ready to inject into Phase 2 as text (no images re-sent)

    Uses client.beta.chat.completions.parse (Structured Outputs) so every field
    is guaranteed to be present with the correct type — no JSON parsing errors.
    """
    system = (
        "You are a precise visual QA analyst for e-commerce phone case products. "
        "Your tasks: (1) classify each image, (2) summarise the product for SEO copywriting. "
        "Do NOT write any marketing copy, titles, tags, or product descriptions. "
        "Return ONLY valid JSON matching the required schema — no markdown, no extra text."
    )

    content: list[dict] = [{"type": "text", "text": _build_phase1_user_prompt(n_images)}]
    for i, block in enumerate(image_blocks, 1):
        content.append({"type": "text", "text": f"\nIMAGE {i}:"})
        content.append(block)

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": content},
    ]

    is_reasoning = _is_reasoning_model(cfg.openai_model)
    _MAX_ATTEMPTS = 2
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            if is_reasoning:
                resp = client.beta.chat.completions.parse(
                    model=cfg.openai_model,
                    messages=messages,
                    max_completion_tokens=8000,
                    reasoning_effort="medium",
                    response_format=_Phase1Response,
                )
            else:
                resp = client.beta.chat.completions.parse(
                    model=cfg.openai_model,
                    messages=messages,
                    temperature=0.0,
                    max_tokens=4000,
                    response_format=_Phase1Response,
                )

            parsed = resp.choices[0].message.parsed
            if parsed is None:
                log.warning(
                    "Phase 1 attempt %d/%d: parsed is None — %s",
                    attempt, _MAX_ATTEMPTS,
                    "retrying" if attempt < _MAX_ATTEMPTS else "giving up",
                )
                continue

            image_analysis = _apply_boolean_correction(parsed.image_classifications, n_images)
            product_summary = {
                "character_name":      parsed.product_summary.character_name,
                "case_primary_color":  parsed.product_summary.case_primary_color,
                "case_secondary_color": parsed.product_summary.case_secondary_color,
                "design_features":     parsed.product_summary.design_features,
            }

            if image_analysis:
                if attempt > 1:
                    log.info("Phase 1 succeeded on retry attempt %d/%d", attempt, _MAX_ATTEMPTS)
                return image_analysis, product_summary

            log.warning(
                "Phase 1 attempt %d/%d returned empty classification — %s",
                attempt, _MAX_ATTEMPTS,
                "retrying" if attempt < _MAX_ATTEMPTS else "giving up",
            )
        except Exception as exc:
            log.warning(
                "Phase 1 attempt %d/%d failed: %s — %s",
                attempt, _MAX_ATTEMPTS, exc,
                "retrying" if attempt < _MAX_ATTEMPTS else "giving up",
            )

    log.error("Phase 1 failed after %d attempts — continuing with empty analysis", _MAX_ATTEMPTS)
    return [], {}


def _build_phase1_user_prompt(n_images: int) -> str:
    return f"""You are a precision visual QA analyst classifying {n_images} phone case product images numbered IMAGE 1 to IMAGE {n_images}.

════════════════════════════════════════════════════════════
STEP 1 — CLASSIFY EACH IMAGE
════════════════════════════════════════════════════════════
For EACH image produce one JSON object with EXACTLY these fields, in this order:

  "index"               — integer: the image number (1 to {n_images})
  "description"         — string: ONE sentence describing the overall image.
  "accessory_reasoning" — string: CRITICAL. Explicitly state what accessories are visible.
                          Example (grip + charm): "I see a bunny-shaped grip on the back. I see a beaded wristlet dangling from the corner."
                          Example (none):         "Hand holding case. No grip attached. No charm dangling. No beads or cord visible."
                          Example (edge shot):    "Side-profile edge view. Case bumper is visible. No grip. No charm. The dark sleeve is the person's hand, not a strap."
  "has_grip"            — boolean: true ONLY if accessory_reasoning explicitly mentions a grip/popsocket.
  "has_charm"           — boolean: true ONLY if accessory_reasoning explicitly mentions charm/beads/cord.
  "has_case"            — boolean: true if the phone case body is visible in the image.
  "is_edge_or_profile"  — boolean: true if camera angle shows the side / edge / profile of the case.
  "has_magsafe_ring"    — boolean: true if a circular ring outline is visible on the back.
  "grip_shape"          — string: brief shape description if grip present, else "".
  "thumbnail_quality"   — integer 1–10: image quality as a product thumbnail.

────────────────────────────────────────────────────────────
VISUAL REFERENCE — GRIP (has_grip):
  A GRIP is any raised accessory mounted on the BACK surface of the case:
  • Popsocket / PopGrip — a circular or shaped disc that extends outward
  • Ring holder — a looped metal ring or finger ring
  • Shaped grips — pear, star, heart, strawberry, flower, bottle, shaker, etc.
  ✔ has_grip = true  → see a raised disc, socket, ring, or shaped bump on the back
  ✗ has_grip = false → case back is clean / flat / no visible protrusion

VISUAL REFERENCE — CHARM (has_charm):
  A CHARM is any hanging accessory attached to the case (beads, pearls, lanyard).
  ✔ has_charm = true  → see beads, cord, or hanging accessory connected to case
  ✗ has_charm = false → no hanging items visible
  ⚠️ CRITICAL WARNING: Do NOT confuse a person's hand, fingers, or a dark sleeve
     with a charm or strap. A charm MUST be a distinct physical object (beads, chain,
     cord) clearly hanging off the case — not skin, clothing, or the case's own bumper.

VISUAL REFERENCE — EDGE/PROFILE (is_edge_or_profile):
  ✔ is_edge_or_profile = true  → camera shows side thickness, bumper, or tilted edge
  ✗ is_edge_or_profile = false → flat-on view of front or back face
  ⚠️ CRITICAL WARNING: Do NOT hallucinate a charm just because the side bumper or
     a person's sleeve is visible in an edge shot. Edge shots almost never have charms.

────────────────────────────────────────────────────────────
CONSISTENCY RULE (mandatory):
  • accessory_reasoning contains "grip" / "popsocket" / "disc" → has_grip MUST be true.
  • accessory_reasoning contains "no grip" / "bare back" / "clean back" → has_grip MUST be false.
  • accessory_reasoning contains "charm" / "dangling" / "beads" → has_charm MUST be true.
  • accessory_reasoning contains "no charm" / "no beads" / "no cord" → has_charm MUST be false.

════════════════════════════════════════════════════════════
STEP 2 — SELF-VERIFICATION (mandatory before returning)
════════════════════════════════════════════════════════════
After classifying ALL images, review your results:

  1. Verify you did NOT mark has_charm = true just because a hand or sleeve appears.
  2. Verify you did NOT mark has_grip = true on an edge/profile shot unless a grip is
     clearly popping out of the back in that shot.
  3. Confirm you have exactly {n_images} entries, one per image, all fields present.

════════════════════════════════════════════════════════════
STEP 3 — PRODUCT SUMMARY (fill AFTER classifying all images)
════════════════════════════════════════════════════════════
Examine ALL images together and fill the "product_summary" object:

  "character_name"       — Exact character(s) on the case. Be specific:
                           Sanrio: Cinnamoroll, Kuromi, My Melody, Hello Kitty, Pompompurin, Pochacco
                           San-X: Rilakkuma, Korilakkuma, Kiiroitori, Sumikko Gurashi
                           Original animals: Pink Bunny, White Bear, Yellow Dog, Frog, Duck, Angel, etc.
                           Multiple characters → join with " & ".
                           Cannot identify → "kawaii character"

  "case_primary_color"   — Dominant background color of the case body. MUST be exactly one of:
                           Beige, Black, Blue, Bronze, Brown, Clear, Copper, Gold, Gray,
                           Green, Orange, Pink, Purple, Rainbow, Red, Rose gold, Silver, White, Yellow

  "case_secondary_color" — Second most visible color (character body, grip, charm, or accent).
                           MUST be exactly one of the same Etsy-allowed list above.

  "design_features"      — Notable visual details for SEO copywriting, e.g.:
                           "clear back, glitter star accents, MagSafe ring confirmed"
                           "translucent pink back, pear liquid shaker grip with floating stars"
                           Mention: clear/transparent back, glitter, 3D elements, printed patterns,
                           special grip theme, charm bead colors, any text or logo on the case.
                           Empty string if no notable features beyond a plain case.

════════════════════════════════════════════════════════════
OUTPUT FORMAT
════════════════════════════════════════════════════════════
Return a JSON object with TWO top-level keys — no markdown, no commentary:
{{
  "product_summary": {{
    "character_name": "Cinnamoroll",
    "case_primary_color": "White",
    "case_secondary_color": "Blue",
    "design_features": "clear back, MagSafe ring confirmed"
  }},
  "image_classifications": [
    {{ "index": 1, "description": "...", "accessory_reasoning": "...", "has_grip": true, "has_charm": false,
       "has_case": true, "is_edge_or_profile": false, "has_magsafe_ring": true, "grip_shape": "pear", "thumbnail_quality": 8 }},
    ...
  ]
}}

Classify ALL {n_images} images. One object per image in ascending index order."""


def _apply_boolean_correction(items: list[_ImageClass], n_images: int) -> list[dict]:
    """
    Apply description-driven boolean correction to Pydantic-parsed Phase 1 results.

    Combines both description and accessory_reasoning text fields — the model was
    forced to write its visual logic in accessory_reasoning before committing to
    booleans, so both fields together form the most reliable signal.
    Negative phrases take priority over positive keywords to prevent hallucination
    (e.g. "no charm" beats "string" found elsewhere in the text).
    """
    _CHARM_KW  = ("charm", "dangling", "dangle", "lanyard", "beads", "beaded",
                  "cord", "strap hanging", "hanging strap", "string", "tassel",
                  "wristlet", "pendant", "hanging")
    _NO_CHARM  = ("no charm", "no dangling", "no lanyard", "no beads", "no strap",
                  "no string", "no hanging", "without charm", "bare corner")
    _GRIP_KW   = ("grip", "popsocket", "pop socket", "pop-socket", "phone holder",
                  "ring holder", "finger ring", "pear-shaped", "shaker grip",
                  "disc", "socket", "protrusion")
    _NO_GRIP   = ("no grip", "no popsocket", "no holder", "no socket",
                  "without grip", "bare back", "clean back")

    result: list[dict] = []
    for item in items:
        try:
            # Combine description + accessory_reasoning for maximum signal coverage
            combined_text = f"{item.description} {item.accessory_reasoning}".lower()
            has_grip  = item.has_grip
            has_charm = item.has_charm

            # Negative phrases override first (prevents finger/sleeve hallucinations)
            if any(p in combined_text for p in _NO_CHARM):
                has_charm = False
            elif any(k in combined_text for k in _CHARM_KW):
                has_charm = True

            if any(p in combined_text for p in _NO_GRIP):
                has_grip = False
            elif any(k in combined_text for k in _GRIP_KW):
                has_grip = True

            result.append({
                "index":              item.index,
                "description":        item.description,
                "has_grip":           has_grip,
                "has_charm":          has_charm,
                "has_case":           item.has_case,
                "is_edge_or_profile": item.is_edge_or_profile,
                "has_magsafe_ring":   item.has_magsafe_ring,
                "grip_shape":         item.grip_shape,
                "thumbnail_quality":  item.thumbnail_quality,
                # Legacy fields expected by xlsx_builder
                "is_held_in_hand":    False,
                "shows_back_of_case": not item.is_edge_or_profile,
            })
        except (ValueError, TypeError):
            continue

    log.info("Phase 1 parsed: %d/%d images classified", len(result), n_images)
    return result


def _derive_style_mapping(image_analysis: list[dict]) -> dict[str, list[int]]:
    """
    Algorithmically build style → [1-based image indices] mapping.

    Index 1 is the thumbnail — always excluded from linked images.
    Edge/profile shots go to 'Case Only (edge)' as low-priority fallback.
    Within each style, indices are sorted best-quality-first so the image at
    position [0] — the one Shop Uploader links — is always the sharpest shot.
    Sort key: thumbnail_quality DESC, then index ASC (earlier upload wins ties).
    """
    mapping: dict[str, list[int]] = {
        "Case+Grip+Charm": [], "Case+Grip": [], "Case+Charm": [],
        "Case Only": [], "Case Only (edge)": [], "Grip Only": [], "Charm Only": [],
    }

    # Build quality lookup keyed by 1-based image index
    quality: dict[int, int] = {
        int(img.get("index", 0)): int(img.get("thumbnail_quality", 5))
        for img in image_analysis
    }

    for img in image_analysis:
        idx       = int(img.get("index", 0))
        if idx < 2:   # index 1 is thumbnail — never link it
            continue
        has_grip  = bool(img.get("has_grip",  False))
        has_charm = bool(img.get("has_charm", False))
        has_case  = bool(img.get("has_case",  True))
        edge      = bool(img.get("is_edge_or_profile", False))

        if has_case:
            if has_grip and has_charm:
                mapping["Case+Grip+Charm"].append(idx)
            elif has_grip:
                mapping["Case+Grip"].append(idx)
            elif has_charm:
                mapping["Case+Charm"].append(idx)
            elif edge:
                mapping["Case Only (edge)"].append(idx)
            else:
                mapping["Case Only"].append(idx)
        elif has_grip:
            mapping["Grip Only"].append(idx)
        # standalone charm (no case, no grip) — never linked

    mapping["Charm Only"] = []  # always empty per Etsy/Shop Uploader rules

    # Sort each style's list: best thumbnail_quality first, ties broken by lower index
    for style in mapping:
        mapping[style].sort(key=lambda i: (-quality.get(i, 5), i))

    return mapping


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — SEO Copy Generation (informed by Phase 1 facts)
# ═══════════════════════════════════════════════════════════════════════════════

def _phase2_generate_copy(
    client: OpenAI,
    cfg: Config,
    meta: ProductMeta,
    image_analysis: list[dict],
    product_summary: dict,
) -> _Phase2Response:
    """
    Generate SEO copy (title, description, tags, colors) using Phase 1
    classification facts and product summary as pure text context.

    No images are re-sent — character name, colors, and design details were
    captured by Phase 1 and injected via product_summary.  This cuts the
    per-listing vision token cost by ~50% and speeds up the call significantly.

    Uses client.beta.chat.completions.parse with _Phase2Response so every
    output field is guaranteed to exist with the correct type — no JSON parse
    errors, no missing keys, no hallucinatory formatting.
    """
    _TEXT_ONLY_PREAMBLE = (
        "OVERRIDE — TEXT-ONLY MODE: All image analysis was completed in Phase 1. "
        "Character name, colors, and design details are provided in the PRODUCT SUMMARY "
        "in the user message. Use the PRODUCT SUMMARY directly for all character "
        "identification, primary_color, secondary_color, and design detail decisions. "
        "Trust all Phase 1 classification facts completely.\n\n"
    )
    system_prompt = _TEXT_ONLY_PREAMBLE + _build_system_prompt(cfg.shop_name, cfg.brand_tags)
    user_prompt   = _build_user_prompt(meta, cfg.brand_tags, image_analysis, product_summary)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    is_reasoning = _is_reasoning_model(cfg.openai_model)
    if is_reasoning:
        resp = client.beta.chat.completions.parse(
            model=cfg.openai_model,
            messages=messages,
            max_completion_tokens=16000,
            reasoning_effort="medium",
            response_format=_Phase2Response,
        )
    else:
        resp = client.beta.chat.completions.parse(
            model=cfg.openai_model,
            messages=messages,
            temperature=0.4,
            max_tokens=4800,
            response_format=_Phase2Response,
        )

    parsed = resp.choices[0].message.parsed
    if not parsed:
        raise ValueError("Phase 2 returned an empty or invalid parsed response.")
    return parsed


def _is_reasoning_model(model: str) -> bool:
    return (
        model.startswith("gpt-5")
        or model.startswith("o1")
        or model.startswith("o3")
        or model.startswith("o4")
    )


def _build_system_prompt(shop_name: str = "Y2KASEshop", brand_tags: list[str] | None = None) -> str:
    # NOTE: use string concatenation (NOT an f-string) — the prompt body contains
    # literal JSON curly braces that Python would misinterpret as format specifiers.
    _tags_display = (
        ", ".join(f'"{t}"' for t in brand_tags)
        if brand_tags
        else '"y2kase"'
    )
    _PROMPT_HEADER = (
        "You are an elite, world-class Etsy SEO algorithm expert and top-tier professional seller"
        " of kawaii Y2K phone cases for the " + shop_name + " brand. Your #1 priority is"
        " generating deeply researched, intensely SEO-driven listings that dominate page-one"
        " rankings on Etsy.\n"
        "\nSHOP BRAND TAGS (MANDATORY — include ALL of these exactly in your tags output): "
        + _tags_display + "\n"
    )
    _PROMPT_KEYS = (
        '\nYou MUST return ONLY a valid JSON object with exactly FIVE keys:'
        ' "title", "description", "tags", "primary_color", "secondary_color".\n'
        'Do NOT include style_image_mapping or image_analysis — those are handled by Phase 1.\n'
    )
    return _PROMPT_HEADER + _PROMPT_KEYS + """No markdown. No code fences. No extra text outside the JSON.

═══════════════════════════════════════
STEP 1 — TITLE (CRITICAL — 140 CHARS MAX)
═══════════════════════════════════════
Structure: [Character+Color] [MAGSAFE if confirmed] Case [with Accessory], [Style] [Color] Cover iPhone 17 16 15 14 13 Pro Max, [Aesthetic] Gift

RULES:
- Include "MAGSAFE" IN ALL CAPS only if the magnetic ring is confirmed in the Phase 1 product summary.
- Front-load most powerful keywords in first 40 characters.
- Target EXACTLY 140 characters. Never below 130.
- Zero fluff: no "A", "The", "Beautiful", "Amazing".
- Separate keyword phrases with commas.
- Include: iPhone 17 16 15 14 13 Pro Max.
- Include character name, accessory name, aesthetic (Kawaii, Y2K, Coquette).

EXAMPLE: "Cute Rilakkuma MAGSAFE Case with Strawberry Shaker Grip & Charm, Kawaii Pink Clear Cover iPhone 17 16 15 14 13 Pro Max, Y2K Coquette Gift"
(adapt for your product — do NOT copy this example verbatim)

═══════════════════════════════════════
STEP 2 — DESCRIPTION (MANDATORY FORMAT — FOLLOW EXACTLY — MINIMUM 500 WORDS)
═══════════════════════════════════════

⚠️ ABSOLUTE RULES — violating ANY of these is a critical failure:
1. Follow the EXACT structure below in the EXACT order shown.
2. NEVER start with a section header, "What's Included", or any list. ALWAYS start with the emoji hook line.
3. MINIMUM 500 words. Count carefully before finalizing.
4. The first 160 characters MUST be maximum keyword-density — this is the Google + Etsy meta snippet.
5. Weave these keyword types NATURALLY throughout EVERY paragraph (not stuffed — woven):
   → Character name | Y2K aesthetic | kawaii | cute iPhone case | [accessory type] | aesthetic phone case
6. Every [BRACKET] placeholder MUST be replaced with actual product-specific content from the Phase 1 product summary.

SEO DEPTH REQUIREMENT: Each of the opening paragraphs must include at least 3 distinct high-value
search phrases. Long-tail phrases ("kawaii iPhone case with pear grip", "Y2K aesthetic phone charm",
"cute [character] phone case gift") outperform single keywords and must appear throughout the copy.

MAGSAFE DESCRIPTION RULE (CRITICAL):
→ IF MagSafe ring is confirmed in Phase 1:
   - The opening hook line MUST include "MagSafe" (e.g. "...this [character] MagSafe iPhone case...")
   - Paragraph 2 (product uniqueness) MUST mention the built-in magnetic ring explicitly:
     e.g. "The case features a built-in white MagSafe ring for seamless wireless charging."
   - Key Features MUST include the MagSafe bullet.
→ IF MagSafe ring is NOT confirmed: do NOT mention MagSafe anywhere in the description.

--- START OF REQUIRED DESCRIPTION FORMAT ---

[EMOJI that matches the character/product] [DESIRE HOOK LINE — keyword-packed opening sentence or two. Do NOT write a generic opener. Immediately name the character, the vibe (Y2K/kawaii/coquette), and what the product includes. Example: "Sweeten up your whole aesthetic with this fully loaded [Character] kawaii iPhone case set — the cutest Y2K phone accessory you'll ever own! ✨"]

[PARAGRAPH 1 — AESTHETIC & DESIRE — 3-4 sentences. Embrace the full emotional fantasy. Name the character. Reference the aesthetic (Y2K, kawaii, coquette). Use vivid, desire-creating language. MUST include: "kawaii phone case", "[character] case", "Y2K aesthetic", "cute iPhone case" or synonyms woven in naturally. End with a reason to buy it as a gift or treat.]

[PARAGRAPH 2 — PRODUCT UNIQUENESS — 3-4 sentences. Start with something like "This isn't just a phone case — it's a complete [character] experience." Describe the actual decal/artwork from the Phase 1 product summary: character design, colors, any special print details (glitter, 3D elements, clear back, MagSafe ring if confirmed). Mention the soft TPU/silicone material and how the clear back lets the phone's color complement the artwork. MUST include at least 2 of: "clear iPhone case", "silicone phone case", "[character] design", "cute phone case", "kawaii [character]".]

[IF GRIP CONFIRMED IN PHASE 1 — PARAGRAPH 3: Start with something like "The absolute star of the show is the attachable [grip name]..." Describe the grip in vivid detail: exact shape (pear, bunny, strawberry, etc.), any liquid shaker effect and what floats inside, the character theming. Explain it is removable and compatible with standard PopSocket mounts. MUST include: "[shape] grip", "phone grip", "popsocket".]

[IF CHARM CONFIRMED IN PHASE 1 — PARAGRAPH 4: Describe the beaded charm in detail: bead colors, any pendant character or decorative element, how it attaches to the case loop. Explain it functions as a wristlet strap. MUST include: "beaded charm", "phone wristlet" or "wristlet charm", "beaded strap".]

✨ Key Features

[BULLET LIST — EXACTLY 5–7 bullets. Only features CONFIRMED IN PHASE 1 CLASSIFICATION. Zero fabrication.
Format STRICTLY as: "Feature Name: One full descriptive sentence with natural keyword integration."
Each bullet MUST be on its own line with a blank line between bullets for readability.

REQUIRED bullets (include these when applicable):
• [Character] Kawaii Design: [Describe the specific artwork — character name, color, pose or expression, any special print detail from the Phase 1 product summary.]
• Soft TPU Silicone Protection: Flexible, shock-absorbent silicone body provides excellent drop protection while keeping your phone ultra-lightweight and easy to grip.
• Raised Edge Bezels: Slightly elevated lip around the screen and camera module protects against face-down scratches and drops.
• Precise Cutouts: Perfectly fitted openings for all buttons, speakers, charging port, and camera — no signal interference, no fumbling.
IF MAGSAFE CONFIRMED → • MagSafe Compatible: Features a built-in white magnetic ring for seamless MagSafe charging and full compatibility with all MagSafe accessories.
IF GRIP CONFIRMED    → • [Shape] [Grip Name]: [Describe in full detail — shape, color, shaker liquid effect if present, what floats inside, character theming. State it is removable and PopSocket-compatible.]
IF CHARM CONFIRMED   → • Hand-Beaded Wristlet Charm: [Describe bead colors, pendant, arrangement. State it attaches to the case loop and functions as a secure wristlet strap.]
• Perfect Kawaii Gift: Comes beautifully packaged — ideal as a birthday gift, Valentine's gift, Christmas present, or a well-deserved self-treat for any Y2K or kawaii aesthetic lover.]

📱 Device Compatibility

Available for the following iPhone models:

iPhone 17 Series: iPhone 17, 17 Pro, 17 Pro Max

iPhone 16 Series: iPhone 16, 16 Pro, 16 Pro Max

iPhone 15 Series: iPhone 15, 15 Pro, 15 Pro Max

iPhone 14 Series: iPhone 14, 14 Pro, 14 Pro Max

iPhone 13 Series: iPhone 13

(Please Note: 13 Pro, 13 Pro Max, lower models, Plus and Mini models are NOT available for this design.)

Please select your exact iPhone model from the dropdown at checkout to guarantee a perfect fit.

📦 What's Included

Choose your preferred bundle from the Styles dropdown:

🌟 The Full Set: ([Case name] + [Grip name] + Beaded Charm)

🔵 Case + Grip: ([Case name] + [Grip name])

💛 Case + Charm: ([Case name] + Beaded Charm)

🤍 Case Only: (The [Character] [Case name])

🌀 Grip Only: (The [Grip name])

✨ Charm Only: (The Beaded Wristlet Charm)

❤️ The """ + shop_name + """ Promise

At """ + shop_name + """, every kawaii phone case is rigorously quality-checked before it ever leaves our hands. We are dedicated to delivering the absolute best cute iPhone cases and Y2K phone accessories while providing maximum protection for your device. We believe your phone should be safe AND adorable — because why choose? Every single order is hand-packaged with love by our team and includes a special free gift just for you! Have a question about sizing, compatibility, or your order? Message us — we reply within 24 hours.

🚚 Shipping & Processing

All orders are processed and ready to ship within 3–5 business days. We ship worldwide with full tracking provided for every order, so you can follow your cute kawaii package every step of the way from our studio to your doorstep. Please allow standard carrier transit times for delivery.

--- END OF REQUIRED DESCRIPTION FORMAT ---

FINAL CHECKLIST before outputting (verify each):
□ Starts with emoji + desire hook line — NOT a section header or bullet list
□ IF MAGSAFE CONFIRMED: "MagSafe" appears in the hook line, the aesthetic paragraph, AND the Key Features bullet
□ IF MAGSAFE NOT CONFIRMED: the word "MagSafe" does NOT appear anywhere in the description
□ Paragraph 1 contains "kawaii phone case", the character's name, and "Y2K aesthetic"
□ Paragraph 2 contains "This isn't just a phone case" style opening and product-specific artwork details
□ All [BRACKET] placeholders replaced with actual product content from the Phase 1 summary
□ Grip paragraph present IF grip is confirmed in Phase 1 classification
□ Charm paragraph present IF charm is confirmed in Phase 1 classification
□ Key Features: 5–7 bullets, each on its own line with blank line between
□ Device Compatibility: each series on its own paragraph with blank line between
□ What's Included: each bundle option on its own line with blank line between
□ Total word count ≥ 500 words

═══════════════════════════════════════
STEP 3 — TAGS (EXACTLY 13 — RESEARCH-VERIFIED SEO INTENSITY)
═══════════════════════════════════════

CRITICAL RULES:
- Exactly 13 tags. Not 12. Not 14. Exactly 13.
- Each tag: maximum 20 characters INCLUDING spaces.
- All lowercase only. Real search terms buyers type. No punctuation except hyphens.
- Every tag must be directly relevant to THIS specific product.

TAG STRATEGY — 5 research-verified tiers (fill in order):

TIER 1 — BRAND IDENTITY (mandatory — ALL provided brand tags must appear):
  [Brand tags for this shop are provided in the user prompt — include ALL of them exactly as written]

TIER 2 — HIGHEST VOLUME UNIVERSAL TAGS (include ALL 3 — non-negotiable):
  These are verified high-search-volume terms for this exact product category:
  → "kawaii phone case"      (17 chars ✓ — 1,600+ monthly Etsy searches)
  → "cute iphone case"       (16 chars ✓ — 9,900+ monthly Etsy searches — highest-volume term)
  → "y2k phone case"         (14 chars ✓ — trending, high buyer intent)

TIER 3 — MAGSAFE KEYWORDS (include ALL 3 — MANDATORY for every listing):
  All products in this shop are MagSafe-compatible. These tags are non-negotiable:
  → "magsafe iphone case"    (19 chars ✓ — top MagSafe search term on Etsy)
  → "magsafe phone case"     (18 chars ✓ — second highest MagSafe search term)
  → "magsafe case"           (12 chars ✓ — short-tail MagSafe search, broad reach)

TIER 4 — iPHONE MODEL EXACT-MATCH (exactly 2 tags — highest-converting search terms):
  → "iphone 17 case"          (14 chars ✓ — newest model, highest search intent)
  → "iphone 16 pro max"       (17 chars ✓ — second most searched model tag)

TIER 5 — PRODUCT SPECIFIC + BUYER INTENT (fill remaining 4 slots):
  SLOT A — Aesthetic/style tag (always eligible, pick best fit):
    → "aesthetic phone case"  (20 chars ✓)
    → "kawaii iphone case"    (18 chars ✓)
    → "coquette phone case"   (19 chars ✓)
  SLOT B — Character/product specific tag (from the Phase 1 product summary):
    → "[character name] case"  e.g. "rilakkuma case", "bunny iphone case", "angel phone case"
  SLOT C — Accessory tag (ONLY if that accessory is CONFIRMED IN PHASE 1):
    IF charm confirmed  → "beaded phone charm"   (18 chars ✓)
    IF charm confirmed  → "phone wristlet"       (14 chars ✓)
    IF grip confirmed   → "phone grip kawaii"    (17 chars ✓)
    IF no accessory     → "kawaii gift for her"  (19 chars ✓)
  SLOT D — Gift intent tag (always eligible):
    → "cute gift for her"     (17 chars ✓ — high-converting gift intent tag)
    → "kawaii gift for her"   (19 chars ✓)
    → "gift for teen girl"    (18 chars ✓)

SELECTION PROCESS:
1. TIER 1: ALL provided brand tags (mandatory — count = number of brand tags given)
2. TIER 2: all 3 universal tags (mandatory)
3. TIER 3: all 3 MagSafe tags (mandatory — every listing)
4. TIER 4: 2 exact iPhone model tags (mandatory)
5. TIER 5: fill remaining slots with product-specific + intent tags
= Total must equal EXACTLY 13 tags

VERIFICATION: Count every tag. Measure every tag ≤ 20 chars. Total must = 13.

═══════════════════════════════════════
ABSOLUTE PROHIBITIONS
═══════════════════════════════════════
- NEVER claim MagSafe or include "MAGSAFE" unless confirmed in the Phase 1 summary
- NEVER list Plus or Mini iPhone models as compatible
- NEVER list Samsung or Android
- NEVER fabricate accessories not confirmed in the Phase 1 classification
- NEVER start the description with "What's Included" or any section header
- NEVER write a description shorter than 300 words
- NEVER use a color value for primary_color or secondary_color that is not in the allowed list:
  Beige, Black, Blue, Bronze, Brown, Clear, Copper, Gold, Gray, Green, Orange, Pink, Purple, Rainbow, Red, Rose gold, Silver, White, Yellow
- NEVER include a tag longer than 20 characters
- NEVER produce fewer or more than exactly 13 tags"""


def _build_user_prompt(
    meta: ProductMeta,
    brand_tags: list[str] | None = None,
    image_analysis: list[dict] | None = None,
    product_summary: dict | None = None,
) -> str:
    """
    Phase 2 user prompt. Injects Phase 1 classification facts and the product
    summary (character name, colors, design features) as text so the model
    writes accurate copy without re-analysing any images.
    """
    lines: list[str] = [
        "Generate an SEO-optimized Etsy listing for this phone case product.",
        "",
        "=== PRODUCT FACTS ===",
        f"Shop: {meta.extra_notes or 'Y2KASEshop'} (HK seller, production partner: Shenzhen Mumusan Technology)",
        "Product type: Kawaii Y2K phone case (possibly with accessories)",
        "Material: Silicone",
    ]

    if brand_tags:
        count_word = {1: "this", 2: "BOTH", 3: "ALL THREE"}.get(len(brand_tags), "ALL")
        lines.append(
            f"BRAND IDENTITY TAGS (include {count_word} in your tags output, exactly as written): "
            + ", ".join(f'"{t}"' for t in brand_tags)
        )

    if meta.keyword_seeds:
        lines.append(f"Known keywords for this product line: {', '.join(meta.keyword_seeds)}")

    if meta.extra_notes:
        lines.append(f"Additional notes: {meta.extra_notes}")

    # ── Inject product summary (character, colors, design — from Phase 1) ─────
    if product_summary:
        lines += [
            "",
            "=== PRODUCT SUMMARY (from Phase 1 vision — use directly, do not re-analyse images) ===",
            f"Character: {product_summary.get('character_name', 'kawaii character')}",
            f"Primary Color: {product_summary.get('case_primary_color', '')}",
            f"Secondary Color: {product_summary.get('case_secondary_color', '')}",
            f"Design Features: {product_summary.get('design_features', '')}",
        ]

    # ── Inject Phase 1 classification facts ───────────────────────────────────
    if image_analysis:
        has_grip    = any(img.get("has_grip",        False) for img in image_analysis)
        has_charm   = any(img.get("has_charm",       False) for img in image_analysis)
        has_magsafe = any(img.get("has_magsafe_ring",False) for img in image_analysis)
        grip_shapes = list({
            img["grip_shape"] for img in image_analysis
            if img.get("has_grip") and img.get("grip_shape")
        })

        lines += [
            "",
            "=== PHASE 1 CLASSIFICATION RESULTS (TRUST THESE — do NOT contradict them) ===",
            f"MagSafe ring detected: {'YES — include MAGSAFE in title and description' if has_magsafe else 'NO — do NOT mention MagSafe anywhere'}",
            f"Grip accessory present: {'YES — ' + ('shape: ' + ', '.join(grip_shapes) if grip_shapes else 'yes') if has_grip else 'NO — omit grip paragraphs and grip features'}",
            f"Charm accessory present: {'YES' if has_charm else 'NO — omit charm paragraphs and charm features'}",
            "",
            "Per-image classification:",
        ]
        for img in sorted(image_analysis, key=lambda x: x.get("index", 0)):
            grip_flag  = "GRIP" if img.get("has_grip")  else "no-grip"
            charm_flag = "CHARM" if img.get("has_charm") else "no-charm"
            edge_flag  = " EDGE-SHOT" if img.get("is_edge_or_profile") else ""
            mag_flag   = " MAGSAFE" if img.get("has_magsafe_ring") else ""
            lines.append(
                f"  IMAGE {img['index']}: {img.get('description', '')} "
                f"[{grip_flag} | {charm_flag}{edge_flag}{mag_flag}]"
            )

    lines += [
        "",
        "=== YOUR TASK ===",
        "1. " + (
            "Use the PRODUCT SUMMARY above for the character name, colors, and design details "
            "— all visual analysis is already complete. Do NOT attempt to identify these from images."
            if product_summary else
            "Identify the CHARACTER(S) and colors from the product details above — be specific "
            "(Cinnamoroll, Kuromi, My Melody, Rilakkuma, original character, etc.)."
        ),
        "2. Use ONLY the Phase 1 classification facts above for MagSafe/grip/charm decisions — do NOT second-guess them.",
        "3. Write the title, description, and tags following ALL system prompt rules exactly.",
        "",
        "Return ONLY a valid JSON object with EXACTLY these FIVE top-level keys "
        "(no markdown, no code fences, no extra text outside the JSON):",
        '  "title", "description", "tags", "primary_color", "secondary_color"',
    ]

    return "\n".join(lines)


def _encode_images(paths: list[Path]) -> list[dict]:
    messages = []
    for path in paths:
        try:
            data = path.read_bytes()
            b64 = base64.b64encode(data).decode("utf-8")
            ext = path.suffix.lower().lstrip(".")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            messages.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high",  # high detail for character identification
                    },
                }
            )
        except Exception as exc:
            log.warning("Could not encode image %s: %s", path.name, exc)
    return messages


_ETSY_COLORS = {
    "beige", "black", "blue", "bronze", "brown", "clear", "copper", "gold",
    "gray", "green", "orange", "pink", "purple", "rainbow", "red",
    "rose gold", "silver", "white", "yellow",
}


def _parse_response(
    parsed_data: _Phase2Response,
    meta: ProductMeta,
    brand_tags: list[str] | None = None,
    image_analysis: list[dict] | None = None,
    style_image_mapping: dict[str, list[int]] | None = None,
) -> GeneratedCopy:
    """
    Convert the Pydantic Phase 2 object into a GeneratedCopy.
    Phase 1 data (image_analysis and style_image_mapping) is injected directly.
    All fields are guaranteed present and correctly typed by Pydantic — no JSON
    parsing, no missing-key guards, no JSONDecodeError possible.
    """
    title = str(parsed_data.title).strip()

    # Enforce 140-char limit — truncate at word boundary if AI exceeded it
    if len(title) > 140:
        title = title[:140].rsplit(" ", 1)[0].rstrip(",").strip()
        log.info("Title truncated to %d chars: %s", len(title), title[:60])

    # Etsy rule: each of [%, :, &, +] may appear at most ONCE in a title.
    _SPECIAL_SUBS = {"&": "and", "+": "and", "%": "percent", ":": ","}
    for char, replacement in _SPECIAL_SUBS.items():
        if title.count(char) > 1:
            parts = title.split(char)
            title = parts[0] + char + f" {replacement} ".join(parts[1:])
            title = " ".join(title.split())
            log.info("Title: deduplicated '%s' → using '%s' for extras", char, replacement)

    description = str(parsed_data.description).strip()

    # Pydantic guarantees tags is list[str] — no isinstance fallback needed.
    tags = [_clean_tag(t) for t in parsed_data.tags if str(t).strip()]
    tags = [t for t in tags if t][:13]
    tags = _ensure_shop_tags(tags, brand_tags or [])

    primary_color   = _validate_color(parsed_data.primary_color)
    secondary_color = _validate_color(parsed_data.secondary_color)

    # ── Use Phase 1 data when provided; fall back to parsing JSON fields ──────
    final_image_analysis: list[dict] = image_analysis if image_analysis else []
    final_style_map: dict[str, list[int]] = style_image_mapping if style_image_mapping else {}

    # Ensure all standard style keys are present (even if empty)
    _all_styles = {
        "Case+Grip+Charm", "Case+Grip", "Case+Charm",
        "Case Only", "Case Only (edge)", "Grip Only", "Charm Only",
    }
    for s in _all_styles:
        final_style_map.setdefault(s, [])
    final_style_map["Charm Only"] = []
    final_style_map["Grip Only"]  = []

    mapped = {k: v for k, v in final_style_map.items() if v}
    if mapped:
        log.info("Style image mapping (Phase 1): %s", mapped)
    else:
        log.warning("Style image mapping is empty — no images linked to variation styles")

    if final_image_analysis:
        log.info("Image analysis: %d images (from Phase 1)", len(final_image_analysis))

    if meta.banned_phrases:
        for phrase in meta.banned_phrases:
            title = re.sub(re.escape(phrase), "", title, flags=re.IGNORECASE).strip()
            description = re.sub(re.escape(phrase), "", description, flags=re.IGNORECASE).strip()

    return GeneratedCopy(
        title=title,
        description=description,
        tags=tags,
        primary_color=primary_color,
        secondary_color=secondary_color,
        style_image_mapping=final_style_map,
        image_analysis=final_image_analysis,
    )


def _validate_color(raw: str) -> str:
    """Return the color if it's in Etsy's allowed list, else empty string."""
    if not raw:
        return ""
    clean = str(raw).strip().lower()
    if clean in _ETSY_COLORS:
        # Return title-cased (matching Etsy's display: "Pink", "Rose gold", etc.)
        for allowed in _ETSY_COLORS:
            if allowed == clean:
                return allowed.title() if " " not in allowed else " ".join(
                    w.capitalize() for w in allowed.split()
                )
    log.warning("AI returned non-allowed color %r — skipping", raw)
    return ""


def _clean_tag(raw: str) -> str:
    tag = str(raw).strip().lower()
    tag = re.sub(r"[^\w\s\-]", "", tag)
    tag = re.sub(r"\s+", " ", tag).strip()
    return tag[:20]


def _ensure_shop_tags(tags: list[str], brand_tags: list[str]) -> list[str]:
    """Guarantee brand identity and all 3 MagSafe tags are always present.

    core_brand is derived from the provided brand_tags so that different shops
    get their own identity tags (not the hardcoded "y2kase" fallback).
    """
    # Use the shop's own brand_tags as the mandatory brand identity.
    # Only fall back to "y2kase" when no brand_tags were configured at all.
    core_brand = [t[:20] for t in brand_tags if t] if brand_tags else ["y2kase"]
    magsafe_required = ["magsafe iphone case", "magsafe phone case", "magsafe case"]
    required_all = core_brand + [m for m in magsafe_required if m not in core_brand]

    tag_set = set(tags)
    result = list(tags)
    for req in required_all:
        if req not in tag_set:
            if len(result) < 13:
                result.append(req)
            else:
                # Replace the last non-required tag to make room
                for i in range(len(result) - 1, -1, -1):
                    if result[i] not in required_all:
                        result[i] = req
                        break
            tag_set.add(req)
    return result[:13]
