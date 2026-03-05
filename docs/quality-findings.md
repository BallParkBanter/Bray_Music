# Bray Music Studio — Quality Findings (2026-03-05)

## Whisper Audit Methodology
- Tool: faster-whisper, medium model, int8, CPU on ROG-STRIX
- ~5-10 seconds per track analysis
- VAD filter enabled (min_silence_duration_ms=500)
- Script: `/tmp/audit_album.py` on ROG-STRIX

## Quality Thresholds
- **GREAT**: good_pct >= 80% AND avg_logprob > -0.6
- **GOOD**: good_pct >= 60% AND avg_logprob > -0.8
- **FAIR**: good_pct >= 40%
- **POOR**: everything else
- **Good segment**: avg_logprob > -0.8 AND no_speech_prob < 0.5

## "Unbreakable Fire" Album Results (15 tracks, all vocal)
- GREAT: 5 tracks (33%) — Unbreakable Fire, Scars of Grace, Rise From the Ashes, Light in the Dark, Dead Man Walking
- GOOD: 1 track (7%) — The Void Inside
- POOR: 7 tracks (47%) — Warriors Cry, Still Standing, Fortress, Surrender, Through the Storm, Redemption Road, Eternal
- NO VOCALS: 2 tracks (13%) — Breaking Chains (160 BPM), Battle Ready (165 BPM)

## Key Patterns Discovered

### BPM vs Vocal Quality
- **85-100 BPM (ballads)**: Best vocal quality. Scars of Grace (85) and Light in the Dark (90) both GREAT.
- **100-150 BPM (mid-tempo)**: Mixed results. Some GREAT, some POOR.
- **155+ BPM (fast)**: Unreliable. Rise From the Ashes (155) = GREAT but an outlier.
- **160+ BPM**: Vocal generation fails completely. Both 160+ BPM tracks produced instrumental output.

### Word Count Issue
- Even GREAT-rated tracks only have 13-27 Whisper-detected words vs 200+ words in the input lyrics
- ACE-Step synthesizes vocal-like sounds that follow melody but many words are mushy/unintelligible
- This is a known ACE-Step limitation, not a BMS issue

### Genre Test Battery (10 songs, mixed vocal/instrumental)
All 10 genres produced coherent audio output:
- Rock, Pop/Synthwave, Country, Hip Hop, Jazz, Ambient, Metal, Classical, Latin, Blues
- Generation time: 144-221s per track
- Instrumental tracks are consistently high quality
- Vocal quality varies significantly (stochastic)

## Recommendations for Future Improvements
1. **"Regenerate" button** — Highest value feature. Generate 3-4 versions, keep the best.
2. **Post-generation quality check** — Run Whisper analysis automatically, warn user when vocals are weak
3. **BPM guidance** — Warn user when BPM > 155 that vocals may not generate
4. **Album mode** — Define style template, apply to multiple tracks, batch generate sequentially
5. **Lyrics review step** — Let user edit AI lyrics before sending to ACE-Step
