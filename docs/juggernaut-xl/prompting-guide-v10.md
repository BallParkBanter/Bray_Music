# Prompt Guide for Juggernaut X

Source: https://learn.rundiffusion.com/prompting-guide-for-juggernaut-x/

## Overview
"Juggernaut X is tailored for professionals who demand precise control over image generation." This model requires detailed, specific prompts with explicit trigger words for optimal results.

## Key Trigger Words
- **Skin Textures** - for detailed human/animal depictions
- **High Resolution** (three variants: "High Resolution," "High-Resolution," "High-Resolution Image")
- **Cinematic** - for dynamic, film-like narratives

## Prompt Structure Components (13 Elements)

1. **Subject** - Primary focus (e.g., "Renaissance noblewoman")
2. **Action** - What the subject is doing ("holding an ancient book")
3. **Environment/Setting** - Background context
4. **Object** - Secondary items enhancing the scene
5. **Color** - Dominant color schemes ("deep red and gold")
6. **Style** - Artistic approach ("reminiscent of Vermeer's lighting")
7. **Mood/Atmosphere** - Emotional quality ("serene," "mysterious")
8. **Lighting** - Specific conditions ("soft natural window light")
9. **Perspective/Viewpoint** - Camera angle or vantage point
10. **Texture/Material** - Prominent surface qualities
11. **Time Period** - Historical era or temporal setting
12. **Cultural Elements** - Tradition-specific references
13. **Emotion** - Expressed feelings if applicable

## Recommended Settings

### Standard Models (NSFW/SAFE)
- Sampling Method: DPM++ 2m Karras
- Steps: 30-40
- CFG: 6-7
- Resolution: 1024x1024, 832x1216, 1216x832
- Token limit: 75 maximum
- Suggested negative prompt: "Naked, Nude, fake eyes, deformed eyes, bad eyes, cgi, 3D, digital, airbrushed"

### Hyper Model
- Sampling Method: DPM++ SDE
- Steps: 4-6 (recommend 6)
- CFG: 1-2 (recommend 2)
- No negative prompts
- Use more descriptive tags than standard model

### Upscaling (Hires. Fix)
- Denoising Strength: 0.25-0.32
- Upscaler: 4x_NMKD-Siax_200k
- Steps: 0-20
- Scale: 1.5-2x

## Text Generation
"Juggernaut has the ability to generate text, though accuracy decreases with sentence length and complexity." Use short, clear phrases in quotes.

## Token Limit
Try not to exceed 75 tokens, as exceeding this reduces prompt adherence. The first sentence of the prompt is the most important.
