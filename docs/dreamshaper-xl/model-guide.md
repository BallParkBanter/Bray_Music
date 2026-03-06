# DreamShaper XL - Model Guide

Sources:
- https://civitai.com/models/112902/dreamshaper-xl
- https://huggingface.co/Lykon/dreamshaper-xl-1-0
- https://www.seaart.ai/articleDetail/cslk7fde878c73dehu2g
- https://www.deviantart.com/aipythondev/journal/Dreamshaper-XL-Extensive-Study-1131166471

## Overview

DreamShaper XL is a general-purpose SDXL model by Lykon that "aims at doing everything well — photos, art, anime, manga." Unlike Juggernaut XL (photorealism-focused), DreamShaper balances realism with fantasy and illustration styles, making it ideal for album cover art.

## HuggingFace Model ID

`Lykon/dreamshaper-xl-1-0` (fp16 variant available, ~6 GB UNet)

## Key Strengths

- Crafts versatile styles with a realistic touch
- Excels at photorealistic AND 3D render type images
- Better human figure generation with refined anatomy
- Great lighting/shadow usage and depth/focus
- Recognizes diverse art and artist references
- Strong with illustration, abstract, sketching, painting styles
- Works well with single-subject images and close-up/portrait/medium shots

## Versions

| Version | Steps | CFG | Sampler | Notes |
|---------|-------|-----|---------|-------|
| **v1.0 (Standard)** | 20-40 | 6 | DPM++ 2M SDE Karras or Euler | Best quality, our choice |
| Lightning | 3-6 | 2 | DPM++ SDE Karras | Fast but lower quality |
| Turbo | 4-8 | 2 | DPM++ SDE Karras (NOT 2M) | Commercial use restricted |

**We use v1.0 (Standard)** for best quality at the cost of slightly longer generation.

## Recommended Settings for Our Use (512x512 Album Covers)

- Sampler: DPM++ 2M SDE Karras (built into diffusers as DEISMultistepScheduler)
- Steps: 25-30
- CFG Scale: 5-6
- Resolution: 512x512 (within the safe range, avoid going far above 1024)
- No refiner needed

## Prompting Best Practices

### Prompt Structure (Ordered by Priority)
1. Medium/Style designation (e.g., "oil painting", "illustration")
2. Art or artist references
3. Angle/view specification
4. Subject description
5. Quality enhancement terms (8K, UHD, highly detailed)
6. Composition details
7. Lighting and shadow elements

### Tips
- First sentence is the most important — sets the foundation
- Tag-style prompts outperform long descriptions, but both work
- Using lighting, shadow, and focus terms increases realism and quality
- Long prompts generally yield superior results
- Works with SDXL-based LoRAs
- Model prefers close-up, portrait, medium range shots
- Low CFG (2-6) works well — model doesn't need heavy guidance

### Effective Keywords
- Quality: "8K, UHD, highly detailed, sharp focus"
- Lighting: "cinematic lighting, rim lighting, golden hour, volumetric light"
- Style: "oil painting, watercolor, illustration, concept art"
- Composition: "depth of field, bokeh, rule of thirds"
- Atmosphere: "moody, dramatic, ethereal, vibrant"

### Negative Prompt
"(low quality, worst quality:1.4), text, watermark, logo, words, letters, signature, blurry, deformed"

## Painting Style Capabilities (Tested)

DreamShaper XL handles these art styles well:
- Renaissance allegory and Baroque drama
- Impressionist technique and color
- Surrealism and dreamlike distortion
- Japanese ink painting
- Rococo, Mughal, Qajar historical styles
- Macro and infrared photography aesthetics
- Kirlian photography effects
- Cinematic scene framing

## Comparison with Juggernaut XL

| Aspect | DreamShaper XL | Juggernaut XL v9 |
|--------|---------------|-------------------|
| Primary strength | Balanced realism + art | Photorealism |
| Art styles | Excellent variety | Fights its training |
| Album covers | Natural fit | Too "photo-like" |
| Trigger words | Art/style terms | Photography terms |
| Human faces | Good, refined | Excellent, hyper-real |
| Fantasy/concept | Excellent | Decent |
| Training data | Mixed art + photo | Photography-heavy |
