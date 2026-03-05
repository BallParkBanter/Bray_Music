# Exported Memories from nextcloud-mcp project — 2026-03-05

These are all the accumulated memories from Claude Code sessions in the `nextcloud-mcp` project,
exported during the Bray Music Studio reorganization. BMS-specific memories were moved to
`~/projects/Bray_Music/docs/` and the nextcloud-mcp MEMORY.md was trimmed.

## Memories that were moved to Bray_Music/docs/

- `ace-step-validation.md` → `docs/ace-step-validation.md` (validation methodology, whisper results, quality params)
- `bms-quality-findings.md` → `docs/quality-findings.md` (album audit results, BPM vs quality patterns)

## BMS-specific memories that were in MEMORY.md (now replaced with pointer)

### ACE-Step Audio Generation — WORKING on GPU (native install, 2026-03-04)

- URL: https://music.apps.bray.house -> ROG-STRIX (192.168.1.153:7861 via NPM proxy host 37)
- Installation: Native at `/home/bobray/ACE-Step-1.5/` (cloned from GitHub)
- Service: systemd `acestep.service` — auto-starts on boot
  - ExecStart: `/home/bobray/.local/bin/uv run acestep --server-name 0.0.0.0 --port 7860 --init_service true`
  - Config: `/home/bobray/ACE-Step-1.5/.env`
  - Logs: `journalctl -u acestep -f`
  - Commands: `sudo systemctl start|stop|restart|status acestep`
- PyTorch: 2.6.0+cu124 (pyproject.toml modified — default cu128 dropped Pascal sm_61 support)
- GPU Tier 4 auto-config: DiT turbo (8 steps), 0.6B LM (pt backend), INT8 quant, SDPA attention, CPU+DiT offload
- No manual patches needed — GPU tier system handles Pascal automatically. Only fix was cu124 torch pin.
- Gradio API: 55 params (50 reported + 5 hidden State components). State at pos 37, States 2-5 at pos 51-54.
- Performance: 60-200s generation, FLAC 48kHz. Full 8-min Tier 4 max works (14GB RAM + 20GB swap).
- Duration tests verified: 3.5-8 min instrumental + 4-8 min with vocals all pass. Swap peaks at ~19GB for 8-min songs.
- Models: checkpoints/ — turbo, base, sft, 0.6B LM, 4B LM

### Bray Music Studio — DEPLOYED (2026-03-04, updated 2026-03-05)

- URL: https://music.apps.bray.house | Library: /library
- UI container: `bray-music-ui` (FastAPI :7861) — Docker, connects to native ACE-Step via `http://host.docker.internal:7860`
- UI code: `/home/bobray/ace-step/ui/` (deployed), source of truth: `~/projects/Bray_Music/ui/`
- docker-compose: `/home/bobray/ace-step/docker-compose.yml` — only `ui` service (ace-step service removed, now native)
- Cover art: Nextcloud Task Processing API (`core:text2image`) -> Visionatrix SDXL on GTX 1060 (~6 min). Pillow gradient fallback (600s timeout).
- Cover art verified: Task scheduling -> Visionatrix juggernaut_xl -> poll status -> download image -> resize 512x512 -> save PNG.
- Cover art gotcha: Visionatrix tasks_queue gets orphaned entries if tasks_details are deleted. Clean both tables + task_locks.
- Credentials: Nextcloud app password "BrayMusicStudio" in `.env` at `/home/bobray/ace-step/.env`
- Tests: 47 unit+API tests pass (`docker exec bray-music-ui python -m pytest tests/unit tests/api -v`)
- Param mapping: include_vocals=False -> lyrics="[Instrumental]", enhance_lyrics -> CaptionRewrite(api[35]), creativity 0-100 -> guidance 10.0-1.5
- CaptionRewrite (api[35]): ONLY rewrites caption text, does NOT generate lyrics. AutoGen (api[49]) just auto-starts next batch. NEITHER generates lyrics.
- Simple Mode lyrics: Ollama on Optimus (192.168.1.145:11434, qwen3:4b) generates lyrics BEFORE ACE-Step generation. 90s timeout, 1024 token limit.
- Lyrics prompt: Explicit structure: Intro(2) -> V1(4) -> Chorus(4) -> V2(4) -> Chorus -> V3(4) -> Bridge(4) -> Chorus -> Outro(2).
- Quality verified: 8-min song = 89% good segments (Whisper), 5-min AI lyrics = 97% good.
- Streaming: `/generate-stream` SSE endpoint: step events (lyrics/submit/queue/generate/decode/save/validate/cover), lyrics text event, progress messages, track data, errors
- Disconnect-safe generation: Generation runs as independent asyncio task with queue. SSE stream reads from queue.
- HTTP Range support: Audio endpoint handles Range requests (HTTP 206) for seekable playback.
- Seek bar CSS fix: Added `background:transparent` to `.seek-range::-webkit-slider-runnable-track`
- UI modes: Simple (Suno-style) + Custom (full controls). Toggle in header.
- NPM proxy host 37: 192.168.1.153:7861
- Song detail page: `/song/{track_id}` — glassmorphism page with cover art, lyrics, player, download/delete/remix
- Library tab system: Songs (filter chips: All/Instrumental/Vocals) | Playlists | Favorites
- Batch generation: Sequential server-side script required. Parallel curl requests cause 502 errors.
- Quality audit: faster-whisper medium model (CPU, int8) — ~5s/track
  - Thresholds: GREAT (80%+ good, avgLP > -0.6), GOOD (60%+, > -0.8), FAIR (40%+), POOR (rest)
  - Good segment: avg_logprob > -0.8 AND no_speech_prob < 0.9 (relaxed for music context)
  - BPM matters: 160+ BPM -> often no vocals. Sweet spot 85-150 BPM for vocals.

### Features added 2026-03-05

- Saved generation params (bpm, key, creativity, include_vocals, enhance_lyrics) on TrackMeta
- Whisper validation micro-service (port 7862, systemd `whisper-service.service`)
  - VAD filter disabled (kills all music segments), no_speech_prob threshold 0.9 (not 0.5)
- Conditional cover art: instrumental/GOOD/GREAT -> AI cover, FAIR/POOR -> gradient only
- Song detail page: Generation Settings section + quality badge
- Remix button: pre-fills Custom mode form via URL params
- Quality badges on library cards

## Non-BMS memories still in nextcloud-mcp MEMORY.md

These remain in the nextcloud-mcp project memory (infrastructure/server knowledge):

- BrayNextcloudServer GPU setup, AppAPI, Visionatrix, Nextcloud app config, Talk push notifications
- Optimus server details
- ROG-STRIX hardware/software
- Chrome headless screenshot gotcha
- SSL cert renewal schedule
