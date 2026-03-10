import io
import random
import httpx
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import logging
from models import TrackMeta
from config import COVER_ART_URL, COVERS_DIR, OLLAMA_URL

logger = logging.getLogger(__name__)

COVER_SIZE = (512, 512)


async def _generate_visual_description(description: str, genre: str) -> str | None:
    """Use Ollama to transform a song description into a visual scene for cover art."""
    prompt = (
        f"I need a visual scene description for album cover art. "
        f"The song is: {description}. Genre: {genre}. "
        f"Describe a vivid visual SCENE (not music) that captures the mood and subject. "
        f"Focus on imagery: objects, settings, lighting, colors, atmosphere. "
        f"Be original — avoid cliches like 'dust motes dance', 'bathed in golden light', "
        f"'rays of light stream through', 'bathed in amber glow'. Find fresh, unexpected imagery. "
        f"Do NOT mention music, songs, albums, or audio. "
        f"Reply with ONLY the visual description in one sentence, under 40 words."
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": "gemma3:12b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 80, "temperature": 0.9},
                },
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            # Strip any thinking tags
            if "</think>" in text:
                text = text.split("</think>")[-1].strip()
            if text:
                logger.info(f"Ollama visual description: {text}")
                return text
    except Exception as e:
        logger.warning(f"Ollama visual description failed: {e}")
    return None


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


# Genre → visual style mapping for cover art
_GENRE_VISUAL = {
    "hip hop": "urban street art style, bold graffiti colors, gritty city atmosphere, dramatic lighting",
    "rock": "dark moody concert lighting, electric energy, raw and powerful imagery",
    "pop": "bright vibrant colors, modern clean design, glossy and polished aesthetic",
    "jazz": "smoky nightclub atmosphere, warm golden tones, sophisticated noir style",
    "classical": "elegant and refined, oil painting style, rich warm tones, timeless beauty",
    "electronic": "futuristic neon lights, cyberpunk aesthetic, glowing abstract shapes",
    "folk": "rustic natural scenery, warm earth tones, handcrafted organic feel",
    "country": "wide open landscape, sunset golden hour, rustic Americana imagery",
    "metal": "dark intense imagery, fire and steel, dramatic high contrast",
    "indie": "dreamy lo-fi photography style, muted pastel colors, artistic and contemplative",
    "ambient": "ethereal misty landscape, soft gradients, peaceful and vast atmosphere",
    "blues": "moody deep blues and warm ambers, vintage feel, soulful atmosphere",
    "reggae": "tropical vibrant colors, island sunset, laid-back warm atmosphere",
    "soul": "warm rich colors, vintage 70s aesthetic, intimate and emotional",
    "gospel": "radiant golden light, uplifting heavenly imagery, spiritual warmth",
    "ballad": "soft romantic lighting, intimate emotional scene, cinematic depth",
    "dance": "pulsing neon lights, energetic club atmosphere, dynamic motion blur",
    "latin": "passionate warm colors, fiery reds and golds, rhythmic visual energy",
    "punk": "raw DIY collage style, bold contrast, rebellious and edgy",
    "r&b": "sleek luxurious aesthetic, deep purple and gold tones, sensual mood lighting",
}

# Random art style pool — used when no genre is detected, so every cover
# gets a unique visual identity. Each style is descriptive enough for SDXL.
_ART_STYLES = [
    "retro 70s psychedelic poster art with swirling colors and kaleidoscope patterns",
    "bold graphic novel illustration with thick ink outlines and dramatic shadows",
    "Japanese ukiyo-e woodblock print with flowing lines and flat bold colors",
    "neon-soaked cyberpunk digital art with glowing edges and dark backgrounds",
    "gritty film noir photography with deep shadows and single light source",
    "abstract expressionist paint splatter with raw energy and chaotic color",
    "vintage 1960s concert poster with hand-lettered feel and acid colors",
    "dark fantasy oil painting with rich textures and mythical atmosphere",
    "minimalist geometric design with clean shapes and limited color palette",
    "oil painting with heavy visible brushstrokes and impasto texture",
    "screen-printed rock concert poster with overprint registration marks",
    "double exposure photography blending portrait with landscape",
    "stained glass mosaic with jewel tones and black leading lines",
    "charcoal sketch with dramatic contrast and smudged edges",
    "spray paint street mural on weathered brick wall",
    "faded vintage Polaroid with warm light leak and soft focus",
    "East Asian ink wash painting with flowing wet-on-wet technique",
    "Art Deco design with gold metallic accents on black background",
    "glitch art with RGB channel splitting and digital distortion",
    "Renaissance chiaroscuro with dramatic light emerging from darkness",
    "comic book halftone dots with bold primary colors and action lines",
    "brutalist concrete and steel with harsh geometry and raw texture",
    "neon sign glowing in rain-slicked darkness",
    "torn paper cut-out collage with layered textures and mixed media",
    "infrared photography with ghostly white foliage and dark skies",
    "grainy 35mm film close-up with shallow depth of field and bokeh",
    "hand-carved linocut block print with bold black and white contrast",
    "vaporwave aesthetic with pastel gradients and retro digital feel",
    "gouache illustration with flat matte colors and visible brush marks",
    "aerial drone photography with abstract patterns from above",
    "long exposure light trails streaking through urban darkness",
    "detailed woodcut engraving with fine crosshatch shading",
    "high contrast monochrome with crushed blacks and blown highlights",
    "layered stencil art with misaligned colors and rough spray edges",
    "antique wet plate photograph with dark vignette and silver tones",
    "lush botanical illustration with scientific precision and rich greens",
    "Andy Warhol style silk screen pop art with bold flat color blocks",
]


async def _local_cover(track: TrackMeta, cover_path: Path) -> bool:
    """Call the local Juggernaut XL cover art service on ROG-STRIX."""
    genre = track.genre_hint or "music"
    description = track.description or track.title

    # Use Ollama to generate a visual scene description from the song description
    visual_scene = await _generate_visual_description(description, genre)

    # Use the AI visual scene if available, otherwise fall back to the raw description
    scene = visual_scene or description

    art_style = random.choice(_ART_STYLES)
    prompt = (
        f"Album cover art: {scene}, "
        f"{art_style}, "
        f"highly detailed, beautiful composition, "
        f"no text, no words, no letters, no watermark"
    )

    logger.info(f"Cover art prompt for {track.id}: {prompt}")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{COVER_ART_URL}/generate",
            json={
                "prompt": prompt,
                "steps": 30,
                "guidance_scale": 5.0,
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
