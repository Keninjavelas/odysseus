import json
import shutil

import pytest
from fastapi import HTTPException
from types import SimpleNamespace

from services.studio.compiler import compile_storyboard, edit_storyboard, render_preview, save_timeline
from routes import studio_routes


def test_storyboard_produces_editable_aligned_tracks(tmp_path):
    timeline = compile_storyboard("Ocean Change", "Opening scene\nSpecies migrate north")
    assert timeline["duration"] == 6
    assert len(timeline["tracks"]["video"]) == 2
    assert [clip["start"] for clip in timeline["tracks"]["video"]] == [0, 3]
    assert all(clip["placeholder"] for clip in timeline["tracks"]["narration"])
    saved = save_timeline(timeline, tmp_path)
    assert json.loads(saved.read_text(encoding="utf-8")) == timeline


def test_storyboard_preview_renders_without_gpu(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    timeline = compile_storyboard("Ocean Change", "Opening scene\nSpecies migrate north")
    preview = render_preview(timeline, tmp_path)
    assert preview.is_file()
    assert preview.stat().st_size > 1000


def test_storyboard_rejects_empty_or_unbounded_outline():
    with pytest.raises(ValueError):
        compile_storyboard("Ocean", "")
    with pytest.raises(ValueError):
        compile_storyboard("Ocean", "\n".join("beat" for _ in range(25)))


def test_storyboard_edit_keeps_three_lanes_aligned():
    timeline = compile_storyboard("Ocean", "One\nTwo\nThree")
    edit_storyboard(timeline, {"action": "move_shot", "shot_id": "shot-003", "index": 0})
    edit_storyboard(timeline, {"action": "set_shot", "shot_id": "shot-003",
                               "duration": 7, "narration_text": "New voiceover"})
    assert [clip["id"] for clip in timeline["tracks"]["video"]] == ["shot-003", "shot-001", "shot-002"]
    assert [clip["start"] for clip in timeline["tracks"]["video"]] == [0, 7, 10]
    assert timeline["tracks"]["captions"][0]["text"] == "New voiceover"
    assert timeline["duration"] == 13


def test_episode_api_keeps_each_owners_timeline_private(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_routes, "get_default_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(studio_routes, "effective_user", lambda request: request.owner)
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    created = studio_routes.create_episode(
        alice, studio_routes.EpisodeInput(title="Ocean", outline="First beat", render_preview=False))
    episode_id = created["timeline"]["episode_id"]
    edited = studio_routes.update_timeline(
        alice, episode_id, studio_routes.TimelineEdit(
            action="set_shot", shot_id="shot-001", duration=8))
    assert edited["timeline"]["duration"] == 8
    assert studio_routes.get_timeline(alice, episode_id).path.name == "timeline.json"
    with pytest.raises(HTTPException) as denied:
        studio_routes.get_timeline(bob, episode_id)
    assert denied.value.status_code == 404
