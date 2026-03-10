# Plan 003: Resilience, Quality, and Pipeline Hardening

**Date:** 2026-03-09
**Status:** Completed
**Based on:** `docs/20-song-test-results.md` (20-song generation test, 2026-03-06/07)

## Background

The 20-song stress test revealed a 75% success rate (15/20). All failures were ACE-Step crashes under sustained load, plus cascading "unreachable" errors when the next song hit ACE-Step during restart. Other findings: Ollama cold start can timeout, fast genres produce songs under 3:00, genre detection loses compound qualifiers, and cover art has a "dust motes" repetition habit.

This plan addresses every finding with code changes, and defines end-to-end validation that proves each fix works in the real pipeline — not just in isolation.

---

## Phase 1: ACE-Step Resilience (Highest Priority)

The #1 problem: ACE-Step crashes every 4-5 consecutive generations, and there's no health check, no retry, no backoff. Two separate fixes.

### 1A. ACE-Step Health Check Before Generation

**Problem:** The UI blindly submits to ACE-Step without checking if it's up. Songs #13 and #18 failed because ACE-Step was restarting after a crash.

**Files modified:**
- `ui/gradio_client.py` — add `async def check_health() -> bool` function
- `ui/main.py` — call health check before ACE-Step submission in both `generate()` and `_run_generation()`

**Implementation:**

In `gradio_client.py`, add a health check function:
```python
async def check_health(timeout: float = 5.0) -> bool:
    """Check if ACE-Step Gradio API is reachable and responsive."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{ACESTEP_URL}/gradio_api/info")
            return r.status_code == 200
    except Exception:
        return False
```

In `_run_generation()` (main.py), before the ACE-Step submission block (~line 285), add a health check with wait-and-retry:
```python
# Check ACE-Step health before submitting
for attempt in range(6):  # Up to 6 attempts = ~3 minutes max wait
    if await gradio_client.check_health():
        break
    wait_time = 30
    logger.warning(f"[GEN {track_id[:8]}] ACESTEP: Not reachable, waiting {wait_time}s (attempt {attempt+1}/6)...")
    await emit({"event": "step", "step": "submit", "state": "active",
                "detail": f"Waiting for ACE-Step ({attempt+1}/6)..."})
    await asyncio.sleep(wait_time)
else:
    logger.error(f"[GEN {track_id[:8]}] ACESTEP: Unreachable after 3 minutes of waiting")
    await emit({"event": "error", "message": "ACE-Step is not responding. Please try again in a few minutes."})
    await emit(None)
    return
```

Same pattern in the synchronous `generate()` endpoint, but simpler (just check once, raise 503 if down).

**Validation:**
- [ ] SSH to ROG-STRIX, `sudo systemctl stop acestep`
- [ ] Submit a generation via the UI — confirm it shows "Waiting for ACE-Step" status messages
- [ ] Start ACE-Step back: `sudo systemctl start acestep`
- [ ] Confirm the generation resumes and completes successfully (full song with lyrics, whisper, cover art)
- [ ] Check docker logs for the health check wait messages

### 1B. Auto-Retry on ACE-Step Crash

**Problem:** When ACE-Step crashes mid-generation (the "peer closed connection" error), the song is lost. The user has to manually re-submit.

**Files modified:**
- `ui/main.py` — wrap ACE-Step call in retry logic in `_run_generation()`

**Implementation:**

In `_run_generation()`, wrap the ACE-Step streaming call in a retry loop:
```python
max_retries = 1  # Retry once after crash (total 2 attempts)
for attempt in range(max_retries + 1):
    step_start = time.time()
    result_data = None
    try:
        async for evt in gradio_client.generate_streaming(req, genre_hint=genre_hint):
            await emit(evt)
            if evt.get("event") == "complete":
                result_data = evt["result"]
                # ... existing success logging ...
            elif evt.get("event") == "error":
                # ... existing error logging ...
                break  # Don't return — fall through to retry logic
            elif evt.get("event") == "progress":
                # ... existing progress logging ...
    except Exception as e:
        elapsed = time.time() - step_start
        logger.error(f"[GEN {track_id[:8]}] ACESTEP: Stream error after {elapsed:.1f}s: {e}")

    if result_data:
        break  # Success — exit retry loop

    # Failed — should we retry?
    if attempt < max_retries:
        logger.info(f"[GEN {track_id[:8]}] ACESTEP: Retrying (attempt {attempt+2}/{max_retries+1})...")
        await emit({"event": "step", "step": "submit", "state": "active",
                    "detail": "ACE-Step crashed — waiting for restart, will retry..."})
        # Wait for ACE-Step to restart (systemd auto-restart takes 60-90s)
        for wait_attempt in range(6):
            await asyncio.sleep(30)
            if await gradio_client.check_health():
                logger.info(f"[GEN {track_id[:8]}] ACESTEP: Back online after {(wait_attempt+1)*30}s")
                break
        else:
            logger.error(f"[GEN {track_id[:8]}] ACESTEP: Not recovered after 3 min wait")
            await emit({"event": "error", "message": "ACE-Step crashed and did not recover"})
            await emit(None)
            return
    else:
        # All retries exhausted
        await emit({"event": "error", "message": "Generation failed after retry"})
        await emit(None)
        return
```

**Validation:**
- [ ] Generate 6 songs consecutively (this should trigger the ~5-song crash pattern)
- [ ] When the crash occurs, confirm from docker logs:
  - The error is detected ("peer closed connection")
  - The retry logic kicks in ("Retrying attempt 2/2")
  - The health check polls until ACE-Step is back
  - The song is re-submitted and completes successfully
- [ ] Confirm the final song has: lyrics, title, whisper score, cover art, correct duration
- [ ] Confirm the SSE stream shows the retry status to the user ("ACE-Step crashed — waiting for restart")

---

## Phase 2: Ollama Cold Start Fix

### 2A. Pre-warm Ollama on UI Startup

**Problem:** Song #1 failed because Ollama's gemma3:12b model wasn't loaded. The 90s lyrics timeout wasn't enough for cold-load (40s) + first inference (slow). Title generation was also 3x slower (43.5s vs 15s).

**Files modified:**
- `ui/main.py` — add `@app.on_event("startup")` handler

**Implementation:**

Add a startup event that pre-warms Ollama:
```python
@app.on_event("startup")
async def startup_warmup():
    """Pre-warm Ollama model on UI startup to avoid first-song timeout."""
    logger.info("Startup: Pre-warming Ollama gemma3:12b...")
    try:
        was_cold = await lyrics_gen.ensure_model_loaded()
        if was_cold:
            logger.info("Startup: Ollama model loaded into GPU (cold start)")
        else:
            logger.info("Startup: Ollama model already warm")
    except Exception as e:
        logger.warning(f"Startup: Ollama pre-warm failed (will retry on first generation): {e}")
```

**Validation:**
- [ ] SSH to ROG-STRIX, restart the UI container: `docker compose restart ui`
- [ ] Check docker logs for "Startup: Pre-warming Ollama" and "loaded into GPU" messages
- [ ] Immediately generate a song (within 30s of container start)
- [ ] Confirm lyrics generate successfully (should take 29-37s, NOT timeout)
- [ ] Confirm title generates in ~15s (NOT 43s)
- [ ] SSH to Optimus (192.168.1.145), run `curl http://localhost:11434/api/ps` — confirm gemma3:12b is loaded

---

## Phase 3: Compound Genre Detection

### 3A. Multi-Word Genre Matching

**Problem:** `_extract_genre()` uses first-match keyword scanning. "Country rock" matches "rock" (checked before "country"). "K-pop" matches "pop" (k-pop is checked after pop). "Latin pop" has no "latin pop" keyword.

**Files modified:**
- `ui/main.py` — reorder and expand the `genre_map` list in `_extract_genre()`

**Implementation:**

The fix is to add compound genre keywords at the TOP of the list (before their single-word components) and add missing compound genres:

```python
genre_map = [
    # Compound genres FIRST (before their components)
    (["country rock", "southern rock"], "country rock"),
    (["latin pop"], "latin pop"),
    (["k-pop", "kpop", "k pop"], "k-pop"),
    (["j-pop", "jpop", "j pop"], "j-pop"),
    (["rap battle", "rap song", "rapper", "rapping", "hip hop", "hip-hop", "hiphop", "trap"], "hip hop"),
    (["r&b", "r and b", "rnb", "rhythm and blues"], "r&b"),
    (["edm", "techno", "house music", "trance", "dubstep", "electronic"], "electronic"),
    (["heavy metal", "death metal", "thrash", "metalcore"], "metal"),
    (["punk rock", "punk"], "punk"),
    (["indie rock", "indie pop", "indie"], "indie"),
    (["classic rock", "rock anthem", "rock song", "rock"], "rock"),
    (["pop song", "pop music", "pop anthem", "pop"], "pop"),
    (["jazz"], "jazz"),
    (["classical", "orchestra", "symphon", "orchestral"], "classical"),
    (["folk", "acoustic folk"], "folk"),
    (["country", "honky tonk", "bluegrass"], "country"),
    (["metal"], "metal"),
    (["ambient", "chill", "lo-fi", "lofi"], "ambient"),
    (["blues"], "blues"),
    (["reggae", "reggaeton"], "reggae"),
    (["soul", "motown"], "soul"),
    (["latin", "salsa", "bossa nova"], "latin"),
    (["dance", "disco", "club"], "dance"),
    (["gospel", "worship", "hymn", "praise"], "gospel"),
    (["ballad", "love song", "slow song", "acoustic love"], "ballad"),
    (["anime"], "j-pop"),
]
```

Also need to add the new compound genres to supporting data structures:

- `_GENRE_BPM` in `gradio_client.py` — add `"country rock": 120`, `"latin pop": 105`
- `_emoji_for()` in `main.py` — add `"country rock": "🤠"`, `"latin pop": "💃"`
- `_GENRE_PROMPT_MAP` in `lyrics_gen.py` — no changes needed (compound genres fall back to default prompt, which is fine)

**Validation:**
- [ ] Generate with description "Country rock song about a Friday night bonfire" — confirm genre_hint is "country rock" (not "rock") in docker logs
- [ ] Generate with description "K-pop inspired song about a secret crush" — confirm genre_hint is "k-pop" (not "pop") in docker logs
- [ ] Generate with description "Latin pop song about dancing under the stars" — confirm genre_hint is "latin pop" (not "pop") in docker logs
- [ ] Generate a plain "Rock song about..." — confirm it still detects "rock" correctly
- [ ] Generate a plain "Pop song about..." — confirm it still detects "pop" correctly
- [ ] All 5 validation songs must complete fully (lyrics, title, audio, whisper, cover art)

---

## Phase 4: Cover Art Improvements

### 4A. Diversity Instruction for Ollama Visual Descriptions

**Problem:** Ollama's gemma3:12b uses "dust motes dance" in 4 of 15 descriptions. This creates visual repetition across covers.

**Files modified:**
- `ui/cover_art.py` — update the `_generate_visual_description()` prompt

**Implementation:**

Add a diversity instruction to the existing prompt in `_generate_visual_description()`:
```python
prompt = (
    f"I need a visual scene description for album cover art. "
    f"The song is: {description}. Genre: {genre}. "
    f"Describe a vivid visual SCENE (not music) that captures the mood and subject. "
    f"Focus on imagery: objects, settings, lighting, colors, atmosphere. "
    f"Be original — avoid cliches like 'dust motes dance', 'bathed in golden light', "
    f"'rays of light stream through'. Find fresh, unexpected imagery. "
    f"Do NOT mention music, songs, albums, or audio. "
    f"Reply with ONLY the visual description in one sentence, under 40 words."
)
```

**Validation:**
- [ ] Generate 5 songs spanning different genres
- [ ] Check docker logs for the Ollama visual descriptions
- [ ] Confirm none use "dust motes dance" or "bathed in golden light"
- [ ] Confirm descriptions are still vivid and genre-appropriate
- [ ] Confirm all 5 get AI cover art successfully

### 4B. Increase Cover Art Idle Timeout

**Problem:** The cover art service (DreamShaper XL) has a 2-minute idle timeout. During consecutive generations, the model unloads between songs because lyrics+title+ACE-Step takes >2 minutes. Every song triggers a full model reload (~35s overhead per song).

**Files modified:**
- `cover_art_service.py` (repo root, deployed to ROG-STRIX) — change `IDLE_TIMEOUT` from 120 to 600 seconds

**Implementation:**

Find and update the idle timeout constant in `cover_art_service.py`:
```python
IDLE_TIMEOUT = 600  # 10 minutes — prevents unnecessary reloads during batch generation
```

After changing, must re-deploy: `scp cover_art_service.py bobray@192.168.1.153:/home/bobray/ace-step/cover_art_service.py` then `ssh bobray@192.168.1.153 "sudo systemctl restart cover-art-service"`.

**Validation:**
- [ ] SSH to ROG-STRIX, confirm the service restarted: `sudo systemctl status cover-art-service`
- [ ] Generate a song, wait 3 minutes, generate another song
- [ ] Check logs for the second song — cover art should NOT show a model reload
- [ ] Confirm cover art time is ~27-32s (not ~65-70s)
- [ ] Wait 11 minutes with no generation, then generate one more song
- [ ] Confirm the model DID unload and reload (timeout still works, just longer)

---

## Phase 5: Unit Tests for New Code

### 5A. Test Coverage for Health Check, Retry, Genre Detection

**Files modified:**
- `ui/tests/unit/test_genre_detection.py` — **new file** — test `_extract_genre()` with compound genres
- `ui/tests/unit/test_gradio_health.py` — **new file** — test `check_health()` with mocked responses

**Implementation:**

`test_genre_detection.py`:
```python
# Test that compound genres are detected correctly
# "Country rock song..." -> "country rock" (not "rock")
# "K-pop inspired..." -> "k-pop" (not "pop")
# "Latin pop song..." -> "latin pop" (not "pop")
# "Rock song..." -> "rock" (still works)
# "Pop song..." -> "pop" (still works)
# "Unknown description" -> "music" (fallback)
```

`test_gradio_health.py`:
```python
# Test health check returns True when ACE-Step responds 200
# Test health check returns False on connection error
# Test health check returns False on timeout
```

**Validation:**
- [ ] Run: `docker exec bray-music-ui python -m pytest tests/unit -v`
- [ ] All new tests pass
- [ ] All existing tests still pass (regression)
- [ ] Note total test count (was 46, should be higher)

---

## Phase 6: Deploy and Full End-to-End Validation

This is the critical phase. Every change from Phases 1-5 must be deployed together and tested as a complete system. Individual phase validation proves each piece works; this phase proves they all work together.

### 6A. Deploy All Changes

```bash
# Copy all changed files to ROG-STRIX
scp ui/main.py bobray@192.168.1.153:/home/bobray/ace-step/ui/main.py
scp ui/gradio_client.py bobray@192.168.1.153:/home/bobray/ace-step/ui/gradio_client.py
scp ui/cover_art.py bobray@192.168.1.153:/home/bobray/ace-step/ui/cover_art.py
scp ui/lyrics_gen.py bobray@192.168.1.153:/home/bobray/ace-step/ui/lyrics_gen.py
scp ui/config.py bobray@192.168.1.153:/home/bobray/ace-step/ui/config.py
scp cover_art_service.py bobray@192.168.1.153:/home/bobray/ace-step/cover_art_service.py
scp -r ui/tests/ bobray@192.168.1.153:/home/bobray/ace-step/ui/tests/

# Rebuild and restart UI container
ssh bobray@192.168.1.153 "cd /home/bobray/ace-step && docker compose build --no-cache ui && docker compose up -d ui"

# Restart cover art service with new timeout
ssh bobray@192.168.1.153 "sudo systemctl restart cover-art-service"
```

**Validation:**
- [ ] `docker ps | grep bray-music` — container running
- [ ] `curl http://192.168.1.153:7861/health` — returns ok, acestep reachable
- [ ] `sudo systemctl status cover-art-service` — active
- [ ] `sudo systemctl status acestep` — active
- [ ] `sudo systemctl status whisper-service` — active
- [ ] Docker logs show "Startup: Pre-warming Ollama" message
- [ ] Run unit tests: `docker exec bray-music-ui python -m pytest tests/unit tests/api -v` — all pass

### 6B. End-to-End Test Suite: 10 Diverse Songs

Generate 10 songs that exercise every change and every genre category. These must be real, full-length vocal songs — no shortcuts.

**Test songs (in this order):**

| # | Description | Tests | Expected Genre |
|---|-------------|-------|----------------|
| 1 | "Pop song about a rainy day" | Ollama pre-warm (first song after deploy), standard genre | pop |
| 2 | "Country rock song about a dirt road at sunset" | Compound genre detection | country rock |
| 3 | "K-pop song about first love in Seoul" | Compound genre detection | k-pop |
| 4 | "Blues ballad about a broken guitar" | Slow genre, should be 4+ minutes | blues |
| 5 | "Punk song about skateboarding through traffic" | Fast genre, likely shortest | punk |
| 6 | "Rap song about being the last one standing" | Hip hop lyrics format, 16-bar verses | hip hop |
| 7 | "Gospel song about a prodigal son coming home" | Long song, ballad lyrics format | gospel |
| 8 | "Latin pop song about carnival night" | Compound genre detection | latin pop |
| 9 | "Metal song about dragons in the mountains" | Heavy genre | metal |
| 10 | "Jazz song about a midnight train" | Medium tempo | jazz |

**For EVERY song, validate ALL of the following:**

1. **Genre detection** — check docker log line `Genre: X` matches expected genre
2. **Lyrics generated** — check `LYRICS: Generated N chars` in logs, N > 100
3. **Title generated** — check `TITLE: 'X' in Ys` in logs, Y should be ~15s (not 43s)
4. **ACE-Step completed** — check `ACESTEP: Complete in Xs` in logs
5. **Track saved** — check `SAVED: 'X' | filename | Ds | seed=S` in logs
6. **Duration reasonable** — slow genres (blues, gospel) should be 3:30+, fast genres (punk, pop) at least 2:00
7. **Whisper validation** — check `WHISPER: RATING (score=X)` in logs
8. **Cover art generated** — check `COVER: Saved X.png in Ys` in logs
9. **Cover art description** — check Ollama visual description in logs, should NOT contain "dust motes dance"
10. **Cover art style** — check the random art style was applied
11. **Song playable** — open the song in the UI at `https://music.apps.bray.house/song/{id}`, play audio
12. **Song detail correct** — on the song page, verify title, duration, quality badge, cover art image all display correctly
13. **New Cover button works** — click "New Cover" on at least 2 songs, confirm new art generates
14. **Total time** — check `TOTAL TIME: Xs` in logs

**Crash recovery test (songs 5-10):**

After generating songs 1-4, we should be approaching the ~5-song crash threshold. Songs 5-10 are specifically designed to push through the crash:

- [ ] If ACE-Step crashes during songs 5-10, confirm the retry logic kicks in
- [ ] Confirm the retried song completes with all data (lyrics, whisper, cover art)
- [ ] Confirm the SSE stream shows "waiting for restart" status to the user
- [ ] If NO crash occurs in 10 songs (great!), note this as an improvement finding

**Compile results into a table:**

| # | Song | Genre | Genre Correct? | Lyrics | Title Time | Duration | Quality | Cover Art | Cover Desc Fresh? | Total Time | Notes |
|---|------|-------|----------------|--------|------------|----------|---------|-----------|-------------------|------------|-------|

### 6C. Regression Tests

After all 10 songs, verify nothing broke:

- [ ] **Library page** — loads correctly, shows all new songs with covers and quality badges
- [ ] **Search** — search for one of the new song titles, confirm it appears
- [ ] **Favorites** — toggle favorite on 2 songs, filter by favorites, confirm they appear
- [ ] **Playlists** — create a playlist, add 3 songs to it, verify
- [ ] **Custom mode** — switch to Custom mode in the UI, manually set BPM=100, Key=C, Duration=2min, generate a short song. Confirm it respects all manual params.
- [ ] **Instrumental** — generate an instrumental (no vocals). Confirm: no whisper validation, cover art still generated, no lyrics in track metadata.
- [ ] **Remix** — from any song's detail page, click Remix. Confirm it navigates to index with params pre-filled. Generate the remix. Confirm it produces a new song with the original's params.
- [ ] **Delete** — delete one of the test songs. Confirm it's removed from library, audio file deleted, cover file deleted.
- [ ] **Mobile** — open `https://music.apps.bray.house` on phone, generate a song. Confirm SSE stream works, all steps display, song plays back correctly.

---

## Phase 7: Documentation and Memory Update

### 7A. Update Project Documentation

After all validation passes:

**Files modified:**
- `CLAUDE.md` — update genre detection section if compound genres change the keyword count
- `AS-BUILT.md` — document retry logic, health check, Ollama pre-warm, cover art timeout change

### 7B. Update Auto-Memory

Update `MEMORY.md` with:
- New retry logic and health check behavior
- Compound genre detection (add to genre detection section)
- Cover art idle timeout change (120s -> 600s)
- Ollama pre-warm on startup behavior
- Updated test count

### 7C. Commit and Push

```bash
cd ~/projects/Bray_Music
git add ui/main.py ui/gradio_client.py ui/cover_art.py ui/lyrics_gen.py
git add cover_art_service.py
git add ui/tests/unit/test_genre_detection.py ui/tests/unit/test_gradio_health.py
git add plans/003-resilience-and-quality.md docs/20-song-test-results.md
git commit -m "Add ACE-Step retry/health check, Ollama pre-warm, compound genre detection, cover art improvements"
git push origin main && git push github main
```

---

## Acceptance Criteria

The plan is COMPLETE when ALL of the following are true:

1. **All 10 end-to-end test songs completed** — with full data in the results table
2. **At least 1 ACE-Step crash was recovered** via auto-retry (or 10 consecutive songs succeeded without crash, proving stability improved)
3. **Compound genres detected correctly** — "country rock", "k-pop", and "latin pop" all detected in logs
4. **No "dust motes" in cover art descriptions** across all 10 songs
5. **First song after deploy had no lyrics timeout** — Ollama pre-warm worked
6. **All regression tests passed** — library, search, favorites, playlists, custom mode, instrumental, remix, delete, mobile
7. **All unit tests passed** — including new tests, total count documented
8. **Cover art model reload only happens after 10 min idle** — not after every song
9. **Zero data loss** — no songs lost to crashes, no metadata missing, no orphaned files
10. **Changes committed and pushed** to both Gitea and GitHub

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Retry logic introduces infinite loops | Generation hangs | Hard cap: 1 retry + 3-min health wait max = bounded at ~6 min worst case |
| Health check false positive (ACE-Step responds but not ready) | Wasted generation attempt | `/gradio_api/info` only returns 200 when Gradio is fully initialized |
| Ollama pre-warm fails on startup | Falls back to current behavior | try/except wraps the call; first song will cold-start as before |
| Compound genre detection breaks existing genres | Wrong BPM/lyrics format | Compound keywords checked FIRST, single keywords unchanged after |
| Cover art timeout too long (10 min) | GPU memory held longer | 10 min is still reasonable; ACE-Step can share GPU since cover art auto-unloads |
| Changes interact badly (retry + health check + pre-warm) | Unpredictable pipeline | Phase 6 end-to-end test specifically validates all changes together |

---

## Estimated Scope

| Phase | Files Changed | New Files | Complexity |
|-------|--------------|-----------|------------|
| 1A: Health check | 2 | 0 | Low |
| 1B: Auto-retry | 1 | 0 | Medium |
| 2A: Ollama pre-warm | 1 | 0 | Low |
| 3A: Compound genres | 2 | 0 | Low |
| 4A: Description diversity | 1 | 0 | Low |
| 4B: Cover art timeout | 1 | 0 | Low |
| 5A: Unit tests | 0 | 2 | Low |
| 6: Deploy + test | 0 | 0 | High (time) |
| 7: Docs | 3 | 0 | Low |
| **Total** | **8** | **2** | |
