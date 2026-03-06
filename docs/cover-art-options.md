# Cover Art Generation — Model Options

This document captures research on improving album cover art quality for Bray Music Studio.

## Current Setup (as of 2026-03-06)

- **Model:** DreamShaper XL v1.0 (`Lykon/dreamshaper-xl-1-0`)
- **Hardware:** GTX 1080 Ti (11 GB), ROG-STRIX
- **Service:** `cover-art-service.service` on port 7863
- **Settings:** 25-30 steps, CFG 5-6, 512x512, fp16
- **Generation time:** ~27s per image (warm), ~35s cold

Previously used Juggernaut XL v9, which was photorealism-focused and produced bland album covers.

## Option 1: DreamShaper XL (IMPLEMENTED)

**Model:** `Lykon/dreamshaper-xl-1-0`
**Why:** Balances realism with art/illustration styles. Handles oil painting, watercolor, abstract, fantasy — all things that make great album covers. Juggernaut XL kept defaulting to "nice photo" aesthetic.

**Prompt strategy:**
- Genre-detected songs get genre-specific visual styles (hip hop → street art, jazz → smoky nightclub, etc.)
- Unknown genre songs get the song description + a randomly selected art style from a pool of 37 diverse styles
- Every cover looks unique because of the random style selection

**Docs:** See `docs/dreamshaper-xl/model-guide.md`

## Option 2: Album Cover LoRA (FUTURE)

Layer a specialized LoRA on top of DreamShaper XL for even more album-cover-specific output.

### Best Album Cover Design LoRA
- **Source:** https://civitai.com/models/324660/best-album-cover-design
- **Type:** LyCORIS (LoCon), 782 MB
- **Trigger words:** "Album cover designs", "Best Design Art"
- **Strength:** 0.5-0.8
- **Training data:** Artvinyl.com award winners + iconic covers
- **Best genres:** Metal, indie, surrealist compositions
- **Negative prompt addition:** "Bad Design"

### Top 100 Album Covers LoRA
- **Source:** https://civitai.com/models/8336/top-100-album-covers
- **Training:** Rolling Stone Magazine's top 100 album covers
- **Style:** Iconic, classic album art aesthetics

### Other Album LoRAs
- Electric Art LoRA (https://civitai.com/models/749683) — electronic music covers
- Synthwave Style LoRA (https://civitai.com/models/1463207) — retrofuturistic neon
- Designers Republic LoRA (https://civitai.com/models/22716) — trained on 873 covers

### How to Add a LoRA
Would require changes to `cover_art_service.py`:
```python
from diffusers import StableDiffusionXLPipeline

pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_ID, ...)
pipe.load_lora_weights("path/to/album_cover_lora.safetensors")
pipe.fuse_lora(lora_scale=0.7)
```

## Option 3: Better Prompting with Current Model (PARTIALLY IMPLEMENTED)

Even without switching models or adding LoRAs, we improved prompts:

### What we changed
- Use song description in the image prompt (not just title)
- Genre-specific visual style mappings (20 genres)
- Random art style pool (37 styles) for unknown genres
- Added "no text, no words, no letters, no watermark" to all prompts

### What could be improved further
- Use Juggernaut/SDXL weight syntax `(style:1.3)` to force artistic styles
- Add quality tokens: "8K, UHD, highly detailed, sharp focus"
- Tune CFG scale per style (lower for realism, higher for stylized)
- Use negative prompts more aggressively: "(low quality, worst quality:1.4)"

## Model Comparison

| Model | Strength | Album Cover Fit | VRAM | Notes |
|-------|----------|----------------|------|-------|
| Juggernaut XL v9 | Photorealism | Poor — too "photo-like" | ~7 GB | Our previous model |
| DreamShaper XL v1.0 | Art + Realism balance | Good — versatile styles | ~7 GB | Current model |
| DreamShaper XL + LoRA | Art + album-specific | Best — trained on real covers | ~7-8 GB | Future option |
| Midjourney v6 | Artistic cohesion | Excellent | Cloud only | Not self-hosted |
| DALL-E 3 | Prompt adherence | Good | Cloud only | Not self-hosted |

## References

- Juggernaut XL docs: `docs/juggernaut-xl/`
- DreamShaper XL docs: `docs/dreamshaper-xl/`
- Cover art service: `cover_art_service.py`
- Cover art client: `ui/cover_art.py`
