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
            pkg.generated_copy = _generate_with_retry(
                client, pkg.meta, pkg.image_paths, cfg,
            )
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
    system_prompt = _build_system_prompt(cfg.shop_name)
    user_prompt = _build_user_prompt(meta, cfg.brand_tags)

    # CRITICAL: send ALL images (up to 10 — Etsy max) and EXPLICITLY LABEL each
    # one with "IMAGE 1:", "IMAGE 2:", etc. interleaved between the actual images.
    # Without these labels, the AI cannot reliably correlate its analysis with
    # the correct image index — it has to GUESS which image is which.
    images_to_send = image_paths[:10]
    image_blocks = _encode_images(images_to_send)

    order_note = (
        f"\n\n═══ {len(image_blocks)} PRODUCT IMAGES — explicitly numbered below ═══\n"
        "These images are already in the CORRECT display order set by the seller.\n"
        "Each image is preceded by 'IMAGE X:' label. Use these EXACT numbers "
        "in your image_analysis output.\n"
    )

    # Build content with explicit labels before each image
    content: list[dict] = [{"type": "text", "text": user_prompt}]
    content.append({"type": "text", "text": order_note})
    for i, block in enumerate(image_blocks, 1):
        content.append({"type": "text", "text": f"\nIMAGE {i}:"})
        content.append(block)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    # Reasoning models (gpt-5, gpt-5.4, gpt-5.5, o-series) use different API params:
    #   - `max_completion_tokens` instead of `max_tokens`
    #   - no `temperature` (only default = 1)
    #   - support `reasoning_effort` (low / medium / high)
    is_reasoning = (
        cfg.openai_model.startswith("gpt-5")
        or cfg.openai_model.startswith("o1")
        or cfg.openai_model.startswith("o3")
        or cfg.openai_model.startswith("o4")
    )

    if is_reasoning:
        response = client.chat.completions.create(
            model=cfg.openai_model,
            messages=messages,
            max_completion_tokens=12000,  # reasoning tokens + output tokens
            response_format={"type": "json_object"},
            reasoning_effort="medium",  # medium = best balance for vision tasks
        )
    else:
        response = client.chat.completions.create(
            model=cfg.openai_model,
            messages=messages,
            temperature=0.3,
            max_tokens=4500,
            response_format={"type": "json_object"},
        )

    raw_content = response.choices[0].message.content or ""
    return _parse_response(raw_content, meta, cfg.brand_tags)


def _build_system_prompt(shop_name: str = "Y2KASEshop") -> str:
    # NOTE: use string concatenation (NOT an f-string) — the prompt body contains
    # literal JSON curly braces that Python would misinterpret as format specifiers.
    _PROMPT_HEADER = (
        "You are an elite, world-class Etsy SEO algorithm expert and top-tier professional seller"
        " of kawaii Y2K phone cases for the " + shop_name + " brand. Your #1 priority is"
        " generating deeply researched, intensely SEO-driven listings that dominate page-one"
        " rankings on Etsy.\n"
    )
    _PROMPT_KEYS = (
        '\nYou MUST return ONLY a valid JSON object with exactly seven keys:'
        ' "title", "description", "tags", "primary_color", "secondary_color",'
        ' "style_image_mapping", "image_analysis".\n'
    )
    return _PROMPT_HEADER + _PROMPT_KEYS + """No markdown. No code fences. No extra text outside the JSON.

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

6. ████ STYLE IMAGE MAPPING — EXAMINE EVERY IMAGE WITH EXTREME VISUAL PRECISION ████

   Before classifying, train your eye on these EXACT visual elements:

   ─────────────────────────────────────────────────────────────
   VISUAL DETECTION GUIDE — ACCESSORIES
   ─────────────────────────────────────────────────────────────
   A) THE GRIP (popsocket / phone holder / finger ring):
      - A circular, oval, or shaped FLAT DISC or POP-UP SOCKET on the BACK of the phone case
      - Usually attached to the center of the back
      - May be themed: pear shape, strawberry, bunny, star, etc.
      - Can be popped up (3D, standing off the case) or flat against the case
      - LOOK: Is there a round/shaped protrusion on the back of the case? = GRIP PRESENT
      - If you see ANY circular disc, pop socket, or holder on the back → GRIP IS PRESENT

   B) THE CHARM (wristlet / lanyard / beaded strap):
      - A string, cord, or chain hanging from the case
      - Usually has beads, a pendant, or decorative elements
      - Hangs off one corner or a loop on the case
      - LOOK: Is there anything dangling/hanging from the case? = CHARM PRESENT

   ─────────────────────────────────────────────────────────────
   CLASSIFICATION RULES (apply in this exact order per image):
   ─────────────────────────────────────────────────────────────

   "Case+Grip+Charm": Grip IS present AND charm IS hanging from the case
                      → Both accessories clearly visible together

   "Case+Grip":       Grip IS present on the back, charm is NOT hanging
                      → You see the grip disc/socket, no dangling beads

   "Case+Charm":      Charm IS hanging, NO grip disc/socket on the back
                      → Dangling beads/lanyard, clean back without popsocket

   "Case Only":       ████ STRICTLY — NO grip, NO charm, NOTHING ATTACHED ████
                      → The back of the case is completely bare/clean
                      → No disc, no popsocket, no dangling strap whatsoever
                      → If you see even a shadow of a grip → NOT Case Only
                      → Common for: close-up back shots, packaging shots,
                        flat-lay of just the case, or showing the MagSafe ring

   "Case Only (edge)": Same as Case Only (strictly NO grip, NO charm) BUT the camera
                        angle shows the EDGE, SIDE PROFILE, or BENT CURVE of the case
                        → These are less flattering shots: side profiles, tilted edge views,
                          shots showing the thickness or the border/bumper of the case
                        → Typically used to show case thickness or fit
                        → MUST still have NO grip and NO charm attached

   "Grip Only":       The grip/popsocket is DETACHED and shown by itself
                      → No phone case in the image, or grip clearly separated

   "Charm Only":      The charm/lanyard/beads shown alone, detached
                      → ALWAYS assign empty list []. Never link to an image.

   ─────────────────────────────────────────────────────────────
   MULTI-STEP VERIFICATION SYSTEM
   ─────────────────────────────────────────────────────────────

   VERIFICATION PASS 1 — Accessory Detection (answer for EACH image):
   ┌──────────────────────────────────────────────────────────────────────┐
   │ A) Grip present?  Look for a circular/shaped DISC on the case BACK.  │
   │    Pear, star, strawberry, bunny shapes = grip. Flat ring = grip.    │
   │    If ANYTHING is stuck to the back center → GRIP = YES              │
   │                                                                      │
   │ B) Charm present? Look for DANGLING beads/cord from the case corner. │
   │    Hanging strap, pearl strand, lanyard, keychain = CHARM = YES      │
   │                                                                      │
   │ C) Is this the CASE or a standalone accessory?                       │
   └──────────────────────────────────────────────────────────────────────┘

   VERIFICATION PASS 2 — Angle Quality (only for Case Only images):
   ┌──────────────────────────────────────────────────────────────────────┐
   │ NICE angle: Camera faces the FRONT or BACK of the case flat-on.     │
   │   → You can clearly see the case design, artwork, or characters.    │
   │   → Classify as "Case Only"                                         │
   │                                                                      │
   │ EDGE angle: Camera is aimed at the SIDE, PROFILE, or TILTED EDGE.  │
   │   → You see the case thickness, bumper, or a bent/curved view.     │
   │   → Classify as "Case Only (edge)"                                  │
   └──────────────────────────────────────────────────────────────────────┘

   VERIFICATION PASS 3 — Final Cross-Check:
   ┌──────────────────────────────────────────────────────────────────────┐
   │ Re-examine every image you classified as "Case Only" or             │
   │ "Case Only (edge)". Ask again: Is there ANY circular disc, pop      │
   │ socket, or holder ANYWHERE in the frame? If YES → reclassify as    │
   │ Case+Grip, Case+Grip+Charm, or Case+Charm accordingly.             │
   │                                                                      │
   │ Re-examine every "Case+Grip" image. Confirm: do you see the grip?  │
   │ If the grip is NOT actually visible → reclassify as Case Only.     │
   └──────────────────────────────────────────────────────────────────────┘

   ─────────────────────────────────────────────────────────────
   CLASSIFICATION DECISION TABLE:
   ─────────────────────────────────────────────────────────────
   Grip=YES + Charm=YES + Case=YES   → "Case+Grip+Charm"
   Grip=YES + Charm=NO  + Case=YES   → "Case+Grip"
   Grip=NO  + Charm=YES + Case=YES   → "Case+Charm"
   Grip=NO  + Charm=NO  + Case=YES + Nice angle  → "Case Only"
   Grip=NO  + Charm=NO  + Case=YES + Edge angle  → "Case Only (edge)"
   Grip=YES + Case=NO (standalone)   → "Grip Only"
   Charm only visible, no case       → "Charm Only"

   ─────────────────────────────────────────────────────────────
   OUTPUT — lists of 1-based indices, BEST/MOST REPRESENTATIVE FIRST:
   ─────────────────────────────────────────────────────────────
   "style_image_mapping": {
     "Case+Grip+Charm": [3, 1],        ← multiple angles welcome
     "Case+Grip":       [2, 5, 8],     ← best grip shot first, others after
     "Case+Charm":      [4],
     "Case Only":       [6, 7],        ← nice flat front/back shots ONLY
     "Case Only (edge)":[9, 10],       ← side/profile/edge shots ONLY
     "Grip Only":       [],
     "Charm Only":      []             ← ALWAYS empty
   }
   RULES:
   - Same index cannot appear in two styles.
   - "Charm Only" and "Grip Only" are ALWAYS empty lists [].
   - Unclassifiable (packaging cards, brand cards) → omit entirely.
   - Within each list, put the BEST/MOST REPRESENTATIVE image FIRST.

═══════════════════════════════════════
STEP 7 — IMAGE_ANALYSIS (STRUCTURED PER-IMAGE FACTS — MOST CRITICAL)
═══════════════════════════════════════

This is the MOST IMPORTANT output. The system uses these facts to classify
images for variation style linking. Structured facts are deterministic and reliable.

For EACH image (1, 2, 3, ... N), produce an object with these fields IN THIS ORDER:

{
  "index": 1,
  "description": "...",          ← FIRST: Write a 1-2 sentence detailed description of what
                                    you SEE in this image. Mention every visible element:
                                    case color, what's on the back, anything attached,
                                    anything dangling, how it's held, etc.
                                    EXAMPLE: "Yellow phone case held in a hand showing the
                                    front. A pear-shaped grip is mounted on the back of the
                                    case. A small yellow beaded charm dangles from the
                                    bottom-right corner via a thin string."
                                    EXAMPLE: "Yellow phone case shown back-facing with a
                                    pear-shaped grip in the center. NO charm or strap
                                    visible anywhere. Clean back composition."
  "has_grip": true,              ← After describing, set true ONLY if your description
                                    mentioned a grip/popsocket/disc/holder.
  "has_charm": true,             ← After describing, set true ONLY if your description
                                    mentioned charm/dangling/lanyard/beads/string/strap.
                                    Even a SUBTLE charm in any corner = true.
  "has_case": true,
  "is_edge_or_profile": false,
  "is_held_in_hand": false,
  "shows_back_of_case": true,
  "thumbnail_quality": 8         ← 1-10. Hero quality matters most for thumbnail decisions.
}

═════ CRITICAL: DESCRIPTION-FIRST CHAIN OF THOUGHT ═════

You MUST write the "description" field FIRST for each image, BEFORE filling in the
boolean fields. The description forces you to actually examine each image carefully.
This is the most important rule in this entire prompt.

CONSISTENCY CHECK (your output will be validated):
  → If your description mentions "charm", "dangling", "lanyard", "beads",
    "strap", "hanging", "string" → has_charm MUST be true.
  → If your description mentions "grip", "popsocket", "disc", "holder",
    "ring" on the back → has_grip MUST be true.
  → If your description says "no charm", "no grip", "clean back", "bare back"
    → those features are false.

Lying to yourself by writing a description with charm visible but setting
has_charm=false will result in WRONG ordering. ALWAYS make the booleans
match what you described.

═════ OUTPUT FORMAT ═════

"image_analysis": [
  {"index": 1, "has_grip": true, "has_charm": true, "has_case": true,
   "is_edge_or_profile": false, "is_held_in_hand": true, "shows_back_of_case": false,
   "thumbnail_quality": 9},
  {"index": 2, "has_grip": true, "has_charm": false, "has_case": true,
   "is_edge_or_profile": false, "is_held_in_hand": true, "shows_back_of_case": true,
   "thumbnail_quality": 10},
  ...
]

   - One object per image, in numerical order by index
   - EVERY image in the folder gets an entry
   - Fields are deterministic facts (booleans/integers), NOT subjective opinions
   - thumbnail_quality is the only subjective field — use it to rank within categories

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
STEP 3 — DESCRIPTION (MANDATORY FORMAT — FOLLOW EXACTLY — MINIMUM 500 WORDS)
═══════════════════════════════════════

⚠️ ABSOLUTE RULES — violating ANY of these is a critical failure:
1. Follow the EXACT structure below in the EXACT order shown.
2. NEVER start with a section header, "What's Included", or any list. ALWAYS start with the emoji hook line.
3. MINIMUM 500 words. Count carefully before finalizing.
4. The first 160 characters MUST be maximum keyword-density — this is the Google + Etsy meta snippet.
5. Weave these keyword types NATURALLY throughout EVERY paragraph (not stuffed — woven):
   → Character name | Y2K aesthetic | kawaii | cute iPhone case | [accessory type] | aesthetic phone case
6. Every [BRACKET] placeholder MUST be replaced with the actual product-specific content from the images.

SEO DEPTH REQUIREMENT: Each of the opening paragraphs must include at least 3 distinct high-value
search phrases. Long-tail phrases ("kawaii iPhone case with pear grip", "Y2K aesthetic phone charm",
"cute [character] phone case gift") outperform single keywords and must appear throughout the copy.

MAGSAFE DESCRIPTION RULE (CRITICAL):
→ IF MagSafe ring was CONFIRMED in Step 1:
   - The opening hook line MUST include "MagSafe" (e.g. "...this [character] MagSafe iPhone case...")
   - Paragraph 2 (product uniqueness) MUST mention the built-in magnetic ring explicitly:
     e.g. "The case features a built-in white MagSafe ring for seamless wireless charging."
   - Key Features MUST include the MagSafe bullet.
→ IF MagSafe ring was NOT confirmed: do NOT mention MagSafe anywhere in the description.

--- START OF REQUIRED DESCRIPTION FORMAT ---

[EMOJI that matches the character/product] [DESIRE HOOK LINE — keyword-packed opening sentence or two. Do NOT write a generic opener. Immediately name the character, the vibe (Y2K/kawaii/coquette), and what the product includes. Example: "Sweeten up your whole aesthetic with this fully loaded [Character] kawaii iPhone case set — the cutest Y2K phone accessory you'll ever own! ✨"]

[PARAGRAPH 1 — AESTHETIC & DESIRE — 3-4 sentences. Embrace the full emotional fantasy. Name the character. Reference the aesthetic (Y2K, kawaii, coquette). Use vivid, desire-creating language. MUST include: "kawaii phone case", "[character] case", "Y2K aesthetic", "cute iPhone case" or synonyms woven in naturally. End with a reason to buy it as a gift or treat.]

[PARAGRAPH 2 — PRODUCT UNIQUENESS — 3-4 sentences. Start with something like "This isn't just a phone case — it's a complete [character] experience." Describe the actual decal/artwork visible on the case: character design, colors, any special print details (glitter, 3D elements, clear back, MagSafe ring if visible). Mention the soft TPU/silicone material and how the clear back lets the phone's color complement the artwork. MUST include at least 2 of: "clear iPhone case", "silicone phone case", "[character] design", "cute phone case", "kawaii [character]".]

[IF GRIP VISIBLE — PARAGRAPH 3: Start with something like "The absolute star of the show is the attachable [grip name]..." Describe the grip in vivid detail: exact shape (pear, bunny, strawberry, etc.), any liquid shaker effect and what floats inside, the character theming. Explain it is removable and compatible with standard PopSocket mounts. MUST include: "[shape] grip", "phone grip", "popsocket".]

[IF CHARM VISIBLE — PARAGRAPH 4: Describe the beaded charm in detail: bead colors, any pendant character or decorative element, how it attaches to the case loop. Explain it functions as a wristlet strap. MUST include: "beaded charm", "phone wristlet" or "wristlet charm", "beaded strap".]

✨ Key Features

[BULLET LIST — EXACTLY 5–7 bullets. Only features CONFIRMED VISIBLE in the images. Zero fabrication.
Format STRICTLY as: "Feature Name: One full descriptive sentence with natural keyword integration."
Each bullet MUST be on its own line with a blank line between bullets for readability.

REQUIRED bullets (include these when applicable):
• [Character] Kawaii Design: [Describe the specific artwork — character name, color, pose or expression, any special print detail visible on the case back.]
• Soft TPU Silicone Protection: Flexible, shock-absorbent silicone body provides excellent drop protection while keeping your phone ultra-lightweight and easy to grip.
• Raised Edge Bezels: Slightly elevated lip around the screen and camera module protects against face-down scratches and drops.
• Precise Cutouts: Perfectly fitted openings for all buttons, speakers, charging port, and camera — no signal interference, no fumbling.
IF MAGSAFE VISIBLE → • MagSafe Compatible: Features a built-in white magnetic ring for seamless MagSafe charging and full compatibility with all MagSafe accessories.
IF GRIP VISIBLE    → • [Shape] [Grip Name]: [Describe in full detail — shape, color, shaker liquid effect if present, what floats inside, character theming. State it is removable and PopSocket-compatible.]
IF CHARM VISIBLE   → • Hand-Beaded Wristlet Charm: [Describe bead colors, pendant, arrangement. State it attaches to the case loop and functions as a secure wristlet strap.]
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
□ All [BRACKET] placeholders replaced with actual product content from the images
□ Grip paragraph present IF grip is visible in images
□ Charm paragraph present IF charm is visible in images
□ Key Features: 5–7 bullets, each on its own line with blank line between
□ Device Compatibility: each series on its own paragraph with blank line between
□ What's Included: each bundle option on its own line with blank line between
□ Total word count ≥ 500 words

═══════════════════════════════════════
STEP 4 — TAGS (EXACTLY 13 — RESEARCH-VERIFIED SEO INTENSITY)
═══════════════════════════════════════

CRITICAL RULES:
- Exactly 13 tags. Not 12. Not 14. Exactly 13.
- Each tag: maximum 20 characters INCLUDING spaces.
- All lowercase only. Real search terms buyers type. No punctuation except hyphens.
- Every tag must be directly relevant to THIS specific product in the images.

TAG STRATEGY — 5 research-verified tiers (fill in order):

TIER 1 — BRAND IDENTITY (always include BOTH — mandatory, fill first):
  These are forced into every listing to build shop authority.
  [Brand tags will be provided in the user prompt — use them exactly as given]

TIER 2 — HIGHEST VOLUME UNIVERSAL TAGS (include ALL 4 — non-negotiable):
  These are verified high-search-volume terms for this exact product category:
  → "kawaii phone case"      (1,600+ monthly Etsy searches, difficulty 49/100 — EXACT match required)
  → "cute iphone case"       (9,900+ monthly Etsy searches — highest-volume phone case term)
  → "y2k phone case"         (trending, high buyer intent)
  → "aesthetic phone case"   (broad reach, 20 chars exactly ✓)

TIER 3 — CHARACTER + PRODUCT SPECIFIC (2 tags from what you see in images):
  → "[character name] case"   e.g. "rilakkuma case", "bunny iphone case", "dog iphone case"
  → "[character name] gift"   e.g. "bunny phone gift", "kawaii dog gift"
  IF MagSafe confirmed: replace one with → "magsafe iphone case" (19 chars ✓)

TIER 4 — iPHONE MODEL EXACT-MATCH (exactly 2 tags — highest-converting search terms):
  → "iphone 17 case"          (14 chars ✓ — newest model, highest search intent)
  → "iphone 16 pro max"       (17 chars ✓ — second most searched model tag)

TIER 5 — ACCESSORY + BUYER INTENT (fill remaining 3 slots with the best matching options):
  Use ONLY tags for accessories that are CONFIRMED VISIBLE in images:
  IF charm visible  → "beaded phone charm"   (18 chars ✓)
  IF charm visible  → "phone wristlet"       (14 chars ✓)
  IF grip visible   → "phone grip kawaii"    (17 chars ✓)
  Always eligible   → "kawaii iphone case"   (18 chars ✓ — high-converting variant of tier 2)
  Always eligible   → "kawaii gift for her"  (19 chars ✓ — top gift search phrase on Etsy)
  Always eligible   → "cute gift for her"    (17 chars ✓ — high-converting gift intent tag)

SELECTION PROCESS:
1. TIER 1: 2 brand tags (mandatory — from user prompt)
2. TIER 2: all 4 universal tags (mandatory)
3. TIER 3: 2 character/product tags from images
4. TIER 4: 2 exact iPhone model tags
5. TIER 5: best 3 accessory+intent tags based on confirmed visible accessories
= Total: 2+4+2+2+3 = EXACTLY 13 tags ✓

VERIFICATION: Count every tag. Measure every tag ≤ 20 chars. Total must = 13.

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


def _build_user_prompt(meta: ProductMeta, brand_tags: list[str] | None = None) -> str:
    lines: list[str] = [
        "Analyze the images of this phone case product and generate an SEO-optimized Etsy listing.",
        "",
        "=== PRODUCT FACTS (use these as additional context) ===",
        f"Shop: {meta.extra_notes or 'Y2KASEshop'} (HK seller, production partner: Shenzhen Mumusan Technology)",
        f"Product type: Kawaii Y2K phone case (possibly with accessories)",
        f"Material: Silicone",
    ]

    if brand_tags:
        lines.append(
            f"BRAND IDENTITY TAGS (include BOTH in your tags output, exactly as written): "
            + ", ".join(f'"{t}"' for t in brand_tags)
        )

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


def _parse_response(raw: str, meta: ProductMeta, brand_tags: list[str] | None = None) -> GeneratedCopy:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI returned non-JSON: {raw[:200]}") from exc

    title = str(data.get("title", "")).strip()

    # Enforce 140-char limit — truncate at word boundary if AI exceeded it
    if len(title) > 140:
        title = title[:140].rsplit(" ", 1)[0].rstrip(",").strip()
        log.info("Title truncated to %d chars: %s", len(title), title[:60])
    description = str(data.get("description", "")).strip()
    raw_tags = data.get("tags", [])

    if not isinstance(raw_tags, list):
        raw_tags = re.split(r"[,\n]", str(raw_tags))

    tags = [_clean_tag(t) for t in raw_tags if str(t).strip()]
    tags = [t for t in tags if t][:13]
    tags = _ensure_shop_tags(tags, brand_tags or [])

    # Validate colors against Etsy allowed list
    primary_color = _validate_color(data.get("primary_color", ""))
    secondary_color = _validate_color(data.get("secondary_color", ""))

    # Parse style image mapping — each style maps to a LIST of 1-based image indices
    raw_mapping = data.get("style_image_mapping", {})
    style_image_mapping: dict[str, list[int]] = {}
    valid_styles = {
        "Case+Grip+Charm", "Case+Grip", "Case+Charm",
        "Case Only", "Case Only (edge)", "Grip Only", "Charm Only",
    }
    if isinstance(raw_mapping, dict):
        for style, val in raw_mapping.items():
            if style not in valid_styles:
                continue
            if style in ("Charm Only", "Grip Only"):
                style_image_mapping[style] = []  # always empty
                continue
            # Accept both list and single int from AI
            if val is None or val == [] or str(val).lower() in ("null", "none", ""):
                style_image_mapping[style] = []
            elif isinstance(val, list):
                indices = []
                for v in val:
                    try:
                        indices.append(int(v))
                    except (ValueError, TypeError):
                        pass
                style_image_mapping[style] = indices
            else:
                try:
                    style_image_mapping[style] = [int(val)]
                except (ValueError, TypeError):
                    style_image_mapping[style] = []
    # Ensure all 6 styles are present
    for s in valid_styles:
        style_image_mapping.setdefault(s, [])
    # Charm Only and Grip Only are always empty
    style_image_mapping["Charm Only"] = []
    style_image_mapping["Grip Only"] = []

    mapped = {k: v for k, v in style_image_mapping.items() if v}
    log.info("Style image mapping: %s", mapped)

    # Parse image_analysis — structured per-image facts for style linking
    raw_analysis = data.get("image_analysis", [])
    image_analysis: list[dict] = []
    if isinstance(raw_analysis, list):
        for item in raw_analysis:
            if not isinstance(item, dict):
                continue
            try:
                # Use img_desc (not description) to avoid shadowing the listing description variable
                img_desc = str(item.get("description", "")).strip()
                has_grip = bool(item.get("has_grip", False))
                has_charm = bool(item.get("has_charm", False))

                # ── Code-level validation: AUTO-CORRECT booleans against description ──
                # AI sometimes writes "charm dangles" in description but sets has_charm=false.
                # We trust the description (chain-of-thought output) over the boolean.
                desc_lower = img_desc.lower()

                charm_keywords = (
                    "charm", "dangling", "dangle", "lanyard", "beads", "beaded",
                    "strap hanging", "hanging strap", "string", "cord", "tassel",
                    "wristlet", "pendant",
                )
                no_charm_phrases = (
                    "no charm", "no dangling", "no lanyard", "no beads",
                    "no strap", "no string", "no hanging", "without charm",
                    "without dangling", "without lanyard",
                )
                grip_keywords = (
                    "grip", "popsocket", "pop socket", "pop-socket",
                    "phone holder", "ring holder", "finger ring",
                    "pear-shaped", "shaker grip",
                )
                no_grip_phrases = (
                    "no grip", "no popsocket", "no holder", "no socket",
                    "without grip", "bare back", "clean back",
                )

                # Charm validation
                if any(p in desc_lower for p in no_charm_phrases):
                    if has_charm:
                        log.info("Image %s: description says no charm; correcting has_charm→False",
                                 item.get("index"))
                        has_charm = False
                elif any(k in desc_lower for k in charm_keywords):
                    if not has_charm:
                        log.info("Image %s: description mentions charm; correcting has_charm→True",
                                 item.get("index"))
                        has_charm = True

                # Grip validation
                if any(p in desc_lower for p in no_grip_phrases):
                    if has_grip:
                        log.info("Image %s: description says no grip; correcting has_grip→False",
                                 item.get("index"))
                        has_grip = False
                elif any(k in desc_lower for k in grip_keywords):
                    if not has_grip:
                        log.info("Image %s: description mentions grip; correcting has_grip→True",
                                 item.get("index"))
                        has_grip = True

                image_analysis.append({
                    "index": int(item.get("index", 0)),
                    "description": img_desc,
                    "has_grip": has_grip,
                    "has_charm": has_charm,
                    "has_case": bool(item.get("has_case", True)),
                    "is_edge_or_profile": bool(item.get("is_edge_or_profile", False)),
                    "is_held_in_hand": bool(item.get("is_held_in_hand", False)),
                    "shows_back_of_case": bool(item.get("shows_back_of_case", False)),
                    "thumbnail_quality": int(item.get("thumbnail_quality", 5)),
                })
            except (ValueError, TypeError):
                pass
    if image_analysis:
        log.info("Image analysis: %d images analyzed (with description-validated facts)",
                 len(image_analysis))

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
        style_image_mapping=style_image_mapping,
        image_analysis=image_analysis,
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
    """Always include brand identity tags; replace excess if needed."""
    required = [t[:20] for t in brand_tags if t] or ["y2kaseshop", "y2kase"]
    tag_set = set(tags)
    result = list(tags)
    for req in required:
        if req not in tag_set and len(result) < 13:
            result.append(req)
            tag_set.add(req)
        elif req not in tag_set and len(result) >= 13:
            result[-1] = req
    return result[:13]
