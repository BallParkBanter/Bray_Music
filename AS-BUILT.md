# Bray Music Studio — As-Built System Documentation

**Document version:** 2026-03-04
**System deployed:** 2026-03-04
**Host:** bobray-ROG-STRIX (192.168.1.153)
**Public URL:** https://music.apps.bray.house
**Library URL:** https://music.apps.bray.house/library

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Infrastructure](#2-infrastructure)
3. [ACE-Step 1.5](#3-ace-step-15)
4. [UI Container](#4-ui-container)
5. [Parameter Mapping](#5-parameter-mapping)
6. [Cover Art Pipeline](#6-cover-art-pipeline)
7. [Frontend Architecture](#7-frontend-architecture)
8. [Networking](#8-networking)
9. [Known Issues and Considerations](#9-known-issues-and-considerations)
10. [Testing](#10-testing)
11. [Operations](#11-operations)
12. [File Inventory](#12-file-inventory)

---

## 1. System Overview

Bray Music Studio is a self-hosted, AI-powered music generation web application. It provides a Suno-style user interface that wraps the ACE-Step 1.5 music generation model, allowing users to describe a song in natural language and receive a fully generated FLAC audio file with AI-generated cover art.

### Architecture Diagram (Text)

```
                    Internet
                       |
                       v
              *.apps.bray.house
            (SSL via NPM, host 37)
                       |
                       v
        +----------------------------+
        |    bray-music-ui (Docker)  |
        |    FastAPI :7861           |
        |    UI, API, history,       |
        |    cover art orchestration |
        +----------------------------+
           |                    |
           v                    v
  +------------------+   +-----------------------------+
  | ACE-Step 1.5     |   | Nextcloud Task Processing   |
  | (native, systemd)|   | (BrayNextcloudServer)       |
  | Gradio :7860     |   | core:text2image             |
  | GTX 1080 Ti GPU  |   | Visionatrix SDXL            |
  +------------------+   +-----------------------------+
```

### Data Flow

1. User describes a song in the web UI (Simple or Custom mode)
2. UI container sends parameters to ACE-Step's Gradio API via `host.docker.internal:7860`
3. ACE-Step generates audio on the GTX 1080 Ti GPU (60-120 seconds)
4. UI container downloads the FLAC file from Gradio's file server to the shared volume
5. Track metadata is saved to `history.json`
6. In the background, cover art is requested from Nextcloud's Task Processing API (Visionatrix SDXL on BrayNextcloudServer)
7. If Nextcloud/Visionatrix fails, a Pillow gradient+text fallback cover is generated

---

## 2. Infrastructure

### Host Machine: bobray-ROG-STRIX

| Property | Value |
|----------|-------|
| IP Address | 192.168.1.153 |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.17.0-14-generic |
| CPU | AMD Ryzen 7 5700G with Radeon Graphics (8 cores / 16 threads) |
| RAM | 14 GiB physical + 19 GiB swap |
| GPU | NVIDIA GeForce GTX 1080 Ti (11264 MiB VRAM) |
| GPU Architecture | Pascal (sm_61) |
| NVIDIA Driver | 580.126.09 |
| CUDA Version | 13.0 (as reported by nvidia-smi) |
| Docker | 28.2.2, build 28.2.2-0ubuntu1~24.04.1 |
| NVIDIA Container Toolkit | Installed (2026-03-02) |

**CRITICAL:** Do NOT upgrade the NVIDIA driver past nvidia-580. The nvidia-590 series dropped Pascal (sm_61) support. The GTX 1080 Ti will not function with nvidia-590+.

### GPU Memory Utilization (Typical)

When ACE-Step is loaded and idle, the GPU uses approximately 1900-2400 MiB. During generation, usage peaks near 4-6 GiB. Desktop compositing (GNOME Shell, Xwayland, gnome-remote-desktop) uses an additional ~480 MiB.

---

## 3. ACE-Step 1.5

### Installation

ACE-Step 1.5 is installed natively (not in Docker) on ROG-STRIX.

| Property | Value |
|----------|-------|
| Installation path | `/home/bobray/ACE-Step-1.5/` |
| Python version | 3.12 (managed via uv) |
| Virtual environment | `/home/bobray/ACE-Step-1.5/.venv/` |
| Package manager | uv (at `/home/bobray/.local/bin/uv`) |
| Gradio version | 6.2.0 |
| Listening address | `0.0.0.0:7860` |

### PyTorch Version and CUDA Pin

The `pyproject.toml` pins PyTorch to **cu124** (CUDA 12.4):

```
"torch==2.6.0+cu124",
"torchvision==0.21.0+cu124",
"torchaudio==2.6.0+cu124",
```

This is critical because the default cu128 build dropped support for Pascal's sm_61 compute capability. The cu124 build is the last PyTorch wheel set that includes sm_61 kernels.

The PyTorch index is configured in `pyproject.toml`:

```toml
[[tool.uv.index]]
name = "pytorch-cu124"
url = "https://download.pytorch.org/whl/cu124"
explicit = true
```

### Environment Configuration

File: `/home/bobray/ACE-Step-1.5/.env`

```
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B
ACESTEP_LM_BACKEND=pt
ACESTEP_DEVICE=auto
ACESTEP_INIT_LLM=auto
SERVER_NAME=0.0.0.0
PORT=7860
```

| Variable | Purpose |
|----------|---------|
| `ACESTEP_CONFIG_PATH` | DiT model checkpoint to use. `acestep-v15-turbo` = turbo variant (8 inference steps instead of 32) |
| `ACESTEP_LM_MODEL_PATH` | Language model for lyric/caption generation. `acestep-5Hz-lm-0.6B` = 0.6B parameter model (smallest, fits on 11 GB) |
| `ACESTEP_LM_BACKEND` | `pt` = PyTorch backend (vs. `vllm` which requires newer GPU) |
| `ACESTEP_DEVICE` | `auto` = auto-detect GPU |
| `ACESTEP_INIT_LLM` | `auto` = load LLM when first needed |
| `SERVER_NAME` | Bind to all interfaces |
| `PORT` | Gradio server port |

### GPU Tier 4 Auto-Configuration

ACE-Step's internal GPU tier system classifies the GTX 1080 Ti as **Tier 4** (Pascal GPUs). This auto-configures:

- **DiT inference steps:** 8 (turbo mode, instead of 32 for base)
- **Language model:** 0.6B parameters (with PyTorch backend)
- **Quantization:** INT8
- **Attention:** SDPA (Scaled Dot-Product Attention)
- **Offloading:** CPU + DiT offload enabled (model components shuttle between CPU and GPU RAM)

No manual patches are needed. The GPU tier system handles Pascal limitations automatically. The only required fix was the cu124 PyTorch pin.

### systemd Service

File: `/etc/systemd/system/acestep.service`

```ini
[Unit]
Description=ACE-Step 1.5 Music Generation Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bobray
Group=bobray
WorkingDirectory=/home/bobray/ACE-Step-1.5
EnvironmentFile=/home/bobray/ACE-Step-1.5/.env
ExecStart=/home/bobray/.local/bin/uv run acestep --server-name 0.0.0.0 --port 7860 --init_service true
Restart=on-failure
RestartSec=10
TimeoutStartSec=300
StandardOutput=journal
StandardError=journal
SyslogIdentifier=acestep
SupplementaryGroups=video render
LimitNOFILE=65536
LimitMEMLOCK=infinity

[Install]
WantedBy=multi-user.target
```

Key details:
- **`--init_service true`**: Pre-loads models at startup rather than on first request
- **`TimeoutStartSec=300`**: 5-minute startup timeout (model loading takes 2-3 minutes)
- **`SupplementaryGroups=video render`**: Required for GPU device access
- **`LimitMEMLOCK=infinity`**: Required for CUDA memory-mapped operations
- **Enabled at boot**: `WantedBy=multi-user.target`
- **Process tree**: `uv` spawns the Python process, which spawns 16 `torch._inductor/compile_worker` threads
- **Memory usage**: ~11.2 GiB RAM + 8.7 GiB swap (peak 12.5 GiB RAM)

### Model Checkpoints

All models are stored in `/home/bobray/ACE-Step-1.5/checkpoints/`:

| Directory | Size | Purpose |
|-----------|------|---------|
| `acestep-v15-turbo/` | 4.5 GB | **Active** DiT turbo model (8 steps) |
| `acestep-v15-base/` | 4.5 GB | Base DiT model (32 steps, not used) |
| `acestep-v15-sft/` | 4.5 GB | SFT fine-tuned DiT (not used) |
| `acestep-v15-turbo-shift1/` | 4.5 GB | Turbo shift1 variant (not used) |
| `acestep-v15-turbo-shift3/` | 4.5 GB | Turbo shift3 variant (not used) |
| `acestep-v15-turbo-continuous/` | 4.5 GB | Turbo continuous variant (not used) |
| `acestep-5Hz-lm-0.6B/` | 1.3 GB | **Active** 0.6B language model |
| `acestep-5Hz-lm-1.7B/` | 3.5 GB | 1.7B language model (not used) |
| `acestep-5Hz-lm-4B/` | 7.9 GB | 4B language model (not used, too large for Pascal) |
| `Qwen3-Embedding-0.6B/` | 1.2 GB | Embedding model for semantic features |
| `vae/` | 322 MB | VAE decoder |

Total checkpoint storage: ~37.8 GB

### Gradio API Details

The ACE-Step Gradio API endpoint is:

```
POST /gradio_api/call/generation_wrapper
```

**Important discovery:** The `/gradio_api/info` endpoint reports 50 named parameters (indices 0-49). However, the actual handler has **55 inputs** due to hidden Gradio `State` components:

- **Positions 0-36**: Map directly (no shift)
- **Position 37**: Hidden `State` component (must be `None`)
- **Positions 38-50**: API indices 37-49 shifted by +1
- **Positions 51-54**: Four more hidden `State` components (must be `None`)

The full 55-element parameter array is documented in Section 5 below.

**SSE Response Format:**

After POSTing to `/gradio_api/call/generation_wrapper`, the response contains an `event_id`. Polling `GET /gradio_api/call/generation_wrapper/{event_id}` returns an SSE stream with events:

- `event: heartbeat` (keepalive)
- `event: generating` + `data: [...]` (progress updates)
- `event: complete` + `data: [...]` (final result with FLAC path)
- `event: error` + `data: "..."` (error message)

The FLAC file path is extracted from the complete event data. Three extraction strategies are used in order:

1. `data[8]` — file list position (list of dicts with `path` key)
2. `data[0].value.path` — generating event playback format
3. Full recursive scan of all items for any dict with a `.flac` path

Files are downloaded from Gradio's file server: `GET /gradio_api/file={path}`

---

## 4. UI Container

### Docker Configuration

**Dockerfile:** `/home/bobray/ace-step/ui/Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7861
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7861"]
```

- Base image: `python:3.11-slim`
- `fonts-dejavu-core` is installed for the Pillow cover art fallback (DejaVuSans font rendering)
- Server: uvicorn on port 7861

**docker-compose.yml:** `/home/bobray/ace-step/docker-compose.yml`

```yaml
services:
  ui:
    build: ./ui
    image: bray-music-ui:latest
    container_name: bray-music-ui
    restart: unless-stopped
    ports:
      - "7861:7861"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./outputs:/app/outputs
    environment:
      - ACESTEP_URL=http://host.docker.internal:7860
      - NEXTCLOUD_URL=https://nextcloud.services.bray.house
      - NEXTCLOUD_USER=bobray
      - NEXTCLOUD_PASS=${NEXTCLOUD_PASS}
```

Key details:
- **`extra_hosts`**: Maps `host.docker.internal` to the Docker host gateway, allowing the container to reach the native ACE-Step process on port 7860
- **Volume mount**: `./outputs:/app/outputs` — shared directory for FLAC files, covers, and history.json
- **Environment variables**: `NEXTCLOUD_PASS` is sourced from `.env` via Docker Compose variable substitution

**requirements.txt:**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
httpx==0.27.0
pillow==10.4.0
aiofiles==24.1.0
pydantic==2.8.0
pytest==8.3.0
pytest-asyncio==0.23.8
respx==0.21.1
```

### Environment Variables

File: `/home/bobray/ace-step/.env`

| Variable | Value | Purpose |
|----------|-------|---------|
| `NEXTCLOUD_PASS` | `FjyNr-fYX8A-wcSMa-X7mL5-gHx2W` | Nextcloud app password (app name: "BrayMusicStudio") |
| `NEXTCLOUD_USER` | `bobray` | Nextcloud username for Task Processing API |

**Note:** `ACESTEP_URL`, `NEXTCLOUD_URL` are set in docker-compose.yml environment, not the .env file.

### Configuration Module

File: `/home/bobray/ace-step/ui/config.py`

```python
ACESTEP_URL = os.environ.get("ACESTEP_URL", "http://ace-step:7860")
NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "https://nextcloud.services.bray.house")
NEXTCLOUD_USER = os.environ.get("NEXTCLOUD_USER", "bobray")
NEXTCLOUD_PASS = os.environ.get("NEXTCLOUD_PASS", "")

OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", "/app/outputs"))
COVERS_DIR = OUTPUTS_DIR / "covers"
AUDIO_DIR = OUTPUTS_DIR / "api_audio"
HISTORY_FILE = OUTPUTS_DIR / "history.json"
```

Directory auto-creation: `COVERS_DIR` and `AUDIO_DIR` are created at import time via `mkdir(parents=True, exist_ok=True)`.

### FastAPI Application

File: `/home/bobray/ace-step/ui/main.py`

**App title:** `Bray Music Studio`

### API Endpoints — Complete Reference

#### `GET /` — Main UI

- Response: `HTMLResponse`
- Serves `static/index.html` (the Create page)

#### `GET /library` — Library Page

- Response: `HTMLResponse`
- Serves `static/library.html` (the Library page)

#### `POST /generate` — Synchronous Generation

- Request body: `GenerateRequest` (JSON)
- Response: `GenerateResponse` (JSON)
- Calls `gradio_client.generate()` synchronously (blocks until FLAC is ready)
- Reads FLAC duration from file header
- Saves track to history
- Triggers cover art generation as a background task
- Returns 502 if ACE-Step fails

**Request schema (`GenerateRequest`):**

```json
{
  "title": "string (1-200 chars, required)",
  "description": "string (1-500 chars, required)",
  "lyrics": "string (0-5000 chars, default '')",
  "duration": "float (0-8.0, default 0, 0=auto)",
  "include_vocals": "bool (default true)",
  "enhance_lyrics": "bool (default false)",
  "bpm": "string (default '')",
  "key": "string (default '')",
  "creativity": "int (0-100, default 50)",
  "seed": "string (default '')"
}
```

**Response schema (`GenerateResponse`):**

```json
{
  "track": {
    "id": "uuid string",
    "title": "string",
    "description": "string",
    "genre_hint": "string",
    "duration_sec": "float",
    "filename": "string",
    "cover_art": "string or null",
    "cover_gradient": "CSS gradient string",
    "emoji": "string",
    "created_at": "ISO 8601 string",
    "format": "FLAC",
    "seed": "int"
  },
  "status": "ok"
}
```

#### `POST /generate-stream` — SSE Streaming Generation

- Request body: `GenerateRequest` (JSON)
- Response: `StreamingResponse` (text/event-stream)
- Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`
- Returns 422 for validation errors (before stream starts)
- Stream always starts with HTTP 200 (errors are sent as SSE events)

**SSE Event Types:**

| Event | Fields | Description |
|-------|--------|-------------|
| `step` | `step`, `state` | Pipeline step status. Steps: `submit`, `queue`, `generate`, `decode`, `save`. States: `active`, `done` |
| `progress` | `message` | Progress text from ACE-Step (e.g., "LM planning: 45%") |
| `heartbeat` | — | Keepalive from ACE-Step |
| `track` | `track` (TrackMeta object) | Track metadata after generation completes |
| `error` | `message` | Error message (terminal event) |
| `done` | — | Final event, all processing complete |

#### `GET /history` — Track History

- Query params: `sort` (`newest`|`oldest`), `search` (string)
- Response: `HistoryResponse`
- Search filters on title and description (case-insensitive substring match)

```json
{
  "tracks": [TrackMeta, ...],
  "total": 7
}
```

#### `GET /audio/{filename}` — Serve Audio File

- Response: `FileResponse` (audio/flac)
- Returns 404 if file not found
- Serves from `AUDIO_DIR` (`/app/outputs/api_audio/`)

#### `GET /cover/{filename}` — Serve Cover Art

- Response: `FileResponse` (image/png)
- Returns 404 if file not found
- Serves from `COVERS_DIR` (`/app/outputs/covers/`)

#### `GET /track/{track_id}` — Get Single Track

- Response: `TrackMeta`
- Returns 404 if track not found

#### `DELETE /track/{track_id}` — Delete Track

- Removes from history.json
- Deletes audio file from disk
- Deletes cover art file if exists
- Returns 404 if track not found
- Response: `{"status": "deleted", "id": "..."}`

#### `GET /health` — Health Check

- Checks ACE-Step reachability (GET `/gradio_api/info`)
- Checks GPU via `nvidia-smi` (may not be available in container)
- Checks outputs directory writability

```json
{
  "status": "ok",
  "acestep": "reachable" | "unreachable",
  "gpu": "NVIDIA GeForce GTX 1080 Ti" | "nvidia-smi not available",
  "outputs_writable": true
}
```

### Data Models

File: `/home/bobray/ace-step/ui/models.py`

**`GenerateRequest`** — Input validation with Pydantic:

| Field | Type | Constraints | Default |
|-------|------|-------------|---------|
| `title` | `str` | min_length=1, max_length=200 | required |
| `description` | `str` | min_length=1, max_length=500 | required |
| `lyrics` | `str` | max_length=5000 | `""` |
| `duration` | `float` | ge=0, le=8.0 | `0` (auto) |
| `include_vocals` | `bool` | — | `True` |
| `enhance_lyrics` | `bool` | — | `False` |
| `bpm` | `str` | — | `""` |
| `key` | `str` | — | `""` |
| `creativity` | `int` | ge=0, le=100 | `50` |
| `seed` | `str` | — | `""` |

**`TrackMeta`** — Track metadata:

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | — |
| `title` | `str` | — |
| `description` | `str` | — |
| `genre_hint` | `str` | `""` |
| `duration_sec` | `float` | — |
| `filename` | `str` | — |
| `cover_art` | `str \| None` | `None` |
| `cover_gradient` | `str` | Purple-pink gradient |
| `emoji` | `str` | `"🎵"` |
| `created_at` | `str` | — |
| `format` | `str` | `"FLAC"` |
| `seed` | `int` | `0` |

### History Storage

File: `/home/bobray/ace-step/ui/history.py`

- Storage: JSON file at `OUTPUTS_DIR/history.json`
- Concurrency: `asyncio.Lock` protects all read-modify-write operations
- Operations: `load()`, `append()`, `remove()`, `get()`, `update_cover()`
- File format: JSON array of TrackMeta dicts with `indent=2`
- No database — simple file-based persistence

### Helper Functions in main.py

**`_get_audio_duration(file_path)`**: Reads FLAC file headers to extract actual duration. Parses the STREAMINFO metadata block: extracts sample rate from bytes 10-12 and total samples from bytes 13-17, computing `total_samples / sample_rate`.

**`_extract_genre(description)`**: Scans description for genre keywords. Returns first match from: rock, pop, jazz, classical, hip hop, electronic, folk, country, r&b, metal, indie, ambient, blues, reggae, soul, punk, latin, dance, orchestral. Default: `"music"`.

**`_gradient_for(track_id)`**: Deterministic gradient selection based on `hash(track_id) % 8`. Eight gradient presets cycle through purple, pink, blue, green, orange, and peach tones.

**`_emoji_for(genre)`**: Maps genre strings to emoji. Examples: rock=🎸, pop=🎤, jazz=🎷, country=🤠, electronic=🎛️, ambient=🌊.

---

## 5. Parameter Mapping

File: `/home/bobray/ace-step/ui/gradio_client.py`

### Complete 55-Position Parameter Array

The UI builds a 55-element array that maps to ACE-Step's Gradio handler. Due to 5 hidden `State` components, API indices and real positions diverge at position 37.

**Positions 0-36 (API index = real position, no shift):**

| Real Pos | API Idx | Name | UI Mapping | Default |
|----------|---------|------|------------|---------|
| 0 | 0 | Music Caption | `req.description` | `""` |
| 1 | 1 | Lyrics | `req.lyrics` or `"[Instrumental]"` | `""` |
| 2 | 2 | BPM | `float(req.bpm)` if provided | `None` |
| 3 | 3 | Key | `req.key` if provided | `""` |
| 4 | 4 | Time Signature | Not exposed in UI | `""` |
| 5 | 5 | Vocal Language | Hardcoded `"en"` | `"unknown"` |
| 6 | 6 | DiT Inference Steps | Hardcoded `8` (turbo) | `32` |
| 7 | 7 | DiT Guidance Scale | `10.0 - (creativity/100) * 8.5` | `7.0` |
| 8 | 8 | Random Seed | `True` if no seed, `False` if seed given | `True` |
| 9 | 9 | Seed | `str(seed_val)` | `"-1"` |
| 10 | 10 | Reference Audio | Not used | `None` |
| 11 | 11 | Audio Duration | `-1` if auto, else `duration * 60` (seconds) | `-1` |
| 12 | 12 | Batch Size | Hardcoded `1` | `2` |
| 13 | 13 | Source Audio | Not used | `None` |
| 14 | 14 | LM Codes Hints | Not used | `None` |
| 15 | 15 | Repainting Start | Not used | `0.0` |
| 16 | 16 | Repainting End | Not used | `-1` |
| 17 | 17 | Instruction | Not exposed | `"Fill the audio semantic mask based on the given conditions:"` |
| 18 | 18 | LM Codes Strength | Not exposed | `1.0` |
| 19 | 19 | Cover Strength | Not exposed | `0.0` |
| 20 | 20 | Task Type | Not exposed | `"text2music"` |
| 21 | 21 | Use ADG | Not exposed | `False` |
| 22 | 22 | CFG Interval Start | Not exposed | `0.0` |
| 23 | 23 | CFG Interval End | Not exposed | `1.0` |
| 24 | 24 | Shift | Not exposed | `3.0` |
| 25 | 25 | Inference Method | Not exposed | `"ode"` |
| 26 | 26 | Custom Timesteps | Not exposed | `""` |
| 27 | 27 | Audio Format | Hardcoded `"flac"` | `"mp3"` |
| 28 | 28 | LM Temperature | Not exposed | `0.85` |
| 29 | 29 | Think | Not exposed | `True` |
| 30 | 30 | LM CFG Scale | Not exposed | `2.0` |
| 31 | 31 | LM Top-K | Not exposed | `0` |
| 32 | 32 | LM Top-P | Not exposed | `0.9` |
| 33 | 33 | LM Negative Prompt | Not exposed | `"NO USER INPUT"` |
| 34 | 34 | CoT Metas | Not exposed | `True` |
| 35 | 35 | CaptionRewrite | `True` if `enhance_lyrics`, else `False` | `False` |
| 36 | 36 | CoT Language | Not exposed | `True` |

**Position 37 (Hidden State):**

| Real Pos | API Idx | Name | Value |
|----------|---------|------|-------|
| 37 | — | Hidden State | `None` (always) |

**Positions 38-50 (API index + 1 = real position):**

| Real Pos | API Idx | Name | UI Mapping | Default |
|----------|---------|------|------------|---------|
| 38 | 37 | Constrained Decoding Debug | Not exposed | `False` |
| 39 | 38 | ParallelThinking | Not exposed | `True` |
| 40 | 39 | Auto Score | Not exposed | `False` |
| 41 | 40 | Auto LRC | Not exposed | `False` |
| 42 | 41 | Quality Score Sensitivity | Not exposed | `0.5` |
| 43 | 42 | LM Batch Chunk Size | Not exposed | `8` |
| 44 | 43 | Track Name | Not exposed | `None` |
| 45 | 44 | Track Names | Not exposed | `[]` |
| 46 | 45 | Enable Normalization | Not exposed | `True` |
| 47 | 46 | Target Peak dB | Not exposed | `-1.0` |
| 48 | 47 | Latent Shift | Not exposed | `0.0` |
| 49 | 48 | Latent Rescale | Not exposed | `1.0` |
| 50 | 49 | AutoGen | See below | `False` |

**Positions 51-54 (Hidden States):**

| Real Pos | Value |
|----------|-------|
| 51 | `None` |
| 52 | `None` |
| 53 | `None` |
| 54 | `None` |

### Key Parameter Transformations

#### include_vocals → Lyrics

When `include_vocals=False`, the lyrics parameter (position 1) is set to `"[Instrumental]"` regardless of any user-provided lyrics. When `True`, user lyrics are passed through verbatim.

#### enhance_lyrics → CaptionRewrite (position 35)

When `enhance_lyrics=True`, CaptionRewrite at API position 35 (real position 35, no shift needed) is set to `True`. This tells ACE-Step's LLM to rewrite/improve the caption using Chain-of-Thought reasoning before generating music.

#### creativity → DiT Guidance Scale (position 7)

The creativity slider (0-100) maps **inversely** to guidance scale:

```
guidance = 10.0 - (creativity / 100.0) * 8.5
```

| Creativity | Guidance Scale | Effect |
|------------|---------------|--------|
| 0 (strict) | 10.0 | Maximum adherence to prompt |
| 50 (balanced) | 5.75 | Balanced |
| 75 (default in Simple mode) | 3.625 | Creative but guided |
| 100 (free) | 1.5 | Maximum creative freedom |

#### AutoGen (API 49 → real position 50)

AutoGen is automatically enabled when:
- `include_vocals=True` AND
- No lyrics are provided (empty string or whitespace only)

This tells ACE-Step's LLM to auto-generate lyrics from the description (Suno-style behavior). When lyrics are provided or vocals are disabled, AutoGen stays `False`.

#### duration → Audio Duration (position 11)

- `duration=0` (auto): Set to `-1` (ACE-Step decides length, typically 1-3 minutes)
- `duration=N`: Set to `N * 60` (converted from minutes to seconds)

The UI supports 0 (auto) or 1-8 minutes in 0.5-minute increments.

#### seed

- Empty string or non-numeric: Random seed generated as `random.randint(0, 2**31)`, position 8 (Random Seed) = `True`
- Numeric string: Parsed to int, position 8 = `False`, position 9 = string representation

### Gradio Client Timeouts

```python
TIMEOUT = 600.0  # 10 minutes — FP32 on Pascal is slower
```

This applies to both the initial POST and the SSE polling stream.

---

## 6. Cover Art Pipeline

File: `/home/bobray/ace-step/ui/cover_art.py`

### Two-Tier Generation Strategy

1. **Primary: Nextcloud Task Processing API** → Visionatrix SDXL (AI-generated cover art)
2. **Fallback: Pillow** → Gradient background with title text overlay

The fallback always succeeds, ensuring every track gets cover art.

### Nextcloud/Visionatrix Path

**API endpoint:** `POST {NEXTCLOUD_URL}/ocs/v2.php/taskprocessing/schedule`

**Authentication:** HTTP Basic Auth using the Nextcloud app password `BrayMusicStudio`.

**Headers:**
```
OCS-APIRequest: true
Accept: application/json
Content-Type: application/json
```

**Request body:**
```json
{
  "type": "core:text2image",
  "appId": "bray-music-studio",
  "input": {
    "input": "<prompt>",
    "numberOfImages": 1
  }
}
```

**Prompt template:**
```
Album cover art for a {genre} song titled '{title}', {description[:80]}, artistic, music album cover
```

The description is truncated to 80 characters to keep the prompt focused.

**Polling:**
- Endpoint: `GET /ocs/v2.php/taskprocessing/task/{task_id}`
- Poll interval: 5 seconds
- Timeout: 600 seconds (10 minutes — Visionatrix SDXL on GTX 1060 at BrayNextcloudServer can take 5-10 minutes)
- Status values: `STATUS_SUCCESSFUL`, `STATUS_FAILED`, `STATUS_CANCELLED`

**Image download:**
- Endpoint: `GET /ocs/v2.php/taskprocessing/tasks/{task_id}/file/{file_id}`
- The `file_id` is extracted from `task.output.images[0]`

**Post-processing:**
- SDXL outputs at 832x1216; images are resized to 512x512 using `Image.LANCZOS`
- Saved as PNG to `COVERS_DIR/{track_id}.png`

### Pillow Fallback

Used when:
- `NEXTCLOUD_PASS` is not configured
- Nextcloud/Visionatrix is unreachable
- Task fails or times out

**Generation process:**
1. Create 512x512 RGB image
2. Generate vertical gradient using HSV color space, hue derived from `hash(track_id) % 360`
3. Apply semi-transparent black overlay on bottom 160px
4. Render title text (max 30 chars) at center-bottom using DejaVuSans-Bold 48pt
5. Render genre text below title using DejaVuSans 28pt
6. Save as PNG

### Cover Art Update Flow

Cover art is generated asynchronously after the track is created:
1. In `/generate`: cover art runs as a FastAPI `BackgroundTasks` task
2. In `/generate-stream`: cover art runs as an `asyncio.create_task()`
3. When complete, `history_mod.update_cover(track_id, cover_file)` patches the JSON file
4. The frontend polls or reloads to pick up the cover art URL

---

## 7. Frontend Architecture

### Two Pages

1. **Create page** (`/`, `static/index.html`) — Song creation interface
2. **Library page** (`/library`, `static/library.html`) — Browse and play all songs

### Design System: Glassmorphism v3

- **Background:** `#080614` (near-black dark purple)
- **Animated blobs:** 4 floating colored circles with `filter: blur(90px)`, `opacity: 0.3`, animated with 9s ease-in-out `bfloat` keyframes
  - b1: 520px, `#6d28d9` (purple), top-left
  - b2: 420px, `#0d9488` (teal), bottom-right
  - b3: 360px, `#db2777` (pink), middle-right
  - b4: 280px, `#2563eb` (blue), bottom-left
- **Glass panels:** `rgba(255,255,255,.055)` background, `backdrop-filter: blur(22px)`, `border: 1px solid rgba(255,255,255,.11)`, `border-radius: 20px`
- **Font:** Ubuntu (Google Fonts), weights 300/400/500/700
- **Accent colors:** `#8b5cf6` (violet), `#ec4899` (pink), `#6d28d9` (purple)
- **Button gradient:** `linear-gradient(135deg, #6d28d9, #8b5cf6, #db2777)` with `background-size: 200%` and `gshift` animation

### Create Page Layout

**Desktop (>900px):** 3-column CSS grid: `270px 1fr 290px`

| Column | Content |
|--------|---------|
| Left | Quick Style presets, Voice toggle, Song Length, Advanced settings |
| Center | Song title, Description, Lyrics, AI Lyric Polish, Generate button |
| Right | Now Playing widget, History list |

**Mobile (<900px):** Single column flex layout. Right panel (Now Playing + History) is hidden. Bottom player bar appears instead.

### Simple vs Custom Mode

Toggled via buttons in the header. Default: **Simple mode**.

**Simple mode:**
- Grid changes to `1fr 290px` (hides left and center panels)
- Shows `simple-panel` with:
  - Hero text: "What song do you want?"
  - Subtitle: "Just describe it — the AI writes lyrics, picks the style, and creates everything"
  - Title input (optional)
  - Description textarea with placeholder examples
  - Example chips (clickable): Fishing with grandpa, Rock anthem, Worship hymn, Summer road trip pop, Anniversary love song
  - "Create My Song" button
- Hardcoded parameters: `include_vocals=true`, `enhance_lyrics=false`, `creativity=75`, `duration=0` (auto), `seed=""` (random)

**Custom mode:**
- Full 3-column layout with all controls exposed
- Quick Style presets (8 buttons, 2x4 grid): Hymns, Christian, Rock, Rock/Rap, Pop, Country, Acoustic, Custom
- Voice toggle (Include Vocals on/off)
- Song Length: Auto (checkbox) or manual slider 1-8 minutes in 0.5 steps
- Advanced section (collapsed by default): BPM, Key, AI Creativity slider (0-100, default 75), Seed input

### Generation Modal

Triggered by both Simple and Custom mode generation. A centered overlay with dark backdrop blur.

**Steps displayed:**

| Step ID | Label |
|---------|-------|
| gs-submit | Submitting to AI |
| gs-queue | Waiting in queue |
| gs-generate | Generating music |
| gs-decode | Decoding audio |
| gs-save | Saving your song |
| gs-cover | Creating cover art |

Each step has three visual states:
- **Pending:** Gray circle outline, dimmed text
- **Active:** Purple pulsing border with `gpulse` animation, white text
- **Done:** Solid purple circle with checkmark, purple text
- **Error:** Red border, X mark, red text

**Elapsed timer:** Updates every second showing "Elapsed: Xs"

**Cancel button:** Closes modal (does not actually cancel generation — the SSE stream continues)

### SSE Streaming Progress (Frontend)

The frontend reads the SSE stream from `/generate-stream` using `ReadableStream`:

1. Opens fetch with POST
2. Reads chunks via `response.body.getReader()`
3. Parses `data: {...}` lines as JSON
4. Maps `step` events to modal step states
5. Maps `progress` events to progress message display
6. On `track` event: adds to trackList, starts playback, reloads history
7. On `error` event: marks active steps as errored
8. After 5 seconds: auto-closes modal

### Now Playing Widget (Desktop, Right Panel)

- 120x120px album art with pulsing glow animation
- Title and subtitle (genre + format + seed)
- 15-bar waveform visualization (CSS animated bars, paused when not playing)
- Previous/Play/Next controls
- Seekable range input (0-1000 mapped to track duration)
- Time display: current / total

### Seek Bar Progress Fill Fix

The seek bar uses a JavaScript-driven `background` gradient to show played portion:

```javascript
function updateSeekFill(rangeEl) {
  const pct = (rangeEl.value / rangeEl.max) * 100;
  rangeEl.style.background = 'linear-gradient(90deg, #8b5cf6 0%, #ec4899 '
    + pct + '%, rgba(255,255,255,.12) ' + pct + '%)';
}
```

This works across Chrome and Firefox since `::-webkit-slider-runnable-track` styling doesn't propagate to all browsers. The function is called on both `timeupdate` and `input` events.

### Mobile Player Bar

On screens <900px, a fixed-bottom player bar appears:
- Grid layout: `40px 1fr auto` for cover/info/controls, seek bar spans full width
- 40x40px cover art
- Title (13px, truncated)
- Play/pause button (36px circle with gradient)
- Seek bar with time labels

### History Cards (Desktop)

Right panel displays cards with:
- 40x40px thumbnail (cover art or gradient with emoji)
- Title (13px, bold, word-break)
- Metadata: duration, format (FLAC), seed number, date
- Action buttons: play, copy link, download, delete

### Library Page

Full-page song library at `/library`.

**Features:**
- Header with nav links (Create / Library)
- Toolbar: "Your Library" title, track count, search input, sort dropdown (newest/oldest)
- Song grid: `repeat(auto-fill, minmax(280px, 1fr))` responsive grid
- Song cards with:
  - 72x72px cover art
  - Title, description (2-line clamp)
  - Genre tag, duration, format, seed, date
  - Play, Copy Link, Download, Delete buttons
- Bottom player bar (same as mobile player but always visible)
- Empty state with link to Create page
- Mobile responsive: single column, reduced card/cover sizes

### Direct Song Link / Copy Feature

Each song has a copy-link button (🔗) that copies a URL in the format:

```
https://music.apps.bray.house/library#track-{track_id}
```

On page load, if the URL hash starts with `#track-`, the library page:
1. Waits 500ms for tracks to load
2. Finds the track by ID
3. Auto-plays it
4. Scrolls the card into view with `scrollIntoView({ behavior: 'smooth', block: 'center' })`

The copy button shows a green checkmark for 1.5 seconds after copying. Falls back to `prompt()` dialog if clipboard API is unavailable.

### Genre-Based Quick Style Presets

8 preset buttons in Custom mode's left panel:

| Button | Description Injected |
|--------|---------------------|
| 🕊️ Hymns | Peaceful hymn, sacred choral voices, organ, gentle orchestral, reverent and uplifting |
| ✝️ Christian | Contemporary Christian worship, uplifting piano, acoustic guitar, heartfelt vocals |
| 🎸 Rock | Electric guitar driven rock, powerful drums, energetic riffs, stadium anthem |
| 🎤 Rock/Rap | Hip-hop and rock fusion, heavy beats, rap verses, electric guitar hooks |
| ⭐ Pop | Catchy pop melody, upbeat synth, polished production, bright hooky chorus |
| 🤠 Country | Country guitar, warm fiddle, heartfelt storytelling vocals, Nashville sound |
| 🎶 Acoustic | Fingerpicked acoustic guitar, intimate vocals, gentle melody, singer-songwriter |
| ✏️ Custom | Clears description (empty string) |

---

## 8. Networking

### External Access

| Component | URL | Backend |
|-----------|-----|---------|
| Bray Music Studio | https://music.apps.bray.house | 192.168.1.153:7861 |
| Library | https://music.apps.bray.house/library | Same |

### NPM Proxy Configuration

- **Proxy Host ID:** 37
- **Scheme:** HTTPS
- **SSL Certificate:** `*.apps.bray.house` wildcard (acme.sh + Dynu DNS-01)
- **Forward hostname/IP:** 192.168.1.153
- **Forward port:** 7861
- **Certificate renewal:** ~every 60 days, next ~2026-04-20

### Internal Networking

```
bray-music-ui container (port 7861)
    |
    +-- host.docker.internal:7860 --> ACE-Step native process (systemd)
    |   (via Docker's extra_hosts: host.docker.internal:host-gateway)
    |
    +-- HTTPS --> nextcloud.services.bray.house --> BrayNextcloudServer (192.168.1.103)
        (Nextcloud Task Processing API for cover art)
```

**Docker network:** Default bridge. The `host.docker.internal` mapping uses Docker's `--add-host` mechanism to resolve to the host's gateway IP, allowing the container to reach the native ACE-Step process.

**Port mapping:**
- `7860`: ACE-Step Gradio server (native, systemd, not exposed to Docker network directly)
- `7861`: Bray Music Studio UI (Docker, mapped to host)

---

## 9. Known Issues and Considerations

### Pascal GPU Limitations

1. **Driver ceiling:** nvidia-580 is the last driver supporting Pascal (sm_61). Do NOT upgrade to nvidia-590+.
2. **PyTorch CUDA build:** Must use cu124. The cu128 and cu130 builds dropped sm_61 support. The `pyproject.toml` is pinned accordingly.
3. **VRAM:** 11 GiB is sufficient for the turbo model + 0.6B LM but cannot run the 4B LM or base model without heavy offloading.
4. **Performance:** FP32 on Pascal is slower than tensor-core GPUs. Generation takes 60-120 seconds per song (vs. 15-30 seconds on an RTX 3090).
5. **INT8 quantization:** Used by GPU tier 4 auto-config. Works on Pascal but without hardware INT8 tensor cores, it is emulated.

### AutoGen Quality

When AutoGen is enabled (vocals on, no lyrics provided), the 0.6B language model generates lyrics automatically. Quality is variable — the small model produces acceptable but sometimes repetitive or generic lyrics. The 1.7B or 4B models would produce better results but are too large for reliable operation on 11 GiB VRAM with the DiT model also loaded.

### Chrome Headless Screenshot Bug

When taking mobile-viewport screenshots with `google-chrome --headless --window-size=390,844`, Chrome enforces a minimum viewport of ~500px. The screenshot is cropped to the requested size but the layout is rendered at the wider viewport.

**Correct approach:** Use CDP (Chrome DevTools Protocol) with `Emulation.setDeviceMetricsOverride` and `mobile: true` for proper mobile-width rendering. Reference script: `/tmp/proper_screenshot.py`.

This is documented here for future reference when taking screenshots of the UI.

### FLAC Duration Detection

The `_get_audio_duration()` function reads FLAC STREAMINFO metadata directly from the binary header. It handles:
- Magic bytes validation (`fLaC`)
- Block type 0 (STREAMINFO) with minimum 18 bytes
- Sample rate extraction from bytes 10-12 (20 bits)
- Total samples extraction from bytes 13-17 (36 bits)
- Division: `total_samples / sample_rate`

If header parsing fails (corrupt file, non-FLAC), the function falls back to `req.duration * 60` (the requested duration in seconds). Fallback value is `0.0` if the header read fails and no request duration is available.

### Concurrent History Writes

The `history.json` file is protected by an `asyncio.Lock`. However, this only protects against concurrent writes within the same process. If multiple container instances were to share the same volume, data loss could occur. Currently only one `bray-music-ui` container runs, so this is not an issue.

### Cover Art Race Condition

Cover art generation runs in the background after the track response is sent to the client. The client may display the track before cover art is ready. The frontend handles this gracefully by showing a gradient+emoji placeholder until the cover art URL is populated in the track metadata. A page reload or library visit will show the cover once available.

---

## 10. Testing

### Test Structure

```
/home/bobray/ace-step/ui/tests/
├── __init__.py
├── conftest.py          # Shared fixtures (68 lines)
├── unit/
│   ├── __init__.py
│   ├── test_gradio_client.py   # 21 tests — parameter building, SSE parsing
│   ├── test_cover_art.py       # 4 tests — Pillow fallback, error handling
│   └── test_history.py         # 6 tests — CRUD, concurrent writes
├── api/
│   ├── __init__.py
│   └── test_endpoints.py       # 16 tests — all FastAPI endpoints
└── integration/
    ├── __init__.py
    └── test_integration.py     # 4 tests — live container tests (marked @integration)
```

**Total: 47 unit + API tests** (integration tests are separate, require live containers)

### pytest Configuration

File: `/home/bobray/ace-step/ui/pytest.ini`

```ini
[pytest]
asyncio_mode = auto
markers =
    integration: mark test as integration test (requires live containers)
```

### Key Test Fixtures (conftest.py)

**`patch_outputs` (autouse):** Redirects all file paths (`OUTPUTS_DIR`, `COVERS_DIR`, `AUDIO_DIR`, `HISTORY_FILE`) to a `tmp_path` for each test. Patches the `config`, `history`, `cover_art`, and `main` modules.

**`sample_track`:** Returns a `TrackMeta` with id="test-id-1234", title="Test Song", rock genre, 180 second duration, seed=42.

**`test_client`:** Creates an async httpx test client using `ASGITransport(app=app)` for testing FastAPI endpoints without a running server.

### Running Tests

```bash
# Inside the container:
docker exec bray-music-ui python -m pytest tests/unit tests/api -v

# From the host (if tests are in the mounted volume):
docker exec bray-music-ui python -m pytest tests/unit tests/api -v

# Integration tests (requires live containers):
docker exec bray-music-ui python -m pytest tests/integration -v -m integration
```

### Test Coverage Summary

**Unit tests (`test_gradio_client.py`):**
- Parameter array construction (correct positions, correct values)
- State injection (position 37 = None, positions 51-54 = None)
- API-to-real index shift verification
- Instrumental mode (`[Instrumental]` tag)
- Vocals mode (lyrics passthrough)
- CaptionRewrite toggle
- Creativity-to-guidance mapping (0→10.0, 50→5.75, 100→1.5)
- AutoGen logic (enabled when vocals on + no lyrics, disabled otherwise)
- BPM and Key handling
- Seed handling (random vs explicit)
- SSE stream parsing (data[8] format, fallback scan, error events)

**Unit tests (`test_cover_art.py`):**
- Pillow fallback creates valid 512x512 PNG
- Falls back on Nextcloud errors
- Falls back when NEXTCLOUD_PASS not configured
- Gradient varies by track ID

**Unit tests (`test_history.py`):**
- Append creates file
- Append preserves existing tracks
- Remove returns True/False
- Update cover modifies JSON
- 10 concurrent writes succeed

**API tests (`test_endpoints.py`):**
- GET / serves HTML with "Bray Music Studio"
- POST /generate success (mocked ACE-Step)
- POST /generate missing description → 422
- POST /generate duration out of range → 422
- POST /generate ACE-Step error → 502
- GET /history empty, sorted, searched
- GET /audio serves FLAC, 404 for missing
- GET /cover serves PNG
- DELETE /track success and cleanup
- DELETE /track nonexistent → 404
- GET /health returns status
- POST /generate-stream success with SSE events
- POST /generate-stream error handling
- POST /generate-stream validation → 422

**Integration tests (`test_integration.py`):**
- Full generate-and-play cycle
- Cover art appearance polling
- Delete removes file
- History returns generated tracks

---

## 11. Operations

### Starting the System

Both components must be running:

```bash
# 1. ACE-Step (systemd, auto-starts on boot)
sudo systemctl start acestep

# 2. UI container (restart: unless-stopped, auto-starts on boot)
cd /home/bobray/ace-step
docker compose up -d
```

### Stopping the System

```bash
# Stop UI container
cd /home/bobray/ace-step
docker compose down

# Stop ACE-Step
sudo systemctl stop acestep
```

### Restarting

```bash
# Restart ACE-Step (takes 2-3 minutes to reload models)
sudo systemctl restart acestep

# Restart UI container (fast, ~5 seconds)
cd /home/bobray/ace-step
docker compose restart
```

### Rebuilding the UI Container

After code changes:

```bash
cd /home/bobray/ace-step
docker compose down
docker compose up --build -d
```

### Viewing Logs

```bash
# ACE-Step logs (systemd journal)
journalctl -u acestep -f
journalctl -u acestep --since "1 hour ago"

# UI container logs (Docker)
docker logs -f bray-music-ui
docker logs --tail 100 bray-music-ui
```

### Checking Status

```bash
# ACE-Step service
systemctl status acestep

# UI container
docker ps | grep bray-music-ui

# Health endpoint
curl -s http://localhost:7861/health | python3 -m json.tool

# GPU status
nvidia-smi
```

### Troubleshooting

**"ACE-Step unreachable" in health check:**
1. Check `systemctl status acestep` — is it running?
2. Check `journalctl -u acestep -f` — any errors?
3. Verify port 7860 is listening: `ss -tlnp | grep 7860`
4. Test directly: `curl http://localhost:7860/gradio_api/info`

**Generation fails with timeout:**
1. Check GPU utilization: `nvidia-smi` — is it at 100%? A previous generation may still be running.
2. Check ACE-Step logs for OOM or CUDA errors
3. The 10-minute timeout (`TIMEOUT = 600.0`) should accommodate even slow generations

**Cover art never appears:**
1. Check `docker logs bray-music-ui | grep cover` for errors
2. Verify Nextcloud is reachable: `curl -s https://nextcloud.services.bray.house/status.php`
3. Check if Visionatrix is running on BrayNextcloudServer
4. The Pillow fallback should always produce a cover — if even that fails, check font availability in the container

**History.json corruption:**
1. Stop the container: `docker compose down`
2. Inspect: `cat /home/bobray/ace-step/outputs/history.json | python3 -m json.tool`
3. If invalid JSON, restore from backup or manually fix
4. Restart: `docker compose up -d`

**Disk space:**
- FLAC files are 3-22 MB each depending on duration
- Cover art PNGs are 8-600 KB each (Pillow fallback ~8 KB, SDXL covers ~350-600 KB)
- Monitor with: `du -sh /home/bobray/ace-step/outputs/`

---

## 12. File Inventory

### ACE-Step Native Installation

| File/Directory | Purpose |
|----------------|---------|
| `/home/bobray/ACE-Step-1.5/` | ACE-Step 1.5 root directory |
| `/home/bobray/ACE-Step-1.5/.env` | Environment variables (model paths, device config) |
| `/home/bobray/ACE-Step-1.5/.venv/` | Python virtual environment (managed by uv) |
| `/home/bobray/ACE-Step-1.5/pyproject.toml` | Package definition, dependencies, PyTorch cu124 pin |
| `/home/bobray/ACE-Step-1.5/checkpoints/` | All model checkpoint directories (37.8 GB total) |
| `/home/bobray/ACE-Step-1.5/checkpoints/acestep-v15-turbo/` | Active DiT turbo model (4.5 GB) |
| `/home/bobray/ACE-Step-1.5/checkpoints/acestep-5Hz-lm-0.6B/` | Active 0.6B language model (1.3 GB) |
| `/home/bobray/ACE-Step-1.5/checkpoints/vae/` | VAE decoder (322 MB) |
| `/home/bobray/ACE-Step-1.5/checkpoints/Qwen3-Embedding-0.6B/` | Embedding model (1.2 GB) |
| `/etc/systemd/system/acestep.service` | systemd unit file |

### Bray Music Studio UI

| File/Directory | Purpose |
|----------------|---------|
| `/home/bobray/ace-step/` | Project root |
| `/home/bobray/ace-step/.env` | Nextcloud credentials (app password) |
| `/home/bobray/ace-step/docker-compose.yml` | Docker Compose service definition |
| `/home/bobray/ace-step/ui/` | FastAPI application root |
| `/home/bobray/ace-step/ui/main.py` | FastAPI app, all route handlers, helper functions |
| `/home/bobray/ace-step/ui/config.py` | Configuration (URLs, paths, env vars) |
| `/home/bobray/ace-step/ui/models.py` | Pydantic data models (GenerateRequest, TrackMeta, etc.) |
| `/home/bobray/ace-step/ui/gradio_client.py` | ACE-Step Gradio API client, parameter building, SSE parsing |
| `/home/bobray/ace-step/ui/cover_art.py` | Cover art generation (Nextcloud + Pillow fallback) |
| `/home/bobray/ace-step/ui/history.py` | History file management (JSON CRUD with async lock) |
| `/home/bobray/ace-step/ui/Dockerfile` | Docker image definition |
| `/home/bobray/ace-step/ui/requirements.txt` | Python dependencies |
| `/home/bobray/ace-step/ui/pytest.ini` | pytest configuration |
| `/home/bobray/ace-step/ui/static/index.html` | Create page (main UI, ~56 KB) |
| `/home/bobray/ace-step/ui/static/library.html` | Library page (~12 KB) |
| `/home/bobray/ace-step/ui/tests/conftest.py` | Shared test fixtures |
| `/home/bobray/ace-step/ui/tests/unit/test_gradio_client.py` | Gradio client unit tests (21 tests) |
| `/home/bobray/ace-step/ui/tests/unit/test_cover_art.py` | Cover art unit tests (4 tests) |
| `/home/bobray/ace-step/ui/tests/unit/test_history.py` | History unit tests (6 tests) |
| `/home/bobray/ace-step/ui/tests/api/test_endpoints.py` | API endpoint tests (16 tests) |
| `/home/bobray/ace-step/ui/tests/integration/test_integration.py` | Integration tests (4 tests, requires live containers) |

### Output Data

| File/Directory | Purpose |
|----------------|---------|
| `/home/bobray/ace-step/outputs/` | Shared volume (Docker mount) |
| `/home/bobray/ace-step/outputs/history.json` | Track metadata JSON array |
| `/home/bobray/ace-step/outputs/api_audio/` | Generated FLAC files |
| `/home/bobray/ace-step/outputs/covers/` | Cover art PNG files |
| `/home/bobray/ace-step/outputs/api.log` | Historical API log |
| `/home/bobray/ace-step/outputs/gradio.log` | Historical Gradio log |

---

*Document generated 2026-03-04. This is the definitive reference for Bray Music Studio.*

---

## Addendum: Lyrics Generation Pipeline (2026-03-04)

### Problem
ACE-Step's Gradio UI Simple Mode uses a two-step process:
1.  — LM generates caption + lyrics + metadata from description
2.  — generates audio with those pre-filled lyrics

CaptionRewrite (api[35]) only enhances the caption text, NOT lyrics.
AutoGen (api[49]) auto-starts next batch, NOT lyrics generation.
Neither parameter generates lyrics from a description.

### Solution
Added  module that calls Ollama on Optimus (192.168.1.145:11434) with  model to generate structured lyrics before calling ACE-Step.

### Flow
1. User submits Simple mode request (vocals=true, lyrics empty)
2. SSE emits 
3.  calls Ollama on Optimus
4. Ollama returns structured lyrics with [Verse], [Chorus], [Bridge] tags
5. SSE emits  event with generated text
6. SSE emits 
7. Request continues to ACE-Step with real lyrics

### Files Modified
-  — Ollama client (90s timeout, qwen3:4b default)
-  — Added 
-  — Added lyrics generation step in both  and 
-  — CaptionRewrite only activates on explicit 

### Validation Results
- **Before** (empty lyrics): Whisper detected 0 segments, 46% English confidence, essentially instrumental
- **After** (Ollama lyrics): Whisper detected 8 segments, 95% English confidence, coherent transcription matching input lyrics

### Configuration
- Ollama URL:  (Optimus, Windows 11, 5 GPUs)
- Model:  (Q4_K_M, fast enough for lyrics gen)
- Timeout: 90s (first call may be slow while model loads)
- Fallback: If Ollama fails/times out, generation proceeds without lyrics (instrumental-like output)


---

## Addendum: Lyrics Generation Pipeline (2026-03-04)

### Problem
ACE-Step's Gradio UI Simple Mode uses a two-step process:
1. create_sample() -- LM generates caption + lyrics + metadata from description
2. generation_wrapper() -- generates audio with those pre-filled lyrics

CaptionRewrite (api[35]) only enhances the caption text, NOT lyrics.
AutoGen (api[49]) auto-starts next batch, NOT lyrics generation.
Neither parameter generates lyrics from a description.

### Solution
Added lyrics_gen.py module that calls Ollama on Optimus (192.168.1.145:11434) with qwen3:4b model to generate structured lyrics before calling ACE-Step.

### Flow
1. User submits Simple mode request (vocals=true, lyrics empty)
2. SSE emits step:lyrics:active
3. lyrics_gen.generate_lyrics(description) calls Ollama on Optimus
4. Ollama returns structured lyrics with [Verse], [Chorus], [Bridge] tags
5. SSE emits lyrics event with generated text
6. SSE emits step:lyrics:done
7. Request continues to ACE-Step with real lyrics

### Files Modified
- ui/lyrics_gen.py -- Ollama client (90s timeout, qwen3:4b default)
- ui/config.py -- Added OLLAMA_URL=http://192.168.1.145:11434
- ui/main.py -- Added lyrics generation step in both /generate and /generate-stream
- ui/gradio_client.py -- CaptionRewrite only activates on explicit enhance_lyrics=True

### Validation Results
- Before (empty lyrics): Whisper detected 0 segments, 46% English confidence, essentially instrumental
- After (Ollama lyrics): Whisper detected 8 segments, 95% English confidence, coherent transcription matching input lyrics

### Configuration
- Ollama URL: http://192.168.1.145:11434 (Optimus, Windows 11, 5 GPUs)
- Model: qwen3:4b (Q4_K_M, fast enough for lyrics gen)
- Timeout: 90s (first call may be slow while model loads)
- Fallback: If Ollama fails/times out, generation proceeds without lyrics (instrumental-like output)

---

## Addendum: Duration Limit & Cover Art Verification (2026-03-04)

### Duration Cap: 3 Minutes Maximum
- **Problem:** 4-minute song caused Linux OOM kill during DiT diffusion phase with CPU+DiT offload
- **Root cause:** ROG-STRIX has only 14GB RAM. Tier 4 GPU config allows up to 8 min, but CPU offload moves model weights to system RAM. Long songs exhaust available memory.
- **Fix:** UI slider capped at 3 min (was 8). API model validates `le=3.0`. Default changed to 2 min.
- **Verified:** 2.5-min (77s gen) and 3-min (93s gen) songs both complete without OOM.
- **To increase:** Add more RAM to ROG-STRIX, or move to a GPU with ≥16GB VRAM (reduces offload to CPU-only, no DiT offload)

### Lyrics Generation Quality
- Ollama (qwen3:4b) generates full song structures: Intro → Verse 1 → Chorus → Verse 2 → Bridge → Outro
- Token limit increased from 512 to 1024 to accommodate longer songs
- All sections properly tagged with [Intro], [Verse 1], [Chorus], [Verse 2], [Bridge], [Outro]
- Genre-appropriate vocabulary and imagery in lyrics

### Cover Art Pipeline: Fully Verified
- Nextcloud Task Processing API (core:text2image) → Visionatrix juggernaut_xl → GTX 1060
- Processing time: ~6 minutes for SDXL on GTX 1060 (6GB VRAM)
- Images downloaded, resized to 512x512, saved as PNG
- Track metadata updated with cover_art filename
- Previous stuck tasks were from orphaned queue entries — cleaned up

### Files Modified
- ui/models.py — duration cap: `le=3.0` (was 8.0)
- ui/static/index.html — slider max=3, default=2, added lyrics SSE event handler
- ui/lyrics_gen.py — num_predict: 1024 (was 512)

---

## Addendum: Comprehensive Duration & Quality Testing (2026-03-04)

### Duration Tests — ALL PASS Up to 8 Minutes

| Duration | Type | Gen Time | Swap Peak | Result |
|----------|------|----------|-----------|--------|
| 3.5 min | Instrumental | ~60s | 10.8 GB | PASS |
| 4.0 min | Instrumental | ~70s | 13.2 GB | PASS |
| 5.0 min | Instrumental | ~90s | 16.2 GB | PASS |
| 6.0 min | Instrumental | ~120s | 15.7 GB | PASS |
| 7.0 min | Instrumental | ~150s | 18.5 GB | PASS |
| 8.0 min | Instrumental | ~180s | 19.1 GB | PASS |
| 4.0 min | Vocals (3v/chorus/bridge/outro) | ~90s | 19.9 GB | PASS |
| 5.0 min | Vocals (3v/chorus/bridge/outro) | ~120s | 18.3 GB | PASS |
| 6.0 min | Vocals (3v/pre-chorus/chorus/bridge/outro) | ~140s | 18.3 GB | PASS |
| 8.0 min | Vocals (3v/chorus/solo/bridge/outro) | ~200s | 17.6 GB | PASS |

System: 14GB RAM + 20GB swap. Earlier OOM was a one-time fluke under heavy memory pressure. All durations up to Tier 4 max (8 min) work reliably.

### Whisper Quality Verification

**8-min Prog Rock (user-provided lyrics, 3 verses + chorus after each + bridge + guitar solo + outro):**
- 39 segments, 35 good quality (89%)
- 100% English confidence
- Whisper transcription matches input lyrics: chorus repeats correctly after every verse
- Minor misheard words normal for AI-generated singing

**5-min Indie Folk (AI-generated lyrics via Ollama qwen3:4b):**
- 47 segments, 46 good quality (97%)
- 100% English confidence
- Complete song structure: Intro → V1 → Chorus → V2 → Chorus → V3 → Bridge → Chorus → Outro
- Chorus repeats identically as instructed
- Whisper transcription matches generated lyrics near-perfectly

### Lyrics Prompt Update
- Old: "Write 2-3 verses, a chorus that repeats"
- New: Explicit structure template requiring chorus after every verse, 3 verses, bridge, intro/outro
- num_predict: 1024 tokens (supports songs up to 8 min)
- Typical output: 1200-1500 chars, 30-40 lines

### UI Duration Slider
- Restored to max=8 minutes (no arbitrary cap)
- Default: 3 minutes
- Step: 0.5 minutes

### Files Modified
- ui/lyrics_gen.py — improved prompt (explicit repeating chorus), num_predict=1024
- ui/models.py — duration le=8.0 (restored from 3.0)
- ui/static/index.html — slider max=8 (restored)


---

## Addendum 4: Disconnect-Safe Generation & Seek Bar Fixes (2026-03-05)

### Problem 1: SSE Stream Disconnect Loses Generation
NPM proxy has a ~60s read timeout on SSE connections. For songs taking >60s to generate (most 3+ min songs), the SSE stream disconnects mid-generation. The old architecture ran the entire generation inside the SSE generator function — when the client disconnected, the generator stopped, and the completed audio was never saved.

### Fix: Independent Generation Task with Queue
Rewrote `/generate-stream` to decouple generation from SSE delivery:
1. Generation runs as an **independent asyncio task** (not inside the SSE generator)
2. Events are pushed to an **asyncio.Queue**
3. SSE generator reads from the queue
4. If client disconnects, the queue just fills up — generation task keeps running
5. Track is **always saved to history** when generation completes, regardless of client state
6. Cover art task also launches independently

Key code: `_run_generation()` async task in `main.py`, `_jobs` dict tracks in-flight jobs.

### Problem 2: Audio Seek Bar Not Draggable
Users couldn't seek (jump to position) in playing audio. Two root causes:
1. **No HTTP Range support:** FastAPI's FileResponse goes through NPM proxy which strips Range headers. Browser must download entire FLAC before seeking works.
2. **CSS pseudo-element override:** `.seek-range::-webkit-slider-runnable-track` had no explicit background, so Chrome painted a default element over the gradient fill from `updateSeekFill()`.

### Fix: Range Requests + CSS
1. Added manual Range request handling in `/audio/{filename}` endpoint — parses `Range: bytes=start-end` header, returns HTTP 206 with `Content-Range` header and chunked streaming response
2. Added `background:transparent` to `::webkit-slider-runnable-track` CSS

### Verification
- Generated "Miles Away" (4 min, custom lyrics) — client disconnected after 30s, track still saved to history
- Generated "Golden Hour" (3 min, AI lyrics via Ollama) — same disconnect-safe behavior confirmed
- Range requests: `curl -H "Range: bytes=0-1023"` returns HTTP 206 with correct Content-Range header
- All 47 unit+API tests pass

### Files Modified
- `ui/main.py` — Rewrote generate-stream with independent task + queue pattern, added Range request handling
- `ui/static/index.html` — CSS fix for seek bar track background

---

## Addendum 5: Library Tab System, Genre Test Battery, and Album Generation (2026-03-05)

### Library Tab System — DEPLOYED

Rewrote library.html with full Suno-inspired tab system:

**Songs Tab:**
- Filter chips: All / Instrumental / Vocals
- Heart button (♡/♥) on every card for favorite toggle
- "+" button to add songs to playlists
- Search and sort preserved

**Playlists Tab:**
- Create, view, manage playlists
- Playlist cards with gradient covers and track counts
- Click playlist to see tracks, remove tracks
- Create Playlist modal

**Favorites Tab:**
- Dedicated view of favorited tracks
- Own search and sort controls

**New API Endpoints:**
- `POST /track/{id}/favorite` — toggle favorite
- `GET /playlists` — list all playlists
- `POST /playlists` — create playlist
- `DELETE /playlists/{id}` — delete playlist
- `POST /playlists/{id}/tracks` — add track to playlist
- `DELETE /playlists/{id}/tracks/{track_id}` — remove from playlist
- `GET /history?filter=all|favorites|instrumental|vocals` — filter support

**Files Modified:**
- `ui/models.py` — Added `favorite: bool = False` to TrackMeta, new Playlist + PlaylistResponse models
- `ui/history.py` — Added toggle_favorite(), playlist CRUD (playlists.json storage)
- `ui/config.py` — Added PLAYLISTS_FILE
- `ui/main.py` — 6 new endpoints, updated /history with filter param
- `ui/static/library.html` — Complete rewrite with tab system

### Genre Test Battery — 10 Diverse Songs

Generated 10 songs across different genres to stress-test ACE-Step:

| Song | Genre | Duration | Vocals | Result |
|------|-------|----------|--------|--------|
| Velvet Thunder | Orchestral rock | 5 min | Instrumental | Pass |
| Neon Heartbeat | Synthwave | 4 min | AI vocals | Pass |
| Whiskey and Wildflowers | Country folk | 4 min | AI vocals | Pass |
| Concrete Jungle | Hip hop | 4 min | AI vocals | Pass |
| Smoke and Mirrors | Jazz | 6 min | Instrumental | Pass |
| Echoes of Atlantis | Ambient | 7 min | Instrumental | Pass |
| Iron Cathedral | Prog metal | 8 min | AI vocals | Pass |
| Requiem for the Stars | Classical | 6 min | Instrumental | Pass |
| Midnight Salsa | Latin | 5 min | AI vocals | Pass |
| Purple Haze Sunday | Blues rock | 5 min | AI vocals | Pass |

**Key findings:**
- All genres produce coherent output
- Generation time: 144-221s per track
- Ollama (qwen3:4b) generates themed lyrics matching each genre
- 8 min is the practical max (swap peaks at ~19GB)

### "Unbreakable Fire" Album — 15-Track Christian Rock

Full Skillet-style Christian rock album with theologically accurate lyrics:

| # | Title | BPM | Key | Duration | Theme |
|---|-------|-----|-----|----------|-------|
| 1 | Unbreakable Fire | 150 | Em | 4:00 | Spiritual warfare, Holy Spirit |
| 2 | Warriors Cry | 140 | Dm | 4:00 | Armor of God (Eph 6) |
| 3 | Still Standing | 130 | Am | 4:30 | More than conquerors (Rom 8:37) |
| 4 | Scars of Grace | 85 | G | 5:00 | Strength in weakness (2 Cor 12:9) |
| 5 | Rise From the Ashes | 155 | Em | 4:00 | Resurrection, new creation |
| 6 | The Void Inside | 120 | Bm | 4:30 | Only Christ fills void (Eccl) |
| 7 | Breaking Chains | 160 | Cm | 3:30 | Freedom in Christ (Gal 5:1) |
| 8 | Light in the Dark | 90 | D | 5:00 | Psalm 23, hope |
| 9 | Fortress | 145 | Em | 4:00 | God as refuge (Ps 18:2) |
| 10 | Dead Man Walking | 135 | Am | 4:00 | Dead in sin, alive (Eph 2:1-5) |
| 11 | Surrender | 95 | F | 5:00 | Total surrender (Isa 40:31) |
| 12 | Battle Ready | 165 | Dm | 3:30 | Be vigilant (1 Pet 5:8) |
| 13 | Through the Storm | 125 | Gm | 4:30 | Peace be still (Mark 4:39) |
| 14 | Redemption Road | 110 | C | 5:00 | Prodigal son (Rom 8:28) |
| 15 | Eternal | 100 | E | 5:30 | New heaven/earth (Rev 21) |

**Total runtime:** 66 minutes
**All 15 covers:** Generated via Visionatrix SDXL
**Playlist:** Created "Unbreakable Fire" with all 15 tracks in order
**Description template used:** "Christian rock, [subgenre] with [instruments], [vocal style]. Think Skillet [reference]. Themes of [theological concept], [Scripture reference]."

### Generation Pipeline Lessons

**Sequential generation is critical:** ACE-Step processes one song at a time on GPU. Parallel requests cause 502 errors. Solution: server-side Python script that generates tracks one by one.

**Server-side script pattern:**
```python
for track in tracks:
    payload = json.dumps({...}).encode()
    req = urllib.request.Request(API + "/generate", data=payload, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=900)
```

**Generation times:** 144-221s per track depending on duration and whether lyrics need to be generated by Ollama first.

**502 error pattern:** When multiple requests hit ACE-Step simultaneously, the Gradio API returns incomplete chunked responses. The UI's httpx client translates this to a 502. Solution: never send concurrent generation requests.

### Whisper Quality Audit Results (2026-03-05)

Ran faster-whisper (medium model, int8, CPU) on all 15 album tracks:

| # | Title | Rating | Segs | Good% | AvgLogProb | Words |
|---|-------|--------|------|-------|------------|-------|
| 1 | Unbreakable Fire | GREAT | 5 | 100% | -0.290 | 21 |
| 2 | Warriors Cry | POOR | 4 | 0% | -0.610 | 28 |
| 3 | Still Standing | POOR | 5 | 0% | -0.373 | 21 |
| 4 | Scars of Grace | GREAT | 4 | 100% | -0.508 | 17 |
| 5 | Rise From the Ashes | GREAT | 7 | 100% | -0.472 | 27 |
| 6 | The Void Inside | GOOD | 1 | 100% | -0.671 | 8 |
| 7 | Breaking Chains | NO VOCALS | 0 | - | - | 0 |
| 8 | Light in the Dark | GREAT | 3 | 100% | -0.530 | 16 |
| 9 | Fortress | POOR | 7 | 0% | -0.437 | 54 |
| 10 | Dead Man Walking | GREAT | 2 | 100% | -0.411 | 13 |
| 11 | Surrender | POOR | 7 | 0% | -0.327 | 50 |
| 12 | Battle Ready | NO VOCALS | 0 | - | - | 0 |
| 13 | Through the Storm | POOR | 4 | 0% | -0.694 | 18 |
| 14 | Redemption Road | POOR | 1 | 0% | -0.546 | 8 |
| 15 | Eternal | POOR | 2 | 0% | -0.822 | 10 |

**Distribution:** GREAT=5, GOOD=1, FAIR=0, POOR=7, NO VOCALS=2

**Quality thresholds used:**
- GREAT: good_pct >= 80% AND avg_logprob > -0.6
- GOOD: good_pct >= 60% AND avg_logprob > -0.8
- FAIR: good_pct >= 40%
- POOR: everything else
- Good segment: avg_logprob > -0.8 AND no_speech_prob < 0.5

**Key findings:**
- ~33% tracks have clearly intelligible vocals (GREAT rating)
- ~47% have garbled/unclear vocals (POOR rating)
- ~13% produced instrumental output despite vocal request (160+ BPM tracks)
- Low word counts across the board — even GREAT tracks have 13-27 detected words vs 200+ in input lyrics
- BPM correlation: the two NO VOCALS tracks were the fastest (160, 165 BPM)
- Ballads perform best: Scars of Grace (85 BPM) and Light in the Dark (90 BPM) both GREAT
- Sweet spot for vocals appears to be 85-150 BPM
- Matches ACE-Step docs: Coarse vocal synthesis lacking nuance and stochastic artifacts are expected
- Community consensus: generate 2-4 versions per track and pick the best

**Audit script:** /tmp/audit_album.py (uses faster-whisper medium model on CPU, ~5-10s per track)
