# ACE-Step 1.5 — As-Built Documentation

**Date completed:** 2026-03-04 (native install, replacing Docker deployment)
**Host:** bobray-ROG-STRIX (192.168.1.153)
**GPU:** NVIDIA GeForce GTX 1080 Ti (Pascal, sm_61, 11 GB VRAM)

---

## What Is ACE-Step

ACE-Step 1.5 is an open-source full-song AI music generator capable of producing vocals, lyrics, and instruments simultaneously. It runs a Gradio web interface and a REST API.

- **GitHub:** https://github.com/ACE-Step/ACE-Step-1.5
- **Models:** DiT (Diffusion Transformer) + Language Model (0.6B)
- **Output:** FLAC, 48kHz lossless
- **Max duration:** 480 seconds (8 minutes) with LM on GPU tier 4
- **Gradio port:** 7860

---

## Host: bobray-ROG-STRIX

| Property | Value |
|---|---|
| IP | 192.168.1.153 |
| OS | Ubuntu 24.04 LTS |
| GPU | GTX 1080 Ti, Pascal sm_61, 11 GB VRAM |
| Driver | nvidia-driver-580 (do NOT upgrade to 590+, Pascal support dropped) |
| SSH | `ssh bobray@192.168.1.153` |

---

## Installation

ACE-Step 1.5 is installed natively (no Docker) at `/home/bobray/ACE-Step-1.5/` on ROG-STRIX.

### Directory Layout

```
/home/bobray/ACE-Step-1.5/
├── .venv/                     ← Python 3.12 virtual environment
├── .env                       ← Environment variables for systemd service
├── pyproject.toml             ← Modified to pin cu124 PyTorch versions
├── checkpoints/               ← All model weights
│   ├── acestep-v15-turbo/
│   ├── acestep-v15-base/
│   ├── acestep-v15-sft/
│   ├── acestep-5Hz-lm-0.6B/
│   ├── acestep-5Hz-lm-4B/
│   ├── turbo-shift1/
│   ├── turbo-shift3/
│   └── turbo-continuous/
└── acestep/                   ← Source code
```

### How It Was Installed

```bash
cd /home/bobray
git clone https://github.com/ACE-Step/ACE-Step-1.5
cd ACE-Step-1.5
```

The `pyproject.toml` was modified to pin CUDA 12.4 PyTorch versions. The upstream default uses cu128, which dropped Pascal sm_61 support. The cu124 arch list includes sm_50 and sm_60 -- sm_60 SASS runs on sm_61 via CUDA backward compatibility.

```bash
uv sync
```

- **Package manager:** uv (installed at `/home/bobray/.local/bin/uv`)
- **Virtual environment:** `/home/bobray/ACE-Step-1.5/.venv/`
- **Python:** 3.12

### PyTorch/CUDA Versions

| Package | Version |
|---|---|
| torch | 2.6.0+cu124 |
| torchaudio | 2.6.0+cu124 |
| torchvision | 0.21.0+cu124 |

### No Manual Patches Required

Unlike the previous Docker-based deployment which required 6 manual patches for Pascal compatibility, the native installation needs zero patches. ACE-Step's built-in GPU tier system automatically detects the hardware and configures everything correctly.

---

## GPU Tier Auto-Detection

The GTX 1080 Ti (10.9 GB VRAM) is classified as **Tier 4**. ACE-Step automatically configures:

| Setting | Value |
|---|---|
| DiT model | acestep-v15-turbo (8 inference steps) |
| LM model | acestep-5Hz-lm-0.6B (PyTorch backend, on CUDA) |
| INT8 quantization | Enabled (for DiT) |
| Attention | SDPA (flash attention correctly detected as unavailable on sm_61) |
| CPU + DiT offload | Enabled |

The nano-vllm component attempts Triton (which requires sm_70+), then automatically falls back to the PyTorch backend. No manual intervention needed.

---

## Service Management

ACE-Step runs as a systemd service.

### systemd Unit File

**Location:** `/etc/systemd/system/acestep.service`

Key properties:
- **User:** bobray
- **WorkingDirectory:** /home/bobray/ACE-Step-1.5
- **EnvironmentFile:** /home/bobray/ACE-Step-1.5/.env
- **ExecStart:** `/home/bobray/.local/bin/uv run acestep --server-name 0.0.0.0 --port 7860 --init_service true`
- **Restart:** on-failure, 10s delay

### Commands

```bash
# Start/stop/restart
sudo systemctl start acestep
sudo systemctl stop acestep
sudo systemctl restart acestep

# Check status
sudo systemctl status acestep

# View logs (follow mode)
journalctl -u acestep -f
```

### Environment File

**Location:** `/home/bobray/ACE-Step-1.5/.env`

```bash
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B
ACESTEP_LM_BACKEND=pt
ACESTEP_DEVICE=auto
ACESTEP_INIT_LLM=auto
SERVER_NAME=0.0.0.0
PORT=7860
```

---

## VRAM Budget (GTX 1080 Ti 11 GB)

| State | VRAM Used |
|---|---|
| Desktop (Xorg + GNOME + RDP) | ~330 MiB always-on |
| ACE-Step idle (models loaded, CPU offload) | ~624 MiB |
| Combined idle | ~960 MiB |
| Peak during generation | ~6-7 GB |
| Headroom remaining during generation | ~4 GB |

---

## Performance

| Metric | Value |
|---|---|
| Total generation time | ~60-120 seconds (varies by song length) |
| LM phase | ~40-70 seconds |
| DiT phase | ~23-45 seconds |
| Output format | FLAC, 48kHz lossless |
| Max duration | Up to 8 minutes with LM (per GPU tier 4 config) |

---

## Gradio API

ACE-Step exposes a Gradio API on port 7860.

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/gradio_api/call/generation_wrapper` | POST | Submit generation request |
| `/gradio_api/call/generation_wrapper/{event_id}` | GET | Poll for results (SSE stream) |
| `/gradio_api/info` | GET | API schema info |

### Submit a Generation

```bash
curl -X POST http://localhost:7860/gradio_api/call/generation_wrapper \
  -H "Content-Type: application/json" \
  -d '{"data": [<55-element array>]}'
```

Returns:
```json
{"event_id": "UUID"}
```

### Poll for Results

```bash
curl http://localhost:7860/gradio_api/call/generation_wrapper/{event_id}
```

Returns an SSE stream with generation progress and final output.

### Parameter Mapping (55 Parameters)

The API info reports 50 parameters, but the handler expects 55 (5 hidden State components).

- **API params 0-36** map directly to real positions 0-36
- **State 1** occupies real position 37 (hidden)
- **API params 37-49** shift +1 to real positions 38-50
- **States 2-5** occupy real positions 51-54 (hidden)

Key parameters (by API position):
- `audio_duration`: float, default -1 (auto), max 480 sec
- `prompt`: text describing the music style/mood/instruments
- `lyrics`: full lyrics text (or empty for AI-generated)
- `infer_step`: inference steps (8 for turbo model)
- `guidance_scale`: float, creativity vs. prompt adherence
- `seed`: int, -1 for random

---

## NPM Proxy Setup

NPM is on BrayNextcloudServer (192.168.1.103), container `npm-app-1`.

| Field | Value |
|---|---|
| Proxy Host DB ID | 37 |
| Domain | music.apps.bray.house |
| Forward to | 192.168.1.153:7861 (custom UI) |
| SSL Cert DB ID | 31 (`*.apps.bray.house`) |
| nginx conf | `/data/nginx/proxy_host/37.conf` |

- **music.apps.bray.house** routes to port 7861 (Bray Music Studio custom UI)
- **Raw Gradio** at http://192.168.1.153:7860 is accessible on LAN only (direct)

---

## Troubleshooting

### Check Service Status

```bash
sudo systemctl status acestep
```

If the service is not running, check the logs:

```bash
journalctl -u acestep -f
```

### Check GPU Status

```bash
nvidia-smi
```

Verify the GPU is detected and VRAM usage is reasonable. If VRAM exceeds 10 GB, something has leaked.

### Check if Gradio Is Responding

```bash
curl http://localhost:7860/
```

If this fails but the service shows as active, the Gradio server may still be loading models. Wait 30-60 seconds and try again.

### Models Fail to Load

Check `journalctl -u acestep -f` for the error. Common causes:

- Missing checkpoint files in `/home/bobray/ACE-Step-1.5/checkpoints/`
- VRAM exhaustion during model loading (check `nvidia-smi`)
- Wrong environment variable values in `.env`

### Generation Hangs or Produces No Output

```bash
# Restart the service
sudo systemctl restart acestep

# Watch logs during restart
journalctl -u acestep -f
```

### music.apps.bray.house Unreachable

Check NPM on BrayNextcloudServer:

```bash
ssh bobray@192.168.1.103
docker exec npm-app-1 nginx -t
docker exec npm-app-1 nginx -s reload
```

Also verify that the ACE-Step service is running on ROG-STRIX and that the custom UI on port 7861 is responding.
