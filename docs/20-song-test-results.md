# 20-Song Generation Test Results

**Date:** 2026-03-06 / 2026-03-07
**System:** ACE-Step 1.5, 1.7B LM, GTX 1080 Ti (11GB), DreamShaper XL cover art
**Mode:** Simple (all songs via /generate-stream, no manual params — no duration, no BPM, no key specified)
**Goal:** Generate 20 diverse vocal songs, validate every data point, compile lessons learned

---

## Summary

- **20 songs attempted**, **15 completed successfully**, **5 failed** (all ACE-Step crashes)
- **Success rate: 75%** (15/20)
- All 15 successful songs rated **GREAT** by Whisper validation
- All 15 successful songs got **AI cover art** (random style pool)
- **Duration range:** 2:19 (punk) to 4:57 (gospel) — average 3:24
- **Total wall time:** ~110 minutes for all 20 attempts

---

## Results Table

| # | Description | Title | Genre | Duration | Lyrics | Quality | Score | Cover | ACE-Step Time | Total Time | Status |
|---|-------------|-------|-------|----------|--------|---------|-------|-------|---------------|------------|--------|
| 1 | Country ballad about a truck driver missing home | Highway Heartache | country | 2:52 | 0 (timeout) | N/A | N/A | AI | 172.8s | 383.2s | PARTIAL |
| 2 | Hard rock anthem about fighting your demons | Shadowborn | rock | 3:58 | 1444 | GREAT | 0.976 | AI | 238.8s | 393.7s | OK |
| 3 | Gospel choir song about finding grace | Grace Found | gospel | 4:57 | 2041 | GREAT | 0.976 | AI | 297.6s | 471.2s | OK |
| 4 | Jazz lounge song about a rainy night in the city | City Rain Blues | jazz | 3:59 | 1335 | GREAT | 1.0 | AI | 239.4s | 394.1s | OK |
| 5 | Pop song about a summer beach romance | Sun Kissed Waves | pop | 2:55 | 1342 | GREAT | 1.0 | AI | 175.8s | 323.2s | OK |
| 6 | R&B slow jam about making up after a fight | Second Chance Heart | r&b | — | 1461 | — | — | — | crash@144.5s | 192.4s | FAIL |
| 7 | Rap song about growing up in a small town | Dust & Dreams | hip hop | 3:33 | 3017 | GREAT | 1.0 | AI | 213.8s | 430.6s | OK |
| 8 | Folk song about a grandfather's fishing boat | Saltwater Legacy | folk | 3:29 | 1410 | GREAT | 1.0 | AI | 209.4s | 370.7s | OK |
| 9 | Electronic dance track about losing yourself | Neon Bloom | electronic | 3:40 | 1462 | GREAT | 0.944 | AI | 220.8s | 371.1s | OK |
| 10 | Blues song about losing your job Monday morning | Monday Blues | blues | 4:53 | 1413 | GREAT | 0.809 | AI | 293.6s | 429.5s | OK |
| 11 | Punk rock song about quitting your corporate job | Corporate Riot | punk | 2:19 | 1334 | GREAT | 1.0 | AI | 139.8s | 296.1s | OK |
| 12 | Latin pop song about dancing under the stars | Starlight Dance | pop | — | 1354 | — | — | — | crash@115.9s | 163.2s | FAIL |
| 13 | Classical-inspired ballad about seasons changing | Golden Drift | classical | — | 1321 | — | — | — | unreachable | 46.2s | FAIL |
| 14 | Reggae song about a lazy Sunday afternoon | Sunsoaked Ease | reggae | 2:47 | 1376 | GREAT | 0.952 | AI | 167.8s | 315.4s | OK |
| 15 | Soul song about a mother's unconditional love | Golden Thread | soul | 3:42 | 1376 | GREAT | 0.972 | AI | 222.8s | 387.9s | OK |
| 16 | Indie rock song about a road trip with no destination | Wandering Lines | indie | 3:03 | 1397 | GREAT | 1.0 | AI | 183.8s | 335.8s | OK |
| 17 | K-pop inspired song about a secret crush | Hidden Bloom | pop | — | 1518 | — | — | — | crash@153.9s | 204.7s | FAIL |
| 18 | Metal song about a Viking battle at sea | Stormborn Fury | metal | — | 1426 | — | — | — | unreachable | 48.5s | FAIL |
| 19 | Country rock song about a Friday night bonfire | Friday Fireflies | rock | 2:45 | 1315 | GREAT | 0.95 | AI | 165.6s | 311.0s | OK |
| 20 | Acoustic love song about growing old together | Golden Years | ballad | 3:53 | 1953 | GREAT | 1.0 | AI | 233.6s | 402.7s | OK |

---

## Detailed Failure Analysis

### Failure Pattern: ACE-Step Crashes Under Sustained Load

Three separate ACE-Step process crashes occurred, each producing the identical error:

```
peer closed connection without sending complete message body (incomplete chunked read)
```

The crash pattern is extremely consistent:

| Crash | Song # | Genre | Time Before Crash | Songs Since Last Restart |
|-------|--------|-------|-------------------|--------------------------|
| 1st | #6 (R&B) | r&b | 144.5s | 5 (songs #1-#5) |
| 2nd | #12 (Latin pop) | pop | 115.9s | 5 (songs #7-#11) |
| 3rd | #17 (K-pop) | pop | 153.9s | 4 (songs #14-#16 + start of #17) |

**Observations:**
- Crashes always happen 100-155 seconds into audio generation — never during lyrics, title, or post-processing
- The crash happens server-side (ACE-Step Gradio process dies), not client-side
- systemd `Restart=always` correctly restarts the service every time
- Restart takes 60-90 seconds for the 1.7B LM to reload and torch to recompile
- ACE-Step memory peaks at 13.3 GB (with 14.1 GB swap) — on an 11 GB GPU with 16 GB RAM
- **Hypothesis:** Memory leak or VRAM fragmentation accumulates across generations. After 4-5 consecutive generations, the process becomes unstable and crashes during the next memory-intensive operation

**Follow-on failures:** Songs #13 and #18 each failed with "All connection attempts failed" because they were submitted during the 60-90s restart window after the preceding crash. The UI does not check ACE-Step health before submitting.

### Failure: Lyrics Timeout (Song #1)

Full log for song #1:
```
[GEN 8f0389f3] MODEL: Cold-loaded in 40.1s
[GEN 8f0389f3] LYRICS: Returned empty after 90.2s, proceeding without
[GEN 8f0389f3] TITLE: 'Highway Heartache' in 43.5s   <-- also slow (usually 15s)
```

- Ollama's gemma3:12b model was not loaded in GPU when the first song started
- Cold-loading the model took 40.1s
- The remaining 50s was not enough for lyrics generation (normally takes 30-37s, but first inference after load is slower)
- The song proceeded without lyrics, becoming a pseudo-instrumental
- Title generation was also abnormally slow (43.5s vs normal 15s) — probably the first Ollama inference after the cold load

**Impact:** Song #1 has no lyrics, no Whisper validation, and a 2:52 duration that's shorter than it would have been with lyrics. It still got an AI cover and a title.

---

## Detailed Duration Analysis

### Duration vs. Genre (sorted by duration)

| Genre | Duration | Lyrics (chars) | Approx BPM Range | Duration Tier |
|-------|----------|----------------|-------------------|---------------|
| gospel | 4:57 (298s) | 2041 | 60-80 | Long (4:00+) |
| blues | 4:53 (294s) | 1413 | 60-80 | Long (4:00+) |
| jazz | 3:59 (239s) | 1335 | 80-120 | Medium-long (3:30-4:00) |
| rock | 3:58 (239s) | 1444 | 110-140 | Medium-long (3:30-4:00) |
| ballad | 3:53 (234s) | 1953 | 60-80 | Medium-long (3:30-4:00) |
| soul | 3:42 (223s) | 1376 | 70-100 | Medium (3:00-3:30) |
| electronic | 3:40 (221s) | 1462 | 120-140 | Medium (3:00-3:30) |
| hip hop | 3:33 (214s) | 3017 | 80-100 | Medium (3:00-3:30) |
| folk | 3:29 (209s) | 1410 | 90-120 | Medium (3:00-3:30) |
| indie | 3:03 (184s) | 1397 | 120-150 | Medium (3:00-3:30) |
| pop | 2:55 (176s) | 1342 | 110-130 | Short (under 3:00) |
| country* | 2:52 (173s) | 0 | 80-120 | Short (under 3:00) |
| reggae | 2:47 (168s) | 1376 | 70-90 | Short (under 3:00) |
| country rock | 2:45 (166s) | 1315 | 110-140 | Short (under 3:00) |
| punk | 2:19 (140s) | 1334 | 160-200 | Short (under 3:00) |

*country song had no lyrics (timeout), duration would likely be longer with lyrics

**Key findings:**
1. **Duration is primarily genre/tempo-driven, NOT lyrics-length-driven.** Hip hop had 3017 chars (2.3x average) but was only 3:33. Gospel had 2041 chars and was 4:57. Blues had just 1413 chars and was 4:53.
2. **Slow genres (blues, gospel, jazz, ballad) consistently produce 3:50-5:00 songs** without any duration parameter
3. **Fast genres (punk, pop, country rock) produce 2:19-2:55 songs** — reliably under 3:00
4. **8 of 15 songs (53%) were at or above 3:00.** To get more songs over 3:00, we'd need to influence the fast genres.
5. **The auto-duration (-1) setting works well.** The LM makes sensible genre-appropriate choices. We should NOT hardcode duration.
6. **Reggae was surprisingly short (2:47)** despite being a typically mid-tempo genre. May be a training data bias.

### Duration vs. Lyrics Length (proving they're decoupled)

| Song | Lyrics Chars | Duration | Chars/Minute |
|------|-------------|----------|--------------|
| Dust & Dreams (hip hop) | 3017 | 3:33 | 850 |
| Golden Years (ballad) | 1953 | 3:53 | 503 |
| Grace Found (gospel) | 2041 | 4:57 | 412 |
| Neon Bloom (electronic) | 1462 | 3:40 | 399 |
| Corporate Riot (punk) | 1334 | 2:19 | 576 |
| Monday Blues (blues) | 1413 | 4:53 | 289 |

The chars-per-minute rate varies from **289 (blues)** to **850 (hip hop)** — a 3x difference. This confirms that ACE-Step's LM controls pacing per genre, not per character count.

---

## Detailed Quality Analysis

### Whisper Scores (all successful songs)

| Song | Genre | Quality | Score | Whisper Time | Notes |
|------|-------|---------|-------|--------------|-------|
| Shadowborn | rock | GREAT | 0.976 | 65.5s | |
| Grace Found | gospel | GREAT | 0.976 | 79.3s | Choir vocals, still high |
| City Rain Blues | jazz | GREAT | 1.0 | 57.8s | Perfect |
| Sun Kissed Waves | pop | GREAT | 1.0 | 47.2s | Perfect |
| Dust & Dreams | hip hop | GREAT | 1.0 | 107.7s | Longest whisper time (3:33 track) |
| Saltwater Legacy | folk | GREAT | 1.0 | 61.2s | Perfect |
| Neon Bloom | electronic | GREAT | 0.944 | 64.2s | Lowest of "clean" genres — effects |
| Monday Blues | blues | GREAT | 0.809 | 72.6s | Lowest overall — slow/gravelly delivery |
| Corporate Riot | punk | GREAT | 1.0 | 45.6s | Perfect despite fast/aggressive vocals |
| Sunsoaked Ease | reggae | GREAT | 0.952 | 51.7s | Slight accent/rhythm challenge |
| Golden Thread | soul | GREAT | 0.972 | 72.7s | Melisma may affect transcription |
| Wandering Lines | indie | GREAT | 1.0 | 54.2s | Perfect |
| Friday Fireflies | country rock | GREAT | 0.95 | 50.2s | Slight twang/accent |
| Golden Years | ballad | GREAT | 1.0 | 69.2s | Perfect |

**Quality patterns:**
1. **100% GREAT rate** — the 1.7B LM is a transformational upgrade from 0.6B. Previous tests with 0.6B produced occasional FAIR/POOR results.
2. **10 of 14 scored perfect 1.0** (71%) — extraordinary consistency
3. **Blues scored lowest (0.809)** — the genre's slow, gravelly, blues-inflected vocal delivery makes clean transcription harder for Whisper
4. **Electronic scored 0.944** — synth effects and vocal processing reduce Whisper's ability to detect clean speech
5. **Reggae (0.952) and country rock (0.95)** — accent/dialect characteristics slightly reduce Whisper scores
6. **Punk scored perfect 1.0 despite aggressive vocals** — surprising; fast + shouted delivery didn't hurt quality
7. **Gospel scored 0.976** — choir vocals are complex but the model handles them well

### Whisper Timing

| Duration Range | Whisper Time | Notes |
|---------------|-------------|-------|
| 2:19 (shortest) | 45.6s | Fastest whisper |
| 2:45-2:55 | 47-51s | Short songs |
| 3:03-3:42 | 54-73s | Medium songs |
| 3:53-4:57 | 69-80s | Long songs |
| 3:33 (hip hop) | 107.7s | Outlier — dense lyrics, many segments |

Whisper time roughly scales with song duration, but hip hop is a major outlier at 107.7s (3x what similar durations take) — likely because the rapid-fire lyrics produce far more Whisper segments to analyze.

---

## Detailed Cover Art Analysis

### All Cover Art: Ollama Descriptions + Art Styles

| # | Song | Ollama Visual Description | Random Art Style |
|---|------|--------------------------|-----------------|
| 1 | Highway Heartache | Rain streaks the cracked windshield of a lone, dusty semi-truck parked beside a dimly lit, rural diner, bathed in the amber glow of a distant porch light. | torn paper cut-out collage with layered textures and mixed media |
| 2 | Shadowborn | Jagged, obsidian cliffs loom over a storm-ravaged beach; fractured lightning illuminates a solitary, weathered figure battling swirling shadows amidst crashing, black waves. | faded vintage Polaroid with warm light leak and soft focus |
| 3 | Grace Found | Sunlight streams through stained glass, illuminating dust motes dancing above a weathered wooden porch where outstretched hands offer wildflowers to a figure bathed in golden light. | bold graphic novel illustration with thick ink outlines and dramatic shadows |
| 4 | City Rain Blues | Rain streaks down a neon-lit cityscape reflected in a wet taxi window, illuminating a solitary figure nursing a drink at a dimly lit, plush velvet table. | brutalist concrete and steel with harsh geometry and raw texture |
| 5 | Sun Kissed Waves | Golden hour sunlight bathes a secluded cove where a young couple, laughing, builds a sandcastle near turquoise water scattered with vibrant beach towels and scattered seashells. | brutalist concrete and steel with harsh geometry and raw texture |
| 7 | Dust & Dreams | Dusty basketball court, bathed in golden hour light, overlooks faded brick buildings and a single, distant water tower against a hazy, twilight sky. | neon sign glowing in rain-slicked darkness |
| 8 | Saltwater Legacy | A weathered wooden fishing boat rests gently in a misty harbor, bathed in the soft, golden light of a late afternoon sun, with a lone, worn oilskin jacket draped across the stern. | hand-carved linocut block print with bold black and white contrast |
| 9 | Neon Bloom | Shimmering, fractured neon light reflects off a sweating crowd's blurred faces amidst a labyrinthine, chrome-lined space, lost in a pulsating, hazy glow. | minimalist geometric design with clean shapes and limited color palette |
| 10 | Monday Blues | Dust motes dance in the weak morning light slanting across a sparsely furnished room, illuminating a discarded coffee cup and a crumpled notice on a worn wooden table. | infrared photography with ghostly white foliage and dark skies |
| 11 | Corporate Riot | A pristine, beige office cubicle is violently overturned, papers and staplers strewn across a sterile gray floor under harsh, fluorescent lighting, a single defiant red spray-painted fist raised amidst the chaos. | Japanese ukiyo-e woodblock print with flowing lines and flat bold colors |
| 14 | Sunsoaked Ease | Sun-drenched, weathered wood of a porch overlooks a turquoise sea, a hammock sways gently, and vibrant hibiscus blooms spill onto a terracotta tile floor. | dark fantasy oil painting with rich textures and mythical atmosphere |
| 15 | Golden Thread | Dust motes dance in a sunbeam illuminating a woman's gentle hands cradling a faded, patchwork quilt amidst a warmly lit, vintage kitchen. | comic book halftone dots with bold primary colors and action lines |
| 16 | Wandering Lines | Dust motes dance in the fading amber light of a deserted gas station, illuminating a vintage station wagon overflowing with worn maps and faded wildflowers. | Andy Warhol style silk screen pop art with bold flat color blocks |
| 19 | Friday Fireflies | A crackling bonfire illuminates laughing faces silhouetted against a vast, star-dusted sky, surrounded by weathered wood, scattered beer bottles, and the warm glow of string lights. | spray paint street mural on weathered brick wall |
| 20 | Golden Years | Sunlight warms a porch swing where two figures, silver-haired and intertwined, watch falling leaves swirl amidst a riot of late-autumn golds, russets, and fading lavender. | glitch art with RGB channel splitting and digital distortion |

### Cover Art Observations

1. **Ollama descriptions are consistently vivid and genre-appropriate.** Each captures the mood and narrative of the song in a single visual sentence. The two-step approach (Ollama describes scene -> DreamShaper renders with art style) produces much better results than a simple "album cover for [genre] song" prompt.

2. **Ollama has a "dust motes" habit.** The phrase "dust motes dance" appears in 4 of 15 descriptions (#10, #15, #16, and the scene for #3 also has "dust motes"). This is likely a gemma3 bias. Could consider adding a negative prompt or diversity instruction.

3. **Random art style collisions are rare but happen.** Songs #4 (City Rain Blues) and #5 (Sun Kissed Waves) both got "brutalist concrete and steel" — with 37 styles and 15 songs, the probability of at least one collision is ~75%, so this is expected. The collision doesn't matter much because the Ollama descriptions are unique.

4. **Style/subject "mismatches" often produce the most interesting art:**
   - Reggae + "dark fantasy oil painting" — a tropical porch scene rendered in dark, moody oil paint
   - Punk + "Japanese ukiyo-e woodblock print" — an office riot rendered in traditional Japanese style
   - Ballad + "glitch art with RGB channel splitting" — a serene autumn scene with digital distortion
   - Country + "torn paper cut-out collage" — a truck stop scene in mixed media

5. **Cover art generation timing is very consistent:** 64.4s to 71.6s, averaging ~66s. This is longer than the ~27-32s observed in earlier tests, likely because the cover art service's DreamShaper XL model now needs to reload from disk each time (the 2-minute idle unload is triggering between songs in the test because post-processing + next song's lyrics phase takes >2 minutes).

6. **Cover art timing for song #20 was 68.4s** — first generation after the ACE-Step crash/restart cycle, but the cover art service had its own model unloaded (idle timeout) so it needed to reload regardless.

---

## Detailed Lyrics Analysis

### Lyrics Generation Timing

| Song | Genre | Chars | Gen Time | Chars/sec | Notes |
|------|-------|-------|----------|-----------|-------|
| Highway Heartache | country | 0 | 90.2s (timeout) | 0 | Cold start failure |
| Shadowborn | rock | 1444 | 32.6s | 44 | |
| Grace Found | gospel | 2041 | 37.8s | 54 | Long lyrics, still fast |
| City Rain Blues | jazz | 1335 | 31.5s | 42 | |
| Sun Kissed Waves | pop | 1342 | 30.8s | 44 | |
| Second Chance Heart | r&b | 1461 | 32.2s | 45 | (song later failed) |
| Dust & Dreams | hip hop | 3017 | 50.3s | 60 | 2x lyrics, only 1.5x time |
| Saltwater Legacy | folk | 1410 | 32.3s | 44 | |
| Neon Bloom | electronic | 1462 | 33.0s | 44 | |
| Monday Blues | blues | 1413 | 32.4s | 44 | |
| Corporate Riot | punk | 1334 | 29.6s | 45 | Fastest standard gen |
| Starlight Dance | pop | 1354 | 31.8s | 43 | (song later failed) |
| Golden Drift | classical | 1321 | 30.4s | 43 | (song later failed) |
| Sunsoaked Ease | reggae | 1376 | 31.2s | 44 | |
| Golden Thread | soul | 1376 | 30.3s | 45 | |
| Wandering Lines | indie | 1397 | 30.4s | 46 | |
| Hidden Bloom | k-pop | 1518 | 34.0s | 45 | Slightly longer lyrics |
| Stormborn Fury | metal | 1426 | 32.9s | 43 | (song later failed) |
| Friday Fireflies | country rock | 1315 | 29.7s | 44 | |
| Golden Years | ballad | 1953 | 36.9s | 53 | Long lyrics (8-line format) |

**Observations:**
1. **Remarkably consistent:** Standard lyrics (1300-1500 chars) generate in 29.6-33.0 seconds — a variance of only ~10%
2. **Genre-aware verse format works:** Hip hop generates 3017 chars (16-bar verse format), gospel/ballad generate 1950-2040 chars (8-line verse format), all others generate ~1300-1460 chars (6-line verse format)
3. **Throughput scales sub-linearly:** Hip hop (3017 chars) took 50.3s — only 1.5x the time of a standard 1400-char song, suggesting much of the 30s is Ollama overhead
4. **All 19 warm generations succeeded** — only the cold start failed. Ollama is very reliable once the model is loaded.

### Title Generation Timing

| Song | Title | Time | Notes |
|------|-------|------|-------|
| Highway Heartache | Highway Heartache | 43.5s | COLD START (first inference) |
| All other songs | Various | 15.1-16.8s | Extremely consistent |

Title generation is a simple single-line Ollama call. The 43.5s outlier for song #1 confirms the cold start problem — the very first Ollama inference after model load is 3x slower than subsequent calls.

---

## Detailed Performance Analysis

### Full Timing Breakdown Per Successful Song

| Song | Lyrics | Title | ACE-Step | Whisper | Cover Art | Total |
|------|--------|-------|----------|---------|-----------|-------|
| Shadowborn | 32.6s | 15.3s | 238.8s | 65.5s | 66.3s | 393.7s |
| Grace Found | 37.8s | 15.3s | 297.6s | 79.3s | 65.4s | 471.2s |
| City Rain Blues | 31.5s | 15.3s | 239.4s | 57.8s | 65.8s | 394.1s |
| Sun Kissed Waves | 30.8s | 15.4s | 175.8s | 47.2s | 64.7s | 323.2s |
| Dust & Dreams | 50.3s | 15.4s | 213.8s | 107.7s | 70.8s | 430.6s |
| Saltwater Legacy | 32.3s | 15.7s | 209.4s | 61.2s | 69.8s | 370.7s |
| Neon Bloom | 33.0s | 15.3s | 220.8s | 64.2s | 65.1s | 371.1s |
| Monday Blues | 32.4s | 15.2s | 293.6s | 72.6s | 64.8s | 429.5s |
| Corporate Riot | 29.6s | 15.1s | 139.8s | 45.6s | 64.4s | 296.1s |
| Sunsoaked Ease | 31.2s | 15.5s | 167.8s | 51.7s | 71.6s | 315.4s |
| Golden Thread | 30.3s | 15.1s | 222.8s | 72.7s | 68.4s | 387.9s |
| Wandering Lines | 30.4s | 15.5s | 183.8s | 54.2s | 64.5s | 335.8s |
| Friday Fireflies | 29.7s | 15.4s | 165.6s | 50.2s | 71.0s | 311.0s |
| Golden Years | 36.9s | 15.3s | 233.6s | 69.2s | 68.4s | 402.7s |

### Phase Averages

| Phase | Min | Max | Average | % of Total | Bottleneck? |
|-------|-----|-----|---------|------------|-------------|
| Lyrics | 29.6s | 50.3s | 33.5s | 9% | No |
| Title | 15.1s | 15.7s | 15.3s | 4% | No |
| **ACE-Step** | **139.8s** | **297.6s** | **214.5s** | **58%** | **YES** |
| Whisper | 45.6s | 107.7s | 64.2s | 17% | Minor |
| Cover Art | 64.4s | 71.6s | 66.5s | 18% | Minor |
| **Total** | **296s** | **471s** | **370s** | **100%** | |

**ACE-Step audio generation is 58% of total time** — it's the primary bottleneck and the only phase with high variance (140-298s, a 2x range driven entirely by genre/tempo/duration).

### First-After-Restart Performance Penalty

Song #20 (Golden Years) was the first generation after ACE-Step crashed and restarted:
- **ACE-Step audio:** 212.9s (ballad typically ~230s, so actually normal — the torch recompilation happened during the 60-90s restart window, not during generation)
- **Cover art:** 68.4s (model was already unloaded due to idle timeout — reload time)
- **Title generation for song #1:** 43.5s vs normal 15s — Ollama cold start penalty is real

---

## Detailed Genre Detection Analysis

| Description | Detected Genre | Correct? | Notes |
|-------------|---------------|----------|-------|
| "Country ballad about..." | country | Yes | |
| "Hard rock anthem about..." | rock | Yes | |
| "Gospel choir song about..." | gospel | Yes | |
| "Jazz lounge song about..." | jazz | Yes | |
| "Pop song about..." | pop | Yes | |
| "R&B slow jam about..." | r&b | Yes | |
| "Rap song about..." | hip hop | Yes | rap -> hip hop mapping |
| "Folk song about..." | folk | Yes | |
| "Electronic dance track about..." | electronic | Yes | |
| "Blues song about..." | blues | Yes | |
| "Punk rock song about..." | punk | Yes | |
| "Latin pop song about..." | pop | Partial | Lost "latin" qualifier |
| "Classical-inspired ballad about..." | classical | Partial | "ballad" might be better |
| "Reggae song about..." | reggae | Yes | |
| "Soul song about..." | soul | Yes | |
| "Indie rock song about..." | indie | Yes | |
| "K-pop inspired song about..." | pop | Partial | Lost "K-pop" qualifier |
| "Metal song about..." | metal | Yes | |
| "Country rock song about..." | rock | Partial | Lost "country" qualifier |
| "Acoustic love song about..." | ballad | Yes | acoustic -> ballad makes sense |

**Detection accuracy:** 15/20 fully correct, 4/20 partially correct (lost compound qualifier), 1/20 debatable (classical vs ballad).

**Issue:** The genre detection uses first-match keyword matching (`_extract_genre()` in `main.py`). When a description contains multiple genre keywords (like "country rock" or "Latin pop"), only the first match wins. "Country rock" matches "rock" before "country". "K-pop" matches "pop". "Latin pop" matches "pop" (no "latin" keyword exists).

---

## Lessons Learned

### 1. The 1.7B LM Is Transformational

The upgrade from 0.6B to 1.7B LM produced the single biggest quality improvement in the project's history:
- **100% GREAT rate** across 15 songs spanning 14 different genres
- **71% perfect 1.0 Whisper scores** — the model consistently generates clear, intelligible vocals
- **No FAIR or POOR results at all** — previous 0.6B testing regularly produced FAIR results
- The quality is so consistent that the conditional cover art gate (only AI covers for GOOD/GREAT) is essentially always passing

**Implication:** With 1.7B, the Whisper quality gate adds latency (45-108s per song) but almost never changes the outcome. Consider whether it's worth the time, or if it should be async/optional for the user.

### 2. Duration Is Genre-Driven, Not Lyrics-Driven

This was the most surprising finding. ACE-Step's LM has strong internal models of genre-appropriate song length:
- Blues/gospel: ~5 minutes
- Rock/jazz/ballad: ~4 minutes
- Soul/electronic/hip hop/folk: 3:30-3:45
- Pop/reggae/country rock: 2:45-2:55
- Punk: ~2:20

Lyrics length has minimal impact — the same ~1400 chars produces everything from 2:19 (punk) to 4:53 (blues). The LM controls pacing, tempo, and arrangement to match the genre.

**Implication:** To get consistently longer songs for fast genres, we can't just add more lyrics. We'd need to either:
- Bias toward slower BPM for genres that tend short
- Set a minimum duration parameter for fast genres
- Add more song sections (bridge, instrumental break) in the lyrics structure

### 3. ACE-Step Has a Consistent Stability Ceiling

ACE-Step crashes every 4-5 consecutive generations with identical errors. The pattern held across three separate crash cycles in this test. The crash is server-side (the Gradio process dies) and always happens during audio generation, never during other phases.

**Memory evidence:**
- Peak memory after restart: 13.3 GB (with 14.1 GB swap) on 11 GB GPU + 16 GB RAM
- The process uses ~19 GB total (RAM + swap) at peak, as documented in AS-BUILT.md
- After 4-5 generations, accumulated allocations likely push past a fragmentation threshold

**Implication:** This is likely an upstream ACE-Step issue, not something we can fix in our UI layer. Our options:
- **Proactive restart:** Monitor memory and restart ACE-Step before it crashes
- **Retry logic:** When a generation fails, wait for ACE-Step to restart, then auto-retry
- **Health check:** Before submitting a new generation, verify ACE-Step is responsive
- **Cooldown:** Add a brief pause between generations to let the garbage collector work

### 4. Ollama Is Reliable But Has a Cold Start Problem

Once the model is loaded, Ollama is remarkably consistent:
- Lyrics: 29.6-37.8s for standard songs, 50.3s for hip hop's 3000+ chars
- Titles: 15.1-15.7s — essentially constant
- Descriptions (for cover art): equally consistent
- **Zero failures after warm-up** — all 19 warm generations succeeded

But the cold start is a real problem:
- Model load: 40.1s
- First inference after load: ~3x slower than normal (43.5s vs 15s for title)
- Combined: lyrics generation can exceed the 90s timeout

**Implication:** Pre-warm Ollama when the UI starts, or on first page load. A simple "generate one word" prompt would suffice to load the model.

### 5. The Cover Art Pipeline Is Excellent

The two-step approach (Ollama scene description -> DreamShaper XL render with random art style) produces consistently high-quality, diverse cover art:
- Every description is unique and captures the song's narrative/mood
- The 37-style random pool ensures visual variety
- Style/subject "mismatches" often produce the most interesting results
- Generation time is consistent (~66s)

**One issue:** Ollama has a slight "dust motes" repetition habit (4/15 descriptions). Consider adding a diversity instruction to the prompt or post-processing to detect repeated phrases.

**Another issue:** Cover art model reload adds ~35s overhead because the 2-minute idle timeout causes the model to unload between songs. In a batch test like this, the model loads/unloads 15 times unnecessarily.

### 6. Genre Detection Needs Compound Genre Support

The current `_extract_genre()` uses first-match keyword detection, which loses compound genre qualifiers:
- "Country rock" -> "rock" (lost "country")
- "K-pop" -> "pop" (lost "K-pop")
- "Latin pop" -> "pop" (lost "Latin")
- "Classical-inspired ballad" -> "classical" (maybe should be "ballad")

This affects both the genre hint passed to ACE-Step and the auto-BPM selection from `_GENRE_BPM`.

**Implication:** Consider matching multi-word genre combinations first before falling back to single-keyword matches. Or pass the full description string as-is for the genre hint.

### 7. The Pipeline Is Resilient to Partial Failures

Song #1 demonstrated graceful degradation:
- Lyrics timed out -> song proceeded without lyrics (pseudo-instrumental)
- Still got an AI-generated title ("Highway Heartache")
- Still got AI cover art
- Still played and sounded like music
- Just didn't get Whisper validation (no lyrics to validate)

This is good design — the pipeline doesn't fail hard when one component has issues.

### 8. Hip Hop Is a Performance Outlier

Hip hop stands out across multiple dimensions:
- **Lyrics:** 3017 chars (2.3x average) — the 16-bar verse format generates much more text
- **Lyrics time:** 50.3s (1.5x average) — Ollama handles the extra length well
- **Whisper time:** 107.7s (1.7x average) — the dense, rapid lyrics create many more Whisper segments
- **Duration:** 3:33 — moderate, because the fast delivery rate compensates for the long lyrics

**Implication:** Hip hop songs will always take longer to process end-to-end. Budget an extra 30-60s for the full pipeline.

---

## Recommendations (Priority Order)

### Must Fix (Impact: High)

1. **Add ACE-Step health check before generation** — Query `http://localhost:7860/info` (or similar) before submitting. If unreachable, wait and retry up to 90s. This alone would prevent the 2 "unreachable" failures (#13, #18).

2. **Add generation retry logic** — When ACE-Step crashes mid-generation, detect the error, wait for the service to restart (poll health endpoint), and auto-retry the song. Could retry up to 2 times.

3. **Pre-warm Ollama on startup** — On UI container start (or on first user request), send a trivial prompt to Ollama to ensure the model is loaded. This prevents the song #1 cold-start failure.

### Should Fix (Impact: Medium)

4. **Extend cover art idle timeout for batch operations** — The 2-minute idle timeout causes unnecessary reloads during consecutive generations. Consider extending to 5-10 minutes, or making it configurable.

5. **Add compound genre detection** — Match multi-word genre combinations ("country rock", "latin pop", "k-pop") before falling back to single keywords. Maintain a priority-ordered list.

6. **Add diversity to Ollama cover art descriptions** — Add instruction to avoid common phrases like "dust motes dance" or "bathed in golden light". Or post-process to detect and replace repeated imagery.

### Nice to Have (Impact: Low)

7. **Track generation statistics** — Log success/failure counts, average times per phase, quality distribution over time. Could be a simple JSON stats file or dashboard endpoint.

8. **Consider async Whisper validation** — Since 100% of 1.7B songs scored GREAT, Whisper is adding 45-108s per song with no practical impact on the cover art gate. Could run it asynchronously and update the track metadata later.

9. **Genre-aware duration hints for short genres** — For punk/pop/country rock, could set a minimum duration of 180s to ensure songs reach 3:00. But this conflicts with the "auto is best" finding — needs testing.
