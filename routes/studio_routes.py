"""Owner-private Understanding Studio dry-run episodes."""

import hashlib
import io
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.studio.compiler import compile_storyboard, edit_storyboard, render_preview, save_timeline
from src.auth_helpers import effective_user, require_chat_api_token_scope
from src.runtime_paths import get_default_data_dir


router = APIRouter(prefix="/api/studio", tags=["studio"],
                   dependencies=[Depends(require_chat_api_token_scope)])


class EpisodeInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    outline: str = Field(min_length=1, max_length=12000)
    render_preview: bool = True


class TimelineEdit(BaseModel):
    action: str
    shot_id: str
    index: int | None = None
    title: str | None = None
    visual_prompt: str | None = None
    narration_text: str | None = None
    duration: float | None = None
    at_seconds: float | None = None
    render_preview: bool = False


def _owner_dir(owner: str | None) -> Path:
    digest = hashlib.sha256(str(owner or "single-user").encode("utf-8")).hexdigest()[:24]
    return Path(get_default_data_dir()) / "studio" / digest


def _episode_dir(owner: str | None, episode_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", episode_id):
        raise HTTPException(404, "Episode not found")
    return _owner_dir(owner) / episode_id


@router.post("/episodes", status_code=201)
def create_episode(request: Request, payload: EpisodeInput):
    try:
        timeline = compile_storyboard(payload.title, payload.outline)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    directory = _episode_dir(effective_user(request), timeline["episode_id"])
    save_timeline(timeline, directory)
    preview_url = None
    if payload.render_preview:
        try:
            render_preview(timeline, directory)
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error
        preview_url = f"/api/studio/episodes/{timeline['episode_id']}/preview"
    return {"timeline": timeline, "preview_url": preview_url}


@router.get("/episodes/{episode_id}/timeline")
def get_timeline(request: Request, episode_id: str):
    destination = _episode_dir(effective_user(request), episode_id) / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    return FileResponse(destination, media_type="application/json")


@router.patch("/episodes/{episode_id}/timeline")
def update_timeline(request: Request, episode_id: str, edit: TimelineEdit):
    directory = _episode_dir(effective_user(request), episode_id)
    destination = directory / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    timeline = json.loads(destination.read_text(encoding="utf-8"))
    try:
        timeline = edit_storyboard(timeline, edit.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    preview = directory / "preview.mp4"
    if edit.render_preview:
        try:
            render_preview(timeline, directory)
        except RuntimeError as error:
            raise HTTPException(503, str(error)) from error
    else:
        preview.unlink(missing_ok=True)
    save_timeline(timeline, directory)
    return {"timeline": timeline,
            "preview_url": f"/api/studio/episodes/{episode_id}/preview" if edit.render_preview else None}


@router.post("/episodes/{episode_id}/shots/{shot_id}/still")
def upload_shot_still(request: Request, episode_id: str, shot_id: str,
                      image: UploadFile = File(...)):
    """Attach a local still to one shot and refresh the GPU-free preview."""
    from PIL import Image, UnidentifiedImageError

    directory = _episode_dir(effective_user(request), episode_id)
    destination = directory / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    timeline = json.loads(destination.read_text(encoding="utf-8"))
    shot = next((clip for clip in timeline["tracks"]["video"] if clip["id"] == shot_id), None)
    if shot is None:
        raise HTTPException(404, "Shot not found")
    raw = image.file.read(20_000_001)
    if len(raw) > 20_000_000:
        raise HTTPException(413, "Still image exceeds 20 MB")
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            if decoded.format not in {"PNG", "JPEG", "WEBP"} or decoded.width * decoded.height > 24_000_000:
                raise ValueError("Still must be PNG, JPEG, or WebP under 24 megapixels")
            frame = decoded.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise HTTPException(422, f"Invalid still image: {error}") from error
    assets = directory / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + ".jpg"
    frame.save(assets / filename, format="JPEG", quality=92)
    shot["media_path"] = f"assets/{filename}"
    shot["placeholder"] = False
    try:
        render_preview(timeline, directory)
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    save_timeline(timeline, directory)
    return {"timeline": timeline,
            "preview_url": f"/api/studio/episodes/{episode_id}/preview",
            "still_url": f"/api/studio/episodes/{episode_id}/shots/{shot_id}/still"}


@router.get("/episodes/{episode_id}/shots/{shot_id}/still")
def get_shot_still(request: Request, episode_id: str, shot_id: str):
    directory = _episode_dir(effective_user(request), episode_id)
    destination = directory / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    timeline = json.loads(destination.read_text(encoding="utf-8"))
    shot = next((clip for clip in timeline["tracks"]["video"] if clip["id"] == shot_id), None)
    if not shot or not shot.get("media_path"):
        raise HTTPException(404, "Still not found")
    relative = Path(shot["media_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(404, "Still not found")
    image_path = directory / relative
    if not image_path.is_file():
        raise HTTPException(404, "Still not found")
    return FileResponse(image_path, media_type="image/jpeg")


@router.post("/episodes/{episode_id}/shots/{shot_id}/narration")
def upload_shot_narration(request: Request, episode_id: str, shot_id: str,
                          audio: UploadFile = File(...)):
    directory = _episode_dir(effective_user(request), episode_id)
    destination = directory / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    timeline = json.loads(destination.read_text(encoding="utf-8"))
    clip = next((item for item in timeline["tracks"]["narration"] if item["id"] == shot_id), None)
    if clip is None:
        raise HTTPException(404, "Shot not found")
    extension = Path(audio.filename or "").suffix.lower()
    if extension not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
        raise HTTPException(422, "Narration must be WAV, MP3, M4A, OGG, or FLAC")
    raw = audio.file.read(25_000_001)
    if len(raw) > 25_000_000:
        raise HTTPException(413, "Narration exceeds 25 MB")
    audio_dir = directory / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    filename = uuid.uuid4().hex + extension
    source = audio_dir / filename
    source.write_bytes(raw)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        source.unlink(missing_ok=True)
        raise HTTPException(503, "FFmpeg is required for narration")
    try:
        check = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(source),
                                "-vn", "-t", "0.1", "-f", "null", "-"],
                               capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired as error:
        source.unlink(missing_ok=True)
        raise HTTPException(422, "Narration decode timed out") from error
    if check.returncode != 0:
        source.unlink(missing_ok=True)
        raise HTTPException(422, "Invalid narration audio")
    clip["audio_path"] = f"audio/{filename}"
    clip["audio_offset"] = 0.0
    clip["placeholder"] = False
    try:
        render_preview(timeline, directory, ffmpeg=ffmpeg)
    except RuntimeError as error:
        source.unlink(missing_ok=True)
        raise HTTPException(503, str(error)) from error
    save_timeline(timeline, directory)
    return {"timeline": timeline,
            "preview_url": f"/api/studio/episodes/{episode_id}/preview",
            "audio_url": f"/api/studio/episodes/{episode_id}/shots/{shot_id}/narration"}


@router.get("/episodes/{episode_id}/shots/{shot_id}/narration")
def get_shot_narration(request: Request, episode_id: str, shot_id: str):
    directory = _episode_dir(effective_user(request), episode_id)
    destination = directory / "timeline.json"
    if not destination.is_file():
        raise HTTPException(404, "Episode not found")
    timeline = json.loads(destination.read_text(encoding="utf-8"))
    clip = next((item for item in timeline["tracks"]["narration"] if item["id"] == shot_id), None)
    if not clip or not clip.get("audio_path"):
        raise HTTPException(404, "Narration not found")
    relative = Path(clip["audio_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(404, "Narration not found")
    audio_path = directory / relative
    if not audio_path.is_file():
        raise HTTPException(404, "Narration not found")
    media_types = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
                   ".ogg": "audio/ogg", ".flac": "audio/flac"}
    return FileResponse(audio_path, media_type=media_types.get(audio_path.suffix, "application/octet-stream"))


@router.get("/episodes/{episode_id}/preview")
def get_preview(request: Request, episode_id: str):
    destination = _episode_dir(effective_user(request), episode_id) / "preview.mp4"
    if not destination.is_file():
        raise HTTPException(404, "Preview not found")
    return FileResponse(destination, media_type="video/mp4")
