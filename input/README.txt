DROP YOUR PRODUCT FOLDERS HERE
================================

Each subfolder = one product listing.

Folder structure
----------------
input/
  1/
    1.PNG          ← thumbnail (always first)
    2.PNG
    3.PNG
    ...
    2.mp4          ← product video (optional)
    meta.json      ← listing config (price, SKU, phone models, etc.)
  2/
    1.PNG
    ...
    meta.json
  3/
    ...

Rules
-----
- Name images with plain numbers: 1.PNG, 2.PNG, 3.PNG, ...
- Image 1 is ALWAYS the thumbnail.
- Images are shown in the listing in the exact order you numbered them.
- Include one .mp4 video per folder (optional but recommended).
- Every folder must have a meta.json — copy one from the Samples folder as a template.

Running the pipeline
--------------------
  python run.py

The pipeline will:
  1. Load all product folders from this input/ directory.
  2. Upload images to Cloudinary (idempotent — safe to re-run).
  3. Generate AI titles, descriptions, and tags via OpenAI.
  4. Write the final XLSX to the output/ folder.
  5. Clean up old XLSX files from output/ automatically.
