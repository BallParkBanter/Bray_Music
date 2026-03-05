# ACE-Step Audio Validation Reference

## Verified End-to-End Results (2026-03-04)

### Duration Tests — ALL PASS Up to 8 Minutes
- Instrumental: 3.5, 4, 4.5, 5, 6, 7, 8 min — all pass
- Vocals: 4, 5, 6, 8 min with full lyrics (3 verses, chorus after each, bridge, outro) — all pass
- System: 14GB RAM + 20GB swap. Swap peaks at ~19GB for 8-min songs. No OOM.
- Earlier OOM at 4 min was a one-time fluke under heavy memory pressure from rapid-fire tests.

### Whisper Quality Results
- **8-min prog rock** (user lyrics, V1/Chorus/V2/Chorus/V3/Bridge/Chorus/Outro): 39 segments, 89% good, chorus repeats correctly
- **5-min indie folk** (AI lyrics via Ollama): 47 segments, 97% good, near-perfect transcription match
- **Quality threshold:** avg_logprob > -0.8 AND no_speech_prob < 0.5 = "good"

### Cover Art: Working End-to-End
- Nextcloud Task Processing → Visionatrix juggernaut_xl → ~6 min on GTX 1060
- Image downloaded via `/ocs/v2.php/taskprocessing/tasks/{taskId}/file/{fileId}`
- Resized to 512x512, saved to covers/ directory, track metadata updated

## Key Parameter Corrections (2026-03-04)

- **CaptionRewrite (api[35])** = ONLY rewrites the caption/description text. Does NOT generate lyrics. i18n: "Use LM to rewrite caption before generation."
- **AutoGen (api[49])** = "Automatically start next batch after completion." NOT a lyrics generator.
- **Auto Score (api[39])** = Built-in perplexity-based "DiT Lyrics Alignment Score" — measures how well lyrics align with audio.
- **NEITHER CaptionRewrite NOR AutoGen generates lyrics.** Both were wrong approaches.

## How Simple Mode Actually Works (from source code)

Gradio UI Simple Mode is a TWO-STEP process:
1. "Create Sample" button calls `create_sample()` (in `acestep/inference.py:951`) which uses the LM to generate caption, lyrics, BPM, key, duration from a natural language query
2. Those values fill Custom mode fields, then user clicks "Generate Music" with real pre-generated lyrics

**For API usage:** The REST API (port 8001) has `/format_input` endpoint that does the same thing — takes prompt+lyrics and returns enhanced caption+lyrics+metadata. But the REST API server must be started separately from Gradio.

**For Bray Music Studio:** Need to either:
- Enable ACE-Step REST API (port 8001) and call `/format_input` before `generation_wrapper`
- Or use Ollama/another LLM to generate lyrics from description before calling ACE-Step

## Automated Validation Pipeline

### Recommended: Demucs + Whisper + WER

```
Generate audio → Demucs vocal separation → Whisper transcribe → Compare lyrics via WER
```

1. **Demucs** (`pip install demucs`) — vocal isolation
   - Model: `mdx_extra` for best quality
   - Reduces WER from ~29% to ~25% vs raw audio

2. **Whisper** (`pip install openai-whisper`) — transcription
   - Use `large-v2` (NOT v3 — v3 has 4x higher WER on music)
   - `avg_logprob` per segment correlates with intelligibility
   - `avg_logprob < -0.8` → likely gibberish
   - `no_speech_prob` detects missing vocals in sections that should have them

3. **WER** (`pip install jiwer`) — word error rate
   - WER < 0.3 = likely intelligible
   - WER > 0.6 = likely gibberish/garbled
   - Normalize: remove vocables ("oh", "yeah") before comparison

### ACE-Step Built-in QA

- **Score Button** in Gradio UI calculates DiT Lyrics Alignment Score
- **Auto Score (api[39]=True)** runs this automatically per generation
- **Auto LRC (api[40]=True)** generates timestamped lyrics — validates lyrics presence

### Official Metrics (from ACE-Step paper)

- FAD (Frechet Audio Distance) — reference-free quality, lower=better
- CLAP Score — text-audio alignment
- Mulan Score — music-specific alignment
- SongEval — 5 dimensions: Coherence, Memorability, Naturalness, Clarity, Musicality
- AudioBox Aesthetics — Production Quality, Complexity, Enjoyment, Usefulness
- Whisper Forced Alignment — confidence scoring for lyric clarity

### Tools

| Tool | Install | Purpose |
|------|---------|---------|
| demucs | `pip install demucs` | Vocal separation |
| openai-whisper | `pip install openai-whisper` | Transcription |
| jiwer | `pip install jiwer` | WER calculation |
| fadtk | `pip install fadtk` | Frechet Audio Distance |
| frechet-audio-distance | `pip install frechet-audio-distance` | Lightweight FAD |

### Quality Parameters (from community experiments)

- **Guidance Interval (api[22]-api[23])**: Higher (0.5-0.75) → fewer lyrics artifacts, cleaner vocals
- **CFG Scale (api[7])**: High → pronounced vocals; too low → poor results
- **LM Temperature (api[28])**: 0.85 default; lower = more deterministic
- **Scheduler**: Euler produces clearer vocals than Heun (clips)

### Known Limitations

- Gibberish vocals are acknowledged in docs: "Coarse vocal synthesis lacking nuance"
- Language mixing produces bad results
- Skipped/repeated/garbled lyrics are common stochastic artifacts
- Generate 2-4 versions and pick best (community consensus)
- No single automated metric reliably predicts human quality perception
