"""File storage for syllabus PDFs and generated audio.

Local disk for MVP behind a narrow interface, so swapping in S3-compatible
blob storage later (PRD section 10) touches only this module.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Tuple

from app.config import settings

BASE_DIR = Path(__file__).resolve().parents[2]


def _resolve(subdir: str) -> Path:
    path = BASE_DIR / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(data: bytes, filename: str) -> Tuple[str, Path]:
    """Store an uploaded file. Returns (public_url, absolute_path)."""
    suffix = Path(filename).suffix.lower() or ".bin"
    name = f"{uuid.uuid4().hex}{suffix}"
    path = _resolve(settings.upload_dir) / name
    path.write_bytes(data)
    return f"/files/uploads/{name}", path


def save_audio(data: bytes, extension: str = ".mp3") -> Tuple[str, Path]:
    name = f"{uuid.uuid4().hex}{extension}"
    path = _resolve(settings.audio_dir) / name
    path.write_bytes(data)
    return f"/files/audio/{name}", path


def uploads_dir() -> Path:
    return _resolve(settings.upload_dir)


def audio_dir() -> Path:
    return _resolve(settings.audio_dir)
