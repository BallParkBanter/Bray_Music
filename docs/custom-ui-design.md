# Bray Music Studio — Custom UI Design Document

**Status:** DEPLOYED — live at https://music.apps.bray.house
**Date:** 2026-03-04 (updated: native ACE-Step install, reconnected UI)

---

## Overview

The goal is a custom, easy-to-use web interface at `music.apps.bray.house` that wraps ACE-Step's complex Gradio UI. The raw Gradio UI remains accessible at `http://192.168.1.153:7860` for power users and debugging.

---

## Design Philosophy

- **Dark theme always** — non-negotiable
- **Ubuntu font everywhere**
- **Fun, like the Suno app** — colorful, animated, exciting to use
- **Plain English** — all ACE-Step's technical jargon is relabeled
- **Tooltips** — every non-obvious control has a hover tooltip in plain English
- **Prominent controls front-and-center** — advanced options tucked away but accessible
- **History is a first-class feature** — browse, play, download, delete all past generations

---

## Mockup Files

All in `mockup/` directory:

| File | Style | Layout | Theme |
|---|---|---|---|
| `bray-music-studio-v1.html` | Neon/vivid with theme switcher | 3-column | 5 themes (Neon, Cyber, Fire, Emerald, Gold) |
| `design-glassmorphism.html` | Frosted glass, animated gradient blobs | 3-column | Purple/pink, blurry translucent panels |
| `design-analog-console.html` | Analog studio hardware, VU meters | 3-column | Charcoal + amber phosphor + green LEDs |
| `design-editorial.html` | Bold print/magazine, high contrast | 2-column (wide left + dark right) | White + black + red accent |

### v1 (Main Mockup) Features
- 5 theme swatches in header (full theme switching via JS CSS variables)
- Animated waveform bars in Now Playing
- Colorful gradient album art thumbnails in history (each genre gets its own gradient)
- Collapsible Advanced Options panel
- Quick Style genre presets (fill description field with genre-appropriate prompt)
- Instrumental toggle (hides/shows lyrics field)
- Duration slider (1–8 min)
- AI Lyric Enhancer toggle
- Generation seed with dice button

---

## Feature Mapping: Gradio → Plain English

| ACE-Step Label | Bray Music Studio Label | Plain English Tooltip |
|---|---|---|
| Prompt | Describe your song | Tell the AI what kind of song you want — style, mood, instruments, energy |
| Lyrics | Lyrics | Write your own lyrics, or leave blank and AI will write them |
| Audio Duration | Song Length | How long your song should be (1–8 minutes) |
| Guidance Scale | AI Creativity | How closely AI follows your description. Lower = more creative, higher = more literal |
| Infer Steps | Quality | More steps = better quality but slower. Default is fine for most songs |
| Seed | Generation Seed | Same seed + same settings = same song. Use for regenerating variations |
| Auto Score | Auto Chord Notation | Automatically adds musical chord symbols to the output |
| AutoGen | Auto-Generate Lyrics | Let AI write lyrics from scratch based on your description |
| Auto LRC | Auto-Generate Timed Lyrics | Creates a synced lyrics file (.lrc) for karaoke-style display |
| Think | AI Thinks First | Gives the AI extra time to plan the song structure before generating. Slower but often better |
| Send to Remix | Send to Remix | Take this song and use it as the starting point for a new variation |
| Send to Repaint | Send to Repaint | Regenerate specific parts of the song while keeping other parts the same |
| LM Codes Strength | Melody Control | How strongly the language model guides the musical structure (advanced) |
| Generation Mode | Generation Mode | Standard vs. special generation algorithms (leave as default unless experimenting) |
| Enhance Lyrics | Polish My Lyrics | Let AI improve and refine your written lyrics before generating the song |
| 🎲 (dice icon) | 🎲 | Click to pick a random seed — each click will generate a different variation |
| Click Me | Try a Random Example | Click to fill all fields with a random preset example song to try |
| Instrumental | Instrumental (No Vocals) | Generate music only — no singing or lyrics |

---

## Layout: 3-Column Design

```
┌──────────────────────────────────────────────────────────────────────┐
│  [🎵 Bray Music Studio]          [Theme ○○○○○]    [● AI Online]     │
├──────────────┬──────────────────────────────┬───────────────────────┤
│ LEFT         │ CENTER                       │ RIGHT                 │
│              │                              │                        │
│ Quick Style  │ Song Title                   │ ┌─ Now Playing ──────┐ │
│ [Hymns]      │                              │ │  [Album Art]       │ │
│ [Christian]  │ Describe your song           │ │  Waveform ~~~      │ │
│ [Rock]       │ [textarea]                   │ │  ▶ Controls        │ │
│ [Rock/Rap]   │                              │ └────────────────────┘ │
│ [Pop]        │ Lyrics                       │                        │
│ [Country]    │ [textarea]                   │ Search [         ]     │
│ [Acoustic]   │                              │ Sort [Newest ▼]       │
│ [Custom]     │ AI Lyric Polish [toggle]     │                        │
│              │                              │ ┌ Song Card ────────┐ │
│ Vocals [on]  │ [✨ Generate Song]           │ │ 🎵 Amazing Grace  │ │
│              │ [progress bar]               │ │ Hymns · 3:42 FLAC │ │
│ Duration     │ [status message]             │ │ ▶ ↓ 🗑            │ │
│ [3 min ----] │                              │ └───────────────────┘ │
│              │                              │ ... more cards ...    │
│ [Advanced ▼] │                              │                        │
└──────────────┴──────────────────────────────┴───────────────────────┘
```

---

## Backend Architecture (DEPLOYED)

### Technology Stack

- **Backend:** FastAPI (Python) in Docker container `bray-music-ui` on ROG-STRIX
- **Custom UI port:** 7861
- **ACE-Step:** Native install with systemd service on port 7860
- **NPM proxy host 37:** music.apps.bray.house → 192.168.1.153:7861

### How It Works

```
User browser
     │
     ▼
NPM: music.apps.bray.house:443
     │
     ▼
Docker: bray-music-ui (ROG-STRIX:7861)
     │  serves: static HTML/CSS/JS
     │  POST /generate → calls Gradio API via host.docker.internal:7860
     │  GET /history → returns JSON from history.json
     │  GET /audio/<filename> → serves FLAC file
     │  GET /cover/<filename> → serves cover art PNG
     │
     ├──→ ACE-Step native (systemd, :7860) for generation
     ├──→ Nextcloud Task Processing API for AI cover art (Visionatrix SDXL)
     └──→ ./outputs/ volume for audio + covers + history.json
```

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Main song creation page |
| `/library` | GET | Full-screen library/history page |
| `/generate` | POST | Accepts UI parameters, calls Gradio API, returns TrackMeta |
| `/history` | GET | Returns JSON with tracks, supports ?search= and ?sort= |
| `/audio/<filename>` | GET | Serves FLAC file for playback or download |
| `/cover/<filename>` | GET | Serves cover art PNG |
| `/track/<id>` | GET | Get single track metadata |
| `/track/<id>` | DELETE | Removes track from history + deletes FLAC + cover |
| `/health` | GET | ACE-Step reachability, GPU status, outputs writable |

### Generation Parameters (UI → Gradio mapping)

```python
# UI sends plain English params via POST /generate
{
    "title": "My Song",
    "description": "Acoustic pop, fingerpicked guitar...",
    "lyrics": "[Verse 1]\nWake up...",
    "duration": 0,           # 0 = auto (LM decides), 1-8 = minutes
    "include_vocals": true,  # false → lyrics="[Instrumental]"
    "enhance_lyrics": false, # true → CaptionRewrite in Gradio API
    "bpm": "120",
    "key": "G major",
    "creativity": 50,        # 0-100 → guidance scale 10.0-1.5
    "seed": ""               # empty = random
}
```

### History Persistence

- All generated FLAC files in `./outputs/api_audio/`
- Cover art PNGs in `./outputs/covers/`
- History metadata in `./outputs/history.json`
- Search/sort/play/download/delete from UI
- Nothing is auto-deleted
- 41 unit + API tests verify all endpoints

---

## Quick Style Presets (prompts used)

| Genre | Prompt injected into description field |
|---|---|
| Hymns | "Peaceful hymn, sacred choral voices, organ, gentle orchestral, reverent and uplifting" |
| Christian | "Contemporary Christian worship, uplifting piano, acoustic guitar, heartfelt vocals" |
| Rock | "Electric guitar driven rock, powerful drums, energetic riffs, stadium anthem" |
| Rock/Rap | "Hip-hop and rock fusion, heavy beats, rap verses, electric guitar hooks" |
| Pop | "Catchy pop melody, upbeat synth, polished production, bright hooky chorus" |
| Country | "Country guitar, warm fiddle, heartfelt storytelling vocals, Nashville sound" |
| Acoustic | "Fingerpicked acoustic guitar, intimate vocals, gentle melody, singer-songwriter" |
| Custom | (clears description, user types their own) |

---

## Accessing Raw Gradio UI

The original ACE-Step Gradio interface is always available at:

- **Direct (LAN only):** http://192.168.1.153:7860
- Not proxied through NPM — custom UI at music.apps.bray.house is the public interface

The raw Gradio UI exposes all of ACE-Step's original controls including advanced features not surfaced in the custom UI (remix, repaint, Auto Score, etc.).

---

## Deployment Files

All live code on ROG-STRIX at `/home/bobray/ace-step/ui/`:

| File | Purpose |
|---|---|
| `config.py` | Environment variable loading |
| `models.py` | Pydantic request/response schemas |
| `gradio_client.py` | ACE-Step Gradio API wrapper (55-param mapping) |
| `cover_art.py` | Nextcloud Task Processing API + Pillow fallback |
| `history.py` | history.json CRUD with async file locking |
| `main.py` | FastAPI app (all endpoints) |
| `static/index.html` | Song creation page (glassmorphism design) |
| `static/library.html` | Full-screen library page |
| `Dockerfile` | Python 3.11-slim + DejaVu fonts |
| `requirements.txt` | FastAPI, httpx, Pillow, aiofiles, etc. |
| `tests/` | 41 unit + API tests |

Docker compose at `/home/bobray/ace-step/docker-compose.yml` (only `ui` service, ACE-Step is native)
