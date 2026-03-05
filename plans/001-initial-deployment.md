# Plan 001: Initial Bray Music Studio Deployment

**Date:** 2026-03-04
**Status:** Completed

## Summary

Build a web UI ("Bray Music Studio") for ACE-Step AI music generation running on ROG-STRIX (192.168.1.153). FastAPI backend connects to native ACE-Step Gradio API. Cover art via Nextcloud Task Processing API (Visionatrix SDXL).

## Architecture

- **ACE-Step**: Native install at `/home/bobray/ACE-Step-1.5/`, systemd `acestep.service`, port 7860
- **UI**: Docker container `bray-music-ui` (FastAPI, port 7861), connects to ACE-Step via `host.docker.internal:7860`
- **Cover Art**: Nextcloud Task Processing → Visionatrix juggernaut_xl on GTX 1060 (~6 min)
- **Reverse Proxy**: NPM proxy host 37 → `https://music.apps.bray.house`

## Features Delivered

1. Simple mode (Suno-style: describe what you want) + Custom mode (full controls)
2. Ollama lyrics generation (qwen3:4b on Optimus) for Simple mode
3. AI cover art via Nextcloud/Visionatrix with Pillow gradient fallback
4. Song history with library (songs/playlists/favorites tabs)
5. Song detail page with glassmorphism design
6. SSE streaming for generation progress
7. Disconnect-safe generation (runs as independent asyncio task)
8. HTTP Range support for seekable audio playback
9. Batch generation support (sequential, server-side)

## Key Decisions

- Native ACE-Step (not Docker) — needed cu124 PyTorch pin for Pascal GPU
- Docker UI container connects to host services via `host.docker.internal`
- FLAC 48kHz output format
- Gradient fallback for cover art (600s Visionatrix timeout)
- Playlists stored in `playlists.json` (file-based, simple)
