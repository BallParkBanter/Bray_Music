# Bray Music Studio

Custom AI music generation UI built on top of ACE-Step 1.5, running on ROG-STRIX (192.168.1.153).

## Quick Reference

- **Live URL:** https://music.apps.bray.house (NPM proxy → ROG-STRIX:7861)
- **Raw Gradio UI:** http://192.168.1.153:7860 (LAN only, direct access for debugging)
- **ACE-Step REST API:** http://192.168.1.153:8001 (mapped from container port 8000)
- **Custom UI API:** http://192.168.1.153:7861 (FastAPI backend)
- **Cover art service:** http://192.168.1.153:7863 (DreamShaper XL, systemd `cover-art-service.service`)
- **ACE-Step native install:** `/home/bobray/ACE-Step-1.5/` on ROG-STRIX (systemd `acestep.service`)
- **Deployment dir on ROG-STRIX:** `/home/bobray/ace-step/` (docker-compose, .env, outputs)
- **Output audio:** `/home/bobray/ace-step/outputs/api_audio/` on ROG-STRIX
- **Cover art:** `/home/bobray/ace-step/outputs/covers/` on ROG-STRIX
- **SSH:** `ssh bobray@192.168.1.153`

## Architecture

```
browser → NPM (:443) → bray-music-ui (:7861, FastAPI Docker)
                              ↓ HTTP (host.docker.internal:7860)
                        ACE-Step (:7860, native Gradio, systemd)
                              ↓
                        /home/bobray/ace-step/outputs/api_audio/ (FLAC files)
                              ↓
                        bray-music-ui serves history + audio + cover art
```

Cover art generation:
```
bray-music-ui → cover-art-service (:7863, native FastAPI, systemd)
                    ↓ DreamShaper XL (SDXL) on local GTX 1080 Ti (~32s)
                    ↓ (or Pillow gradient fallback if service unavailable)
                /home/bobray/ace-step/outputs/covers/ (PNG files)
```

Whisper validation (post-generation):
```
bray-music-ui → whisper-service (:7862, native FastAPI, systemd)
                    ↓ faster-whisper medium/int8/CPU
                quality_score + quality_rating → TrackMeta
```

## Project Structure

```
Bray_Music/                            ← Git repo (source of truth)
├── CLAUDE.md                          ← this file
├── docker-compose.yml                 ← UI service definition
├── validate.py                        ← Deployment health check
├── AS-BUILT.md                        ← System documentation
├── whisper_service.py                 ← Whisper validation micro-service
├── cover_art_service.py               ← DreamShaper XL cover art micro-service
├── cover-art-service.service          ← systemd unit for cover art service
├── plans/
│   ├── 001-initial-deployment.md      ← Original BMS deployment plan
│   ├── 002-validation-params-remix.md ← Validation, saved params, remix
│   └── 003-resilience-and-quality.md ← Retry, stats, cooldown, uptempo lyrics
├── docs/
│   ├── acestep-as-built.md            ← ACE-Step installation & patch docs
│   ├── custom-ui-design.md            ← UI design decisions
│   ├── ace-step-validation.md         ← Validation methodology & results
│   ├── quality-findings.md            ← Album quality audit findings
│   ├── cover-art-options.md           ← Cover art model research & options
│   ├── acestep/                       ← ACE-Step 1.5 official docs (from GitHub)
│   ├── dreamshaper-xl/                ← DreamShaper XL model guide & settings
│   └── juggernaut-xl/                 ← Juggernaut XL docs (kept for reference)
├── mockup/
│   ├── design-glassmorphism-v3.html   ← CHOSEN design (deployed)
│   └── ...                            ← Other design explorations
└── ui/
    ├── Dockerfile                     ← python:3.11-slim + deps
    ├── requirements.txt
    ├── config.py                      ← env var loading
    ├── models.py                      ← Pydantic request/response schemas
    ├── gradio_client.py               ← ACE-Step Gradio API wrapper
    ├── cover_art.py                   ← Local cover art service client + Pillow fallback
    ├── history.py                     ← history.json CRUD (async file locking)
    ├── lyrics_gen.py                  ← Ollama lyrics generation
    ├── validation.py                  ← Whisper service HTTP client
    ├── stats.py                       ← Generation statistics tracking
    ├── main.py                        ← FastAPI app (all endpoints)
    ├── static/
    │   ├── index.html                 ← Main UI (Simple + Custom modes)
    │   ├── library.html               ← Library (songs/playlists/favorites)
    │   └── song.html                  ← Song detail page
    └── tests/
        ├── conftest.py
        ├── unit/
        ├── api/
        └── integration/
```

## Plans

Plans are numbered and never overwritten. Each plan captures the design at the time of implementation.

- `plans/001-initial-deployment.md` — Original BMS deployment (completed 2026-03-04)
- `plans/002-validation-params-remix.md` — Validation, saved params, remix features
- `plans/003-resilience-and-quality.md` — ACE-Step retry, stats tracking, uptempo lyrics, generation cooldown

## Development Workflow

**Source of truth:** `~/projects/Bray_Music/` (this repo)
**Deploy to ROG-STRIX:** `scp` updated files, then rebuild Docker

```bash
# Edit locally
cd ~/projects/Bray_Music/ui/
# ... make changes ...

# Deploy
scp -r ui/ bobray@192.168.1.153:/home/bobray/ace-step/ui/
ssh bobray@192.168.1.153 "cd /home/bobray/ace-step && docker compose build ui && docker compose up -d ui"

# Push to remotes
cd ~/projects/Bray_Music
git add -A && git commit -m "description"
git push origin main && git push github main
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve index.html |
| GET | `/library` | Serve library.html |
| GET | `/song/{id}` | Serve song.html |
| POST | `/generate` | Generate a song (JSON body) |
| POST | `/generate-stream` | Generate with SSE progress streaming |
| GET | `/history?sort=&search=&filter=` | List tracks (filter: all/favorites/instrumental/vocals) |
| GET | `/track/{id}` | Get single track metadata |
| POST | `/track/{id}/favorite` | Toggle favorite |
| DELETE | `/track/{id}` | Delete track + audio + cover |
| GET | `/audio/{filename}` | Serve FLAC file (Range support) |
| GET | `/cover/{filename}` | Serve cover art PNG |
| GET | `/playlists` | List all playlists |
| POST | `/playlists` | Create playlist |
| DELETE | `/playlists/{id}` | Delete playlist |
| POST | `/playlists/{id}/tracks` | Add track to playlist |
| DELETE | `/playlists/{id}/tracks/{track_id}` | Remove track from playlist |
| GET | `/health` | Health check |
| GET | `/stats` | Generation statistics |

## Key Technical Facts

- ACE-Step 1.5 runs **natively** (not Docker) on **GTX 1080 Ti (11 GB, Pascal sm_61)**
- PyTorch 2.6.0+cu124 (cu128 dropped Pascal support)
- systemd service: `acestep.service` (auto-starts on boot)
- Max song duration: **480 seconds (8 minutes)**
- Default audio format: **FLAC, 48kHz lossless**
- Language model: **1.7B** (PyTorch backend; vllm/Triton requires CUDA Capability >= 7.0, Pascal is 6.1)
- Cover art: Local Juggernaut XL v9 (SDXL) via `cover-art-service` on port 7863, ~27s per image, Pillow gradient fallback
- Cover art VRAM: 7 GB loaded, 10.3 GB peak. Auto-unloads after 2 min idle to free GPU for ACE-Step
- Cover art prompts: genre-specific visual styles (20 genres) + random art style pool (37 styles) for unknown genres
- Lyrics: Ollama (gemma3:12b on Optimus 192.168.1.145:11434)
- Generation concurrency: `asyncio.Semaphore(1)` prevents concurrent ACE-Step submissions
- Statistics: `stats.py` tracks generation counts, timing, genres, quality ratings (GET /stats)
- Uptempo lyrics: Fast genres (punk/pop/rock/metal/electronic/dance/k-pop) use extended template with pre-chorus + double chorus (~52 lines vs ~36 default)

## Container Management

```bash
ssh bobray@192.168.1.153
cd /home/bobray/ace-step

# Status
docker ps | grep bray-music
docker logs bray-music-ui --tail 30
sudo systemctl status acestep
sudo systemctl status cover-art-service
sudo systemctl status whisper-service

# Restart UI only
docker compose restart ui

# Rebuild UI after code changes
docker compose build ui && docker compose up -d ui

# Run tests (163 tests)
docker exec bray-music-ui python -m pytest tests/unit tests/api -v

# Validate deployment
python3 validate.py
```

## NPM Proxy

NPM is on BrayNextcloudServer (192.168.1.103), container `npm-app-1`.

| Field | Value |
|---|---|
| Proxy Host DB ID | 37 |
| Domain | music.apps.bray.house |
| Forward to | 192.168.1.153:7861 |
| SSL Cert DB ID | 31 (`*.apps.bray.house`) |

## Troubleshooting

### UI not loading
```bash
docker logs bray-music-ui --tail 30
curl http://localhost:7861/health
```

### ACE-Step unreachable
```bash
sudo systemctl status acestep
journalctl -u acestep --tail 30
# ACE-Step takes 60-90s to load LM tokenizer after restart
```

### Cover art not generating
```bash
sudo systemctl status cover-art-service
journalctl -u cover-art-service --tail 30
curl http://localhost:7863/health
```
- Pillow fallback should always produce a gradient cover if service is down

### music.apps.bray.house unreachable
```bash
ssh bobray@192.168.1.103
docker exec npm-app-1 nginx -t
docker exec npm-app-1 nginx -s reload
```
