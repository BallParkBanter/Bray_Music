# Plan 002: Validation, Saved Params, and Remix

**Date:** 2026-03-05
**Status:** In Progress

## Features

### Feature 1 — Save Generation Params to TrackMeta
Add bpm, key, creativity, include_vocals, enhance_lyrics, quality_score, quality_rating fields to TrackMeta in models.py. Wire params in both generate endpoints.

### Feature 2 — Whisper Validation Service
Host-side FastAPI micro-service (port 7862) running faster-whisper medium/int8/CPU. UI container calls it via `host.docker.internal:7862`. Runs after audio save, before cover art. ~5-10s per track.

Quality thresholds:
- GREAT: good_pct >= 80% AND avg_logprob > -0.6
- GOOD: good_pct >= 60% AND avg_logprob > -0.8
- FAIR: good_pct >= 40%
- POOR: everything else
- Good segment: avg_logprob > -0.8 AND no_speech_prob < 0.5

### Feature 3 — Conditional Cover Art
- Instrumental → always AI cover
- Vocal GOOD/GREAT → AI cover
- Vocal FAIR/POOR/None → gradient fallback only

### Feature 4 — Song Detail Display
Show Generation Settings section (BPM, Key, Creativity%, Vocals, AI Polish) + quality badge (color-coded: green/blue/amber/red).

### Feature 5 — Remix/Regenerate
Button on song detail page builds URL params → navigates to `/?title=...&bpm=...`. Index.html reads URL params on load → switches to Custom mode → fills all fields.

## Files Modified

| File | Changes |
|------|---------|
| `ui/models.py` | Add 7 fields to TrackMeta |
| `ui/main.py` | Wire params, validation step, conditional cover art |
| `ui/history.py` | Add `update_quality()` method |
| `ui/config.py` | Add `WHISPER_URL` |
| `ui/validation.py` | **New** — HTTP client for whisper service |
| `ui/static/song.html` | Show all params, quality badge, remix button |
| `ui/static/index.html` | URL param pre-fill for remix, validate step in SSE |
| `ui/static/library.html` | Quality badges on cards |

## New Services

| File | Purpose |
|------|---------|
| `whisper_service.py` (repo root) | Whisper validation micro-service (port 7862) |
| systemd unit on ROG-STRIX | Auto-start whisper service |
