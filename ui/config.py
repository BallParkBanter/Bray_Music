import os
from pathlib import Path

ACESTEP_URL = os.environ.get("ACESTEP_URL", "http://ace-step:7860")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.1.145:11434")
WHISPER_URL = os.environ.get("WHISPER_URL", "http://host.docker.internal:7862")
COVER_ART_URL = os.environ.get("COVER_ART_URL", "http://host.docker.internal:7863")

OUTPUTS_DIR = Path(os.environ.get("OUTPUTS_DIR", "/app/outputs"))
COVERS_DIR = OUTPUTS_DIR / "covers"
AUDIO_DIR = OUTPUTS_DIR / "api_audio"
HISTORY_FILE = OUTPUTS_DIR / "history.json"
PLAYLISTS_FILE = OUTPUTS_DIR / "playlists.json"

# Ensure dirs exist at startup
COVERS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
