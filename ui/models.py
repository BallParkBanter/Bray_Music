from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class GenerateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=500)
    lyrics: str = Field(default="", max_length=5000)
    duration: float = Field(default=0, ge=0, le=8.0)  # 0 = auto (AI decides length)
    include_vocals: bool = True
    enhance_lyrics: bool = False
    bpm: str = ""
    key: str = ""
    creativity: int = Field(default=50, ge=0, le=100)
    seed: str = ""


class TrackMeta(BaseModel):
    id: str
    title: str
    description: str
    genre_hint: str = ""
    duration_sec: float
    filename: str
    cover_art: Optional[str] = None
    cover_gradient: str = "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    emoji: str = "🎵"
    created_at: str
    format: str = "FLAC"
    seed: int = 0
    lyrics: str = ""
    favorite: bool = False


class HistoryResponse(BaseModel):
    tracks: list[TrackMeta]
    total: int


class GenerateResponse(BaseModel):
    track: TrackMeta
    status: str = "ok"


class Playlist(BaseModel):
    id: str
    name: str
    track_ids: list[str] = []
    created_at: str
    cover_gradient: str = "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"


class PlaylistResponse(BaseModel):
    playlists: list[Playlist]
    total: int
