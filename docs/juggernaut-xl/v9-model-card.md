# Juggernaut XL v9 - Model Card

Source: https://huggingface.co/RunDiffusion/Juggernaut-XL-v9

## Model Overview
- **Base Model:** stabilityai/stable-diffusion-xl-base-1.0
- **License:** CreativeML OpenRAIL-M
- **Pipeline:** StableDiffusionXLPipeline
- **VAE:** Baked in (no separate VAE needed)

## Key Features
- Specialized for photorealistic image generation
- Architecture, wildlife, car, food, interior, and landscape photography
- Cinematic and detailed photography capabilities

## Recommended Settings
- Resolution: 832x1216
- Sampler: DPM++ 2M Karras
- Steps: 30-40
- CFG Scale: 3-7 (lower = more realistic)

## Upscaling
- Model: 4xNMKD-Siax_200k
- HiRes Steps: 15
- Denoise: 0.3
- Upscale Factor: 1.5

## Recommended Keywords/Tokens
These terms are used in training and optimize results:
- Architecture Photography
- Wildlife Photography
- Car Photography
- Food Photography
- Interior Photography
- Landscape Photography
- Hyperdetailed Photography
- Cinematic Movie
- Still Mid Shot Photo
- Full Body Photo
- Skin Details

## V9 Changes
- Enhanced skin details, lighting, and contrast
- Integration with RunDiffusion Photo Model v2
- Improved photographic output quality

## Important
- Start with NO negative prompt, add only what you don't want
- Lower CFG = more realistic output
- This model is NOT permitted to be used behind API services (commercial licensing: juggernaut@rundiffusion.com)
