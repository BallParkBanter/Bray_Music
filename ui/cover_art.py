import asyncio
import io
import httpx
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import logging
from models import TrackMeta
from config import NEXTCLOUD_URL, NEXTCLOUD_USER, NEXTCLOUD_PASS, COVERS_DIR

logger = logging.getLogger(__name__)

TASK_POLL_INTERVAL = 5
TASK_TIMEOUT = 600  # Visionatrix SDXL on GTX 1060 can take 5-10 min on GTX 1060
COVER_SIZE = (512, 512)


async def generate_cover(track: TrackMeta) -> str | None:
    """Generate cover art. Returns relative filename or None."""
    cover_path = COVERS_DIR / f"{track.id}.png"

    # Try Nextcloud/Visionatrix AI path first
    try:
        result = await _nextcloud_cover(track, cover_path)
        if result:
            return f"{track.id}.png"
    except Exception as e:
        logger.warning(f"Nextcloud cover failed for {track.id}: {e}")

    # Pillow fallback — always succeeds
    try:
        _pillow_cover(track, cover_path)
        return f"{track.id}.png"
    except Exception as e:
        logger.error(f"Pillow fallback failed for {track.id}: {e}")
        return None


async def _nextcloud_cover(track: TrackMeta, cover_path: Path) -> bool:
    if not NEXTCLOUD_PASS:
        raise ValueError("NEXTCLOUD_PASS not configured")

    genre = track.genre_hint or "music"
    prompt = (
        f"Album cover art for a {genre} song titled '{track.title}', "
        f"{track.description[:80]}, artistic, music album cover"
    )

    auth = (NEXTCLOUD_USER, NEXTCLOUD_PASS)
    headers = {"OCS-APIRequest": "true", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=30) as client:
        # Submit task via /schedule endpoint
        resp = await client.post(
            f"{NEXTCLOUD_URL}/ocs/v2.php/taskprocessing/schedule",
            auth=auth,
            headers={**headers, "Content-Type": "application/json"},
            json={
                "type": "core:text2image",
                "appId": "bray-music-studio",
                "input": {
                    "input": prompt,
                    "numberOfImages": 1,
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        task_id = data["ocs"]["data"]["task"]["id"]
        logger.info(f"Nextcloud task {task_id} scheduled for {track.id}")

        # Poll until done — use /task/{id} (singular)
        deadline = asyncio.get_event_loop().time() + TASK_TIMEOUT
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(TASK_POLL_INTERVAL)
            poll = await client.get(
                f"{NEXTCLOUD_URL}/ocs/v2.php/taskprocessing/task/{task_id}",
                auth=auth,
                headers=headers,
            )
            poll.raise_for_status()
            task = poll.json()["ocs"]["data"]["task"]
            status = task["status"]
            progress = task.get("progress")
            logger.debug(f"Task {task_id}: {status} (progress={progress})")

            if status == "STATUS_SUCCESSFUL":
                output = task.get("output", {})
                images = output.get("images", [])
                if images:
                    file_id = images[0]
                    # Download via task file endpoint
                    img_resp = await client.get(
                        f"{NEXTCLOUD_URL}/ocs/v2.php/taskprocessing/tasks/{task_id}/file/{file_id}",
                        auth=auth,
                        headers={"OCS-APIRequest": "true"},
                        timeout=30,
                    )
                    img_resp.raise_for_status()

                    # Resize to 512x512 (SDXL outputs 832x1216)
                    img = Image.open(io.BytesIO(img_resp.content))
                    img = img.resize(COVER_SIZE, Image.LANCZOS)

                    cover_path.parent.mkdir(parents=True, exist_ok=True)
                    img.save(cover_path, "PNG")
                    logger.info(f"AI cover art saved for {track.id}: {cover_path}")
                    return True
                raise ValueError("No images in task output")
            elif status in ("STATUS_FAILED", "STATUS_CANCELLED"):
                raise RuntimeError(f"Task failed with status {status}")

        raise TimeoutError(f"Cover art task {task_id} timed out after {TASK_TIMEOUT}s")


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
