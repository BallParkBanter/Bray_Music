"""Cover art generation micro-service for Bray Music Studio.

Runs on the host (ROG-STRIX) at port 7863. Uses Juggernaut XL (SDXL) on the
local GTX 1080 Ti to generate album cover art from text prompts.

After each generation the process exits so systemd restarts it with a clean
CUDA context. This is necessary because torch.cuda.empty_cache() does not
release VRAM visible to other processes (ACE-Step needs the full 11 GB).

Install: pip install fastapi uvicorn diffusers transformers accelerate
Run: uvicorn cover_art_service:app --host 0.0.0.0 --port 7863
"""

import io
import logging
import os
import signal
import time

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Cover Art Service")

MODEL_ID = "RunDiffusion/Juggernaut-XL-v9"


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    negative_prompt: str = "text, watermark, logo, words, letters, signature, blurry, low quality, deformed"
    steps: int = Field(default=25, ge=1, le=50)
    guidance_scale: float = Field(default=7.0, ge=1.0, le=20.0)
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    seed: int = Field(default=-1)


@app.post("/generate")
async def generate(req: GenerateRequest):
    from diffusers import StableDiffusionXLPipeline

    logger.info("Loading Juggernaut XL (fp16)...")
    try:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float16,
            use_safetensors=True,
            variant="fp16",
        )
        pipe = pipe.to("cuda")
        pipe.set_progress_bar_config(disable=True)
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        raise HTTPException(status_code=500, detail=f"Model load failed: {e}")

    seed = req.seed if req.seed >= 0 else int(torch.randint(0, 2**32, (1,)).item())
    generator = torch.Generator(device="cuda").manual_seed(seed)

    t0 = time.time()
    try:
        result = pipe(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt,
            num_inference_steps=req.steps,
            guidance_scale=req.guidance_scale,
            width=req.width,
            height=req.height,
            generator=generator,
        )
        image = result.images[0]
    except torch.cuda.OutOfMemoryError:
        logger.error("GPU OOM during generation")
        raise HTTPException(status_code=503, detail="GPU out of memory")
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    elapsed = time.time() - t0
    logger.info(f"Generated {req.width}x{req.height} in {elapsed:.1f}s (seed={seed})")

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    content = buf.getvalue()

    # Schedule process exit after response is sent so systemd restarts us
    # with a clean CUDA context (empty_cache doesn't free VRAM cross-process)
    def _exit_soon():
        time.sleep(1)
        logger.info("Exiting to release CUDA context for ACE-Step")
        os.kill(os.getpid(), signal.SIGTERM)

    import threading
    threading.Thread(target=_exit_soon, daemon=True).start()

    return Response(
        content=content,
        media_type="image/png",
        headers={"X-Seed": str(seed), "X-Elapsed": f"{elapsed:.1f}"},
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
    }
