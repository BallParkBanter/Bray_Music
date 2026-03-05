# Bray Music Studio

Custom AI music generation UI built on top of ACE-Step 1.5, running on ROG-STRIX (192.168.1.153).

## Quick Reference

- **Live URL:** https://music.apps.bray.house (NPM proxy → ROG-STRIX:7861)
- **Raw Gradio UI:** http://192.168.1.153:7860 (LAN only, direct access for debugging)
- **ACE-Step REST API:** http://192.168.1.153:8001 (mapped from container port 8000)
- **Custom UI API:** http://192.168.1.153:7861 (FastAPI backend)
- **ACE-Step files on ROG-STRIX:** `/home/bobray/ace-step/`
- **Custom UI code on ROG-STRIX:** `/home/bobray/ace-step/ui/`
- **Output audio:** `/home/bobray/ace-step/outputs/api_audio/` on ROG-STRIX
- **Cover art:** `/home/bobray/ace-step/outputs/covers/` on ROG-STRIX
- **SSH:** `ssh bobray@192.168.1.153`

## Architecture (deployed 2026-03-03)

```
browser → NPM (:443) → bray-music-ui (:7861, FastAPI)
                              ↓ HTTP (Docker network ace-step-net)
                        ace-step (:7860, Gradio)
                              ↓
                        /app/outputs/api_audio/ (FLAC files)
                              ↓
                        bray-music-ui serves history + audio + cover art
```

Cover art generation:
```
bray-music-ui → Nextcloud Task Processing API (core:text2image)
                    ↓
                Visionatrix (SDXL on BrayNextcloudServer GPU)
                    ↓ (or Pillow gradient fallback if Nextcloud unavailable)
                /app/outputs/covers/ (PNG files)
```

## Project Structure

```
Bray_Music/                         ← Local project (mockups + docs)
├── CLAUDE.md                       ← this file
├── mockup/
│   ├── design-glassmorphism-v3.html ← CHOSEN design (deployed)
│   ├── design-glassmorphism-v2.html
│   ├── design-glassmorphism.html
│   ├── design-analog-console.html
│   ├── design-editorial.html
│   ├── music-studio-mockup.html
│   └── bray-music-studio-v1.html
├── docs/
│   ├── acestep-as-built.md         ← ACE-Step installation & patch docs
│   └── custom-ui-design.md         ← UI design decisions & feature mapping
```

```
/home/bobray/ace-step/              ← On ROG-STRIX (live deployment)
├── docker-compose.yml              ← ace-step + ui services
├── .env                            ← NEXTCLOUD_PASS, NEXTCLOUD_USER
├── Dockerfile                      ← ACE-Step Pascal build
├── start.sh                        ← ACE-Step entrypoint
├── validate.py                     ← Deployment health check
├── outputs/
│   ├── api_audio/                  ← Generated FLAC files
│   ├── covers/                     ← Generated cover art PNGs
│   └── history.json                ← Track metadata
└── ui/
    ├── Dockerfile                  ← python:3.11-slim + deps
    ├── requirements.txt
    ├── config.py                   ← env var loading
    ├── models.py                   ← Pydantic request/response schemas
    ├── gradio_client.py            ← ACE-Step Gradio API wrapper
    ├── cover_art.py                ← Nextcloud task API + Pillow fallback
    ├── history.py                  ← history.json CRUD (async file locking)
    ├── main.py                     ← FastAPI app (all endpoints)
    ├── pytest.ini
    ├── static/
    │   └── index.html              ← Glassmorphism v3 with real JS
    └── tests/
        ├── conftest.py
        ├── unit/
        │   ├── test_gradio_client.py
        │   ├── test_cover_art.py
        │   └── test_history.py
        ├── api/
        │   └── test_endpoints.py
        └── integration/
            └── test_integration.py
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve index.html |
| POST | `/generate` | Generate a song (calls ACE-Step, saves to history) |
| GET | `/history?sort=&search=` | List tracks (newest/oldest, search by title/desc) |
| GET | `/track/{id}` | Get single track metadata |
| DELETE | `/track/{id}` | Delete track + audio + cover |
| GET | `/audio/{filename}` | Serve FLAC file |
| GET | `/cover/{filename}` | Serve cover art PNG |
| GET | `/health` | Health check (ACE-Step reachable, outputs writable) |

## Key Technical Facts

- ACE-Step 1.5 runs on **GTX 1080 Ti (11 GB, Pascal sm_61)**
- 5 patches were required for Pascal — see `docs/acestep-as-built.md`
- Max song duration: **480 seconds (8 minutes)**
- Default audio format: **FLAC, 48kHz lossless**
- Language model: **0.6B** (1.7B caused OOM)
- Cover art: Nextcloud `core:text2image` → Visionatrix SDXL, Pillow gradient fallback
- Credentials: Nextcloud app password "BrayMusicStudio" (stored in Nextcloud Notes, note 2200569)

## Container Management

```bash
ssh bobray@192.168.1.153
cd /home/bobray/ace-step

# Status
docker ps | grep -E 'ace-step|bray-music'
docker logs bray-music-ui --tail 30
docker logs ace-step --tail 30

# Restart UI only
docker compose restart ui

# Rebuild UI after code changes
docker compose build ui && docker compose up -d ui

# Rebuild everything
docker compose up --build -d

# Run tests
docker exec bray-music-ui python -m pytest tests/unit tests/api -v

# Run integration tests (requires ACE-Step loaded)
docker exec bray-music-ui python -m pytest tests/integration -v -m integration

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
| nginx conf | `/data/nginx/proxy_host/37.conf` |

## Troubleshooting

### UI not loading
```bash
docker logs bray-music-ui --tail 30
curl http://localhost:7861/health
```

### ACE-Step unreachable (health shows "unreachable")
```bash
docker logs ace-step --tail 30
# ACE-Step takes 60-90s to load LM tokenizer after restart
# Wait and re-check health
```

### Cover art not generating
- Check Nextcloud app password is valid
- Check Visionatrix is running on BrayNextcloudServer
- Pillow fallback should always produce a gradient cover

### music.apps.bray.house unreachable
```bash
ssh bobray@192.168.1.103
docker exec npm-app-1 nginx -t
docker exec npm-app-1 nginx -s reload
```
