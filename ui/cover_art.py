import io
import httpx
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import logging
from models import TrackMeta
from config import COVER_ART_URL, COVERS_DIR

logger = logging.getLogger(__name__)

COVER_SIZE = (512, 512)


async def generate_cover(track: TrackMeta) -> str | None:
    """Generate cover art. Returns relative filename or None."""
    cover_path = COVERS_DIR / f"{track.id}.png"

    # Try local Juggernaut XL service first
    try:
        result = await _local_cover(track, cover_path)
        if result:
            return f"{track.id}.png"
    except Exception as e:
        logger.warning(f"Cover art service failed for {track.id}: {e}")

    # Pillow fallback — always succeeds
    try:
        _pillow_cover(track, cover_path)
        return f"{track.id}.png"
    except Exception as e:
        logger.error(f"Pillow fallback failed for {track.id}: {e}")
        return None


async def _local_cover(track: TrackMeta, cover_path: Path) -> bool:
    """Call the local cover art service on ROG-STRIX."""
    genre = track.genre_hint or "music"
    prompt = (
        f"Album cover art for a {genre} song titled '{track.title}', "
        f"{track.description[:80]}, artistic, music album cover, "
        f"no text, no words, no letters, no watermark"
    )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{COVER_ART_URL}/generate",
            json={
                "prompt": prompt,
                "steps": 25,
                "guidance_scale": 7.0,
                "width": 512,
                "height": 512,
            },
        )
        resp.raise_for_status()

        img = Image.open(io.BytesIO(resp.content))
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(cover_path, "PNG")

        elapsed = resp.headers.get("X-Elapsed", "?")
        logger.info(f"AI cover art saved for {track.id} ({elapsed}s)")
        return True


def _pillow_cover(track: TrackMeta, cover_path: Path) -> None:
    """Generate a gradient cover with title text as fallback."""
    width, height = COVER_SIZE
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Gradient based on track id hash
    h = hash(track.id) % 360
    from colorsys import hsv_to_rgb
    r1, g1, b1 = [int(c * 255) for c in hsv_to_rgb(h / 360, 0.7, 0.4)]
    r2, g2, b2 = [int(c * 255) for c in hsv_to_rgb((h + 60) / 360, 0.8, 0.8)]

    for y in range(height):
        t = y / height
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    title = track.title[:30]

    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
    except OSError:
        font_large = ImageFont.load_default()
        font_small = font_large

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    ov_draw.rectangle([(0, height - 160), (width, height)], fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.text((width // 2, height - 120), title, font=font_large, fill="white", anchor="mm")
    draw.text((width // 2, height - 60), track.genre_hint or "music", font=font_small, fill=(200, 200, 200), anchor="mm")

    cover_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(cover_path, "PNG")
