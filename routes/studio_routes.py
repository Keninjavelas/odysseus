"""Owner-private Understanding Studio dry-run episodes."""

import hashlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
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


@router.get("/episodes/{episode_id}/preview")
def get_preview(request: Request, episode_id: str):
    destination = _episode_dir(effective_user(request), episode_id) / "preview.mp4"
    if not destination.is_file():
        raise HTTPException(404, "Preview not found")
    return FileResponse(destination, media_type="video/mp4")
