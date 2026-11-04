"""Deterministic documentary storyboard compiler and GPU-free preview renderer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path


def compile_storyboard(title: str, outline: str, *, episode_id: str | None = None) -> dict:
    """Turn explicit outline beats into an editable three-lane timeline.

    The dry run treats every nonempty paragraph or line as a beat. It does not
    claim that a topic-only input has been researched or that narration exists.
    """
    title = str(title or "").strip()
    if not title or len(title) > 160:
        raise ValueError("title must contain 1-160 characters")
    beats = [line.strip(" -\t") for line in re.split(r"\n+", str(outline or ""))
             if line.strip(" -\t")]
    if not beats or len(beats) > 24:
        raise ValueError("outline must contain 1-24 nonempty beats")
    if any(len(beat) > 1000 for beat in beats):
        raise ValueError("each outline beat must be at most 1000 characters")
    video, narration, captions = [], [], []
    cursor = 0.0
    for index, beat in enumerate(beats, start=1):
        duration = float(max(3, min(12, round(len(beat.split()) / 2.5))))
        clip_id = f"shot-{index:03d}"
        common = {"id": clip_id, "start": cursor, "duration": duration}
        video.append({**common, "title": beat[:100], "visual_prompt": beat,
                      "media_path": None, "motion": "static", "placeholder": True})
        narration.append({**common, "text": beat, "audio_path": None,
                          "placeholder": True})
        captions.append({**common, "text": beat})
        cursor += duration
    return {
        "schema_version": "1.0",
        "episode_id": episode_id or str(uuid.uuid4()),
        "title": title,
        "duration": cursor,
        "render_mode": "dry_run",
        "tracks": {"video": video, "narration": narration, "captions": captions},
    }


def save_timeline(timeline: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "timeline.json"
    temporary = directory / "timeline.json.tmp"
    temporary.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return destination


def edit_storyboard(timeline: dict, operation: dict) -> dict:
    """Edit shot text, duration, or order while keeping every lane aligned."""
    kind = operation.get("action")
    shot_id = operation.get("shot_id")
    video = timeline["tracks"]["video"]
    narration = timeline["tracks"]["narration"]
    captions = timeline["tracks"]["captions"]
    matches = [index for index, clip in enumerate(video) if clip["id"] == shot_id]
    if len(matches) != 1:
        raise ValueError("shot_id must identify exactly one shot")
    index = matches[0]
    if kind == "set_shot":
        for key in ("title", "visual_prompt", "narration_text"):
            if key in operation and (not isinstance(operation[key], str)
                                     or not operation[key].strip() or len(operation[key]) > 1000):
                raise ValueError(f"{key} must contain 1-1000 characters")
        if "title" in operation:
            video[index]["title"] = operation["title"].strip()
        if "visual_prompt" in operation:
            video[index]["visual_prompt"] = operation["visual_prompt"].strip()
        if "narration_text" in operation:
            narration[index]["text"] = operation["narration_text"].strip()
            captions[index]["text"] = operation["narration_text"].strip()
        if "duration" in operation:
            duration = operation["duration"]
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 30:
                raise ValueError("duration must be between 1 and 30 seconds")
            for track in (video, narration, captions):
                track[index]["duration"] = float(duration)
    elif kind == "move_shot":
        target = operation.get("index")
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target < len(video):
            raise ValueError("index must be a valid zero-based shot position")
        for track in (video, narration, captions):
            track.insert(target, track.pop(index))
    else:
        raise ValueError("action must be set_shot or move_shot")
    cursor = 0.0
    for offset in range(len(video)):
        duration = float(video[offset]["duration"])
        for track in (video, narration, captions):
            track[offset]["start"] = cursor
            track[offset]["duration"] = duration
        cursor += duration
    timeline["duration"] = cursor
    return timeline


def _draw_card(title: str, beat: str, destination: Path, number: int) -> None:
    from PIL import Image, ImageDraw, ImageFont

    frame = Image.new("RGB", (960, 540), (18, 25, 38))
    draw = ImageDraw.Draw(frame)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
        body_font = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
        body_font = font
    draw.rectangle((0, 0, 960, 12), fill=(82, 166, 218))
    draw.text((55, 55), title[:48], fill=(240, 244, 250), font=font)
    draw.text((55, 125), f"SHOT {number:02d}  ·  STORYBOARD PREVIEW", fill=(100, 190, 225), font=body_font)
    wrapped = textwrap.wrap(beat, width=53, max_lines=7, placeholder="…")
    for line_no, line in enumerate(wrapped):
        draw.text((55, 200 + line_no * 38), line, fill=(222, 229, 236), font=body_font)
    frame.save(destination)


def render_preview(timeline: dict, directory: Path, *, ffmpeg: str | None = None) -> Path:
    """Render placeholder shot cards with silent audio; requires no GPU."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for storyboard preview rendering")
    directory.mkdir(parents=True, exist_ok=True)
    concat_file = directory / "frames.ffconcat"
    lines = ["ffconcat version 1.0"]
    clips = timeline["tracks"]["video"]
    for index, clip in enumerate(clips, start=1):
        frame_name = f"shot-{index:03d}.png"
        _draw_card(timeline["title"], clip["visual_prompt"], directory / frame_name, index)
        lines.extend((f"file {frame_name}", f"duration {clip['duration']}"))
    lines.append(f"file shot-{len(clips):03d}.png")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = directory / "preview.mp4"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(concat_file),
               "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
               "-vf", "fps=12,format=yuv420p", "-t", str(timeline["duration"]),
               "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
               "-b:a", "96k", "-movflags", "+faststart", str(output)]
    try:
        subprocess.run(command, cwd=directory, check=True, capture_output=True,
                       text=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        output.unlink(missing_ok=True)
        detail = getattr(error, "stderr", "") or str(error)
        raise RuntimeError(f"FFmpeg preview failed: {detail[-600:]}") from error
    return output
