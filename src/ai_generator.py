"""AI-powered title, description, and tag generation using OpenAI vision.

Role: Elite Etsy SEO expert with deep understanding of kawaii/Y2K phone case market.
Each product folder represents ONE phone case product (multiple images = different angles).
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path

from openai import OpenAI

from src.config import Config
from src.models import GeneratedCopy, ProductMeta, ProductPackage

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 5.0


def generate_copy_for_all(
    packages: list[ProductPackage],
    cfg: Config,
) -> list[str]:
    """Generate AI copy for every package. Returns error messages."""
    client = OpenAI(api_key=cfg.openai_api_key)
    errors: list[str] = []

    for pkg in packages:
        if not pkg.image_paths:
            errors.append(f"[{pkg.meta.parent_sku}] No images — skipping AI generation")
            continue
        try:
            pkg.generated_copy = _generate_with_retry(client, pkg.meta, pkg.image_paths, cfg)
            copy_errors = pkg.generated_copy.validate()
            if copy_errors:
                for ce in copy_errors:
                    errors.append(f"[{pkg.meta.parent_sku}] Copy validation: {ce}")
            else:
                log.info("[%s] Copy generated OK: %s", pkg.meta.parent_sku, pkg.generated_copy.title[:60])
        except Exception as exc:
            errors.append(f"[{pkg.meta.parent_sku}] AI generation failed: {exc}")

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
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(meta)
    # Send up to 8 images so AI can identify characters from multiple angles
    image_messages = _encode_images(image_paths[:8])

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                *image_messages,
            ],
        },
    ]

    response = client.chat.completions.create(
        model=cfg.openai_model,
        messages=messages,
        temperature=0.4,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    raw_content = response.choices[0].message.content or ""
    return _parse_response(raw_content, meta)


def _build_system_prompt() -> str:
    return """You are an elite, world-class Etsy SEO algorithm expert and top-tier professional seller of kawaii Y2K phone cases for the LuvKase / Y2KASEshop brand. Your #1 priority is generating deeply researched, intensely SEO-driven listings that dominate page-one rankings on Etsy.

You MUST return ONLY a valid JSON object with exactly five keys: "title", "description", "tags", "primary_color", "secondary_color".
No markdown. No code fences. No extra text outside the JSON.

═══════════════════════════════════════
STEP 1 — METICULOUS IMAGE ANALYSIS (do this silently before writing)
═══════════════════════════════════════
Examine every pixel of every provided image. Identify and note:

1. CHARACTER(S): Identify the exact character(s) on the case.
   - San-X: Rilakkuma, Korilakkuma, Kiiroitori, Sumikko Gurashi, Cinnamoroll, Pompompurin
   - Sanrio: My Melody, Kuromi, Hello Kitty, Pochacco
   - Animals / originals: dog, bunny, bear, cat, frog, duck, puppy, etc.
   - Look for text/logos on the case itself
   - Note the CHARACTER'S COLOR (yellow dog, pink bunny, white bear, etc.)

2. ██████████ MAGSAFE DETECTION — READ THIS RULE THREE TIMES ██████████

   RULE (1 of 3): Look at the BACK of every case image. A MagSafe ring is a circular
   ring, often white or silver, embedded in the center of the back panel. It may be
   subtle. It may appear as a slight raised circle or a visible ring outline.
   IF YOU SEE IT → the title MUST include "MAGSAFE" in ALL CAPS.
   IF YOU DO NOT SEE IT → do NOT claim MagSafe.

   RULE (2 of 3): Examine EVERY image carefully before concluding no ring exists.
   Some images show the back clearly; others show only the front or sides.
   If ANY image shows a circular ring on the back → include MAGSAFE.
   Do NOT skip this check. Missing a visible MagSafe ring is a critical error.

   RULE (3 of 3): The MagSafe ring is the single most important SEO keyword for this
   product category. If the ring is present and you fail to include "MAGSAFE" in the
   title, the listing will rank significantly lower in search. Check every image twice.
   When in doubt and a circular element is visible on the back → include MAGSAFE.

   ████████████████████████████████████████████████████████████████████

3. ACCESSORIES — examine carefully:
   - GRIP: Pop socket / grip / phone holder? What shape/theme? (pear, strawberry, star, bunny, ball, liquid shaker, etc.)
   - CHARM: Beaded wristlet / charm / lanyard?
   - CAMERA RING: Decorative bezel/ring around the camera cutout?

4. COLORS — examine the case carefully. You will output these as "primary_color" and "secondary_color".
   - PRIMARY COLOR: The dominant/background color of the case body itself.
   - SECONDARY COLOR: The second most visible color (character, grip, charm, accents).
   You MUST map BOTH to EXACTLY ONE value from this Etsy-allowed list:
   Beige, Black, Blue, Bronze, Brown, Clear, Copper, Gold, Gray, Green,
   Orange, Pink, Purple, Rainbow, Red, Rose gold, Silver, White, Yellow
   Mapping guide: Clear/transparent→"Clear" | Light pink→"Pink" | Dark red→"Red"
   | Lilac/lavender→"Purple" | Tan/cream→"Beige" | Multiple equal colors→"Rainbow"
   NEVER invent a color not on that list. Always pick the closest match.

5. DESIGN FEATURES: 3D elements? Glitter? Stars? Bows? Flowers? Hearts?

═══════════════════════════════════════
STEP 2 — TITLE (CRITICAL — 140 CHARS MAX)
═══════════════════════════════════════
Structure: [Character+Color] [MAGSAFE if ring visible] Case [with Accessory], [Style] [Color] Cover iPhone 17 16 15 14 13 Pro Max, [Aesthetic] Gift

RULES:
- Include "MAGSAFE" IN ALL CAPS only if the magnetic ring is visible in the images (see Step 1 rule above — checked 3 times)
- Front-load most powerful keywords in first 40 characters
- Target EXACTLY 140 characters. Never below 130.
- Zero fluff: no "A", "The", "Beautiful", "Amazing"
- Separate keyword phrases with commas
- Include: iPhone 17 16 15 14 13 Pro Max
- Include character name, accessory name, aesthetic (Kawaii, Y2K, Coquette)

EXAMPLE: "Cute Rilakkuma MAGSAFE Case with Strawberry Shaker Grip & Charm, Kawaii Pink Clear Cover iPhone 17 16 15 14 13 Pro Max, Y2K Coquette Gift"
(adapt for your product — do NOT copy this example verbatim)

═══════════════════════════════════════
STEP 3 — DESCRIPTION (MANDATORY FORMAT — FOLLOW EXACTLY)
═══════════════════════════════════════

⚠️ CRITICAL: Follow this EXACT structure in this EXACT order. Do NOT skip sections. Do NOT reorder. NEVER start with "What's Included".

--- START OF REQUIRED DESCRIPTION FORMAT ---

[EMOJI matching character] [ONE-LINE HOOK — first 160 chars MUST be keyword-rich: include character name, MAGSAFE (if applicable), Y2K/kawaii, iPhone case — this is the Google meta description snippet]

[PARAGRAPH: Aesthetic hook — Y2K / kawaii / coquette mood. Mention the character by name. Create desire. 2-3 sentences.]

[PARAGRAPH: Describe what makes THIS case unique. Describe the actual decal art, clear back, character design. Be specific about what you see in the images. 2-3 sentences.]

[IF GRIP visible: PARAGRAPH describing the grip — shape, shaker liquid effect if applicable, character theme]

[IF CHARM visible: PARAGRAPH describing the charm — beads, pendant, color]

✨ Key Features

[BULLET LIST — only features visible in images, 4-6 bullets. Format: "Feature Name: Description."]
- IF MAGSAFE RING VISIBLE: "MagSafe Compatible: Features a built-in magnetic ring, fully compatible with all MagSafe chargers and accessories."
- Camera Protection: [if visible bezel/ring]
- [Other confirmed features]

📱 Device Compatibility

Available for the following iPhone models:

iPhone 17 Series: iPhone 17, 17 Pro, 17 Pro Max
iPhone 16 Series: iPhone 16, 16 Pro, 16 Pro Max
iPhone 15 Series: iPhone 15, 15 Pro, 15 Pro Max
iPhone 14 Series: iPhone 14 Pro Max, 14 Pro, 14/13

(Please Note: 13 Pro, 13 Pro Max, lower models, Plus and Mini models are NOT available for this design).

📦 What's Included

Choose your preferred bundle from the dropdown:

The Full Set: ([Case] + [Grip] + Beaded Charm)
Case + Grip: ([Case] + [Grip])
Case + Charm: ([Case] + Beaded Charm)
Case Only: (The Case)
Grip Only: (The [Grip])
Charm Only

❤️ The LuvKase Promise

At LuvKase, we are dedicated to delivering the best quality cases while providing maximum protection for your device. We believe your phone should be safe and cute. Every order is hand-packaged with love and includes a special free gift just for you!

🚚 Shipping & Processing

All orders are processed and ready to ship within 3-5 business days. We ship worldwide with tracking provided for every order.

--- END OF REQUIRED DESCRIPTION FORMAT ---

REPLACE [Grip] with the actual grip name identified in images (e.g., Pear Grip, Bunny Grip, Strawberry Shaker Grip).
The first 160 characters MUST be keyword-dense.
MINIMUM description length: 300 words.

═══════════════════════════════════════
STEP 4 — TAGS (EXACTLY 13 — MAXIMUM SEO INTENSITY)
═══════════════════════════════════════

CRITICAL RULES:
- Exactly 13 tags. Not 12. Not 14. Exactly 13.
- Each tag: maximum 20 characters INCLUDING spaces.
- All lowercase only. Real search terms buyers type. No punctuation except hyphens.
- Every tag must be directly relevant to THIS specific product in the images.

TAG STRATEGY — cover all 5 categories:

CATEGORY A — BRAND IDENTITY (always include both):
  luvkase
  y2kase

CATEGORY B — CHARACTER / PRODUCT SPECIFIC (2-3 tags, based on what you see in images):
  → [character name] case     e.g. "rilakkuma case", "bunny phone case", "dog iphone case"
  → [character name] magsafe  e.g. "rilakkuma magsafe" (ONLY if ring visible)
  → [character name] gift     e.g. "bunny phone gift"

CATEGORY C — HIGH-VOLUME IPHONE MODEL (2 tags, exact search terms):
  → iphone 17 pro max         (or "iphone 17 case" — always include ONE high-value model tag)
  → iphone 16 case            (include a second model tag)

CATEGORY D — ACCESSORY / FEATURE TAGS (2-3 tags based on what is visible):
  → magsafe iphone case       (ONLY if ring visible)
  → clear iphone case
  → shaker grip case          (if liquid shaker grip visible)
  → beaded phone charm        (if charm visible)
  → kawaii phone case

CATEGORY E — AESTHETIC / BUYER INTENT (2-3 tags, high-converting search phrases):
  → y2k phone case
  → cute iphone case
  → kawaii gift for her
  → coquette iphone case
  → aesthetic phone case

SELECTION PROCESS:
1. Fill Category A first (2 tags — mandatory)
2. Fill Category B with character-specific tags (2-3 tags from images)
3. Fill Category C with iPhone model tags (2 tags)
4. Fill remaining slots with the highest-converting tags from D and E
5. Verify total = exactly 13, each ≤ 20 chars

═══════════════════════════════════════
ABSOLUTE PROHIBITIONS
═══════════════════════════════════════
- NEVER claim MagSafe or include "MAGSAFE" unless the magnetic ring is visually confirmed in images
- NEVER list Plus or Mini iPhone models as compatible
- NEVER list Samsung or Android
- NEVER fabricate accessories not shown in images
- NEVER start the description with "What's Included" or any section header
- NEVER write a description shorter than 300 words
- NEVER use a color value for primary_color or secondary_color that is not in the allowed list:
  Beige, Black, Blue, Bronze, Brown, Clear, Copper, Gold, Gray, Green, Orange, Pink, Purple, Rainbow, Red, Rose gold, Silver, White, Yellow
- NEVER include a tag longer than 20 characters
- NEVER produce fewer or more than exactly 13 tags"""


def _build_user_prompt(meta: ProductMeta) -> str:
    lines: list[str] = [
        "Analyze the images of this phone case product and generate an SEO-optimized Etsy listing.",
        "",
        "=== PRODUCT FACTS (use these as additional context) ===",
        f"Shop: LuvKase / Y2KASEshop (HK seller, production partner: Shenzhen Mumusan Technology)",
        f"Product type: Kawaii Y2K phone case (possibly with accessories)",
        f"Material: Silicone",
    ]

    if meta.keyword_seeds:
        lines.append(f"Known keywords for this product line: {', '.join(meta.keyword_seeds)}")

    if meta.extra_notes:
        lines.append(f"Additional notes: {meta.extra_notes}")

    lines += [
        "",
        "=== YOUR TASK ===",
        "1. Carefully identify the CHARACTER(S) in the images — be specific (e.g. Cinnamoroll, Kuromi, My Melody, Pompompurin, Rilakkuma, original character, etc.).",
        "2. Confirm presence/absence of: MagSafe ring, grip, charm, beads.",
        "3. Generate the title, description, and tags following the system prompt rules exactly.",
        "",
        "Return ONLY a JSON object: { \"title\": \"...\", \"description\": \"...\", \"tags\": [...] }",
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


def _parse_response(raw: str, meta: ProductMeta) -> GeneratedCopy:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI returned non-JSON: {raw[:200]}") from exc

    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    raw_tags = data.get("tags", [])

    if not isinstance(raw_tags, list):
        raw_tags = re.split(r"[,\n]", str(raw_tags))

    tags = [_clean_tag(t) for t in raw_tags if str(t).strip()]
    tags = [t for t in tags if t][:13]
    tags = _ensure_shop_tags(tags)

    # Validate colors against Etsy allowed list
    primary_color = _validate_color(data.get("primary_color", ""))
    secondary_color = _validate_color(data.get("secondary_color", ""))

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


def _ensure_shop_tags(tags: list[str]) -> list[str]:
    """Always include shop identity tags; replace excess if needed."""
    required = ["luvkase", "y2kase"]
    tag_set = set(tags)
    result = list(tags)
    for req in required:
        if req not in tag_set and len(result) < 13:
            result.append(req)
            tag_set.add(req)
        elif req not in tag_set and len(result) >= 13:
            result[-1] = req
    return result[:13]
