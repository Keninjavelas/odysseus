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
        narration.append({**common, "text": beat, "audio_path": None, "audio_offset": 0.0,
                          "placeholder": True})
        captions.append({**common, "text": beat})
        cursor += duration
    return {
        "schema_version": "1.0",
        "revision": 1,
        "episode_id": episode_id or str(uuid.uuid4()),
        "title": title,
        "duration": cursor,
        "render_mode": "dry_run",
        "tracks": {"video": video, "narration": narration, "captions": captions},
    }


def compile_subtitles(title: str, srt: str, *, episode_id: str | None = None) -> dict:
    """Build a silent rough cut from SRT cues, retaining source timecodes."""
    title = str(title or "").strip()
    if not title or len(title) > 160:
        raise ValueError("title must contain 1-160 characters")
    blocks = re.split(r"\n\s*\n", str(srt or "").lstrip("\ufeff").replace("\r\n", "\n").strip())
    if not blocks or len(blocks) > 60:
        raise ValueError("SRT must contain 1-60 cues")
    clock = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})$")

    def seconds(value: str) -> float:
        match = clock.fullmatch(value.strip())
        if not match:
            raise ValueError("invalid SRT timecode")
        hour, minute, second, millis = map(int, match.groups())
        if minute >= 60 or second >= 60:
            raise ValueError("invalid SRT timecode")
        return hour * 3600 + minute * 60 + second + millis / 1000

    video, narration, captions = [], [], []
    cursor = 0.0

    def append_shot(duration: float, text: str, source_start: float | None = None,
                    source_end: float | None = None) -> None:
        nonlocal cursor
        if len(video) >= 60:
            raise ValueError("SRT rough cut exceeds 60 shots including pauses")
        clip_id = f"shot-{len(video) + 1:03d}"
        common = {"id": clip_id, "start": round(cursor, 3), "duration": round(duration, 3)}
        label = text.splitlines()[0][:100] if text else "Pause"
        video.append({**common, "title": label, "visual_prompt": text or "Silence / B-roll",
                      "media_path": None, "motion": "static", "placeholder": True,
                      "source_start": source_start, "source_end": source_end})
        narration.append({**common, "text": text, "audio_path": None, "audio_offset": 0.0,
                          "placeholder": True, "source_start": source_start,
                          "source_end": source_end})
        captions.append({**common, "text": text})
        cursor = round(cursor + duration, 3)

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and lines[0].isdigit():
            lines.pop(0)
        if len(lines) < 2 or "-->" not in lines[0]:
            raise ValueError("invalid SRT cue")
        start_text, end_text = (part.strip() for part in lines[0].split("-->", 1))
        start, end = seconds(start_text), seconds(end_text)
        cue_text = "\n".join(lines[1:])
        if not cue_text or len(cue_text) > 1000 or not 0.1 <= end - start <= 30:
            raise ValueError("SRT cue needs text and a duration of 0.1-30 seconds")
        if start < cursor - 0.001:
            raise ValueError("SRT cues must be in order and must not overlap")
        gap = round(start - cursor, 3)
        while gap > 0:
            piece = min(30.0, gap)
            append_shot(piece, "")
            gap = round(gap - piece, 3)
        append_shot(round(end - start, 3), cue_text, start, end)
    if cursor > 300:
        raise ValueError("SRT rough cut must be at most five minutes")
    return {"schema_version": "1.0", "revision": 1,
            "episode_id": episode_id or str(uuid.uuid4()), "title": title,
            "duration": cursor, "render_mode": "transcript_rough_cut",
            "tracks": {"video": video, "narration": narration, "captions": captions}}


def save_timeline(timeline: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "timeline.json"
    temporary = directory / "timeline.json.tmp"
    temporary.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    write_subtitles(timeline, directory)
    return destination


def _srt_time(seconds: float) -> str:
    millis = round(float(seconds) * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    whole, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def write_subtitles(timeline: dict, directory: Path) -> Path:
    """Export the caption lane as an editable UTF-8 SRT sidecar."""
    entries = []
    for clip in timeline["tracks"]["captions"]:
        caption = str(clip.get("text") or "").strip()
        if not caption:
            continue
        start = float(clip["start"])
        end = start + float(clip["duration"])
        entries.append(f"{len(entries) + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{caption}\n")
    destination = directory / "captions.srt"
    destination.write_text("\n".join(entries), encoding="utf-8")
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
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0.1 <= duration <= 30:
                raise ValueError("duration must be between 0.1 and 30 seconds")
            for track in (video, narration, captions):
                track[index]["duration"] = float(duration)
    elif kind == "split_shot":
        if len(video) >= 60:
            raise ValueError("preview timelines support at most 60 shots")
        at_seconds = operation.get("at_seconds")
        duration = float(video[index]["duration"])
        if (isinstance(at_seconds, bool) or not isinstance(at_seconds, (int, float))
                or not 0.1 <= at_seconds <= round(duration - 0.1, 3)):
            raise ValueError("at_seconds must leave at least 0.1 second on each side")
        new_id = f"{shot_id}-part-{uuid.uuid4().hex[:8]}"
        for track in (video, narration, captions):
            original = track[index]
            latter = dict(original)
            latter["id"] = new_id
            latter["duration"] = duration - float(at_seconds)
            original["duration"] = float(at_seconds)
            if original.get("source_start") is not None and original.get("source_end") is not None:
                cut = min(float(original["source_end"]),
                          float(original["source_start"]) + float(at_seconds))
                latter["source_start"] = cut
                original["source_end"] = cut
            track.insert(index + 1, latter)
        # A duplicated transcript would appear twice in the export; the new
        # segment is deliberately empty until the editor writes its voiceover.
        narration[index + 1]["text"] = ""
        narration[index + 1]["audio_offset"] = float(narration[index].get("audio_offset") or 0) + float(at_seconds)
        captions[index + 1]["text"] = ""
    elif kind == "delete_shot":
        if len(video) == 1:
            raise ValueError("an episode must keep at least one shot")
        for track in (video, narration, captions):
            track.pop(index)
    elif kind == "move_shot":
        target = operation.get("index")
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target < len(video):
            raise ValueError("index must be a valid zero-based shot position")
        for track in (video, narration, captions):
            track.insert(target, track.pop(index))
    else:
        raise ValueError("action must be set_shot, split_shot, delete_shot, or move_shot")
    cursor = 0.0
    for offset in range(len(video)):
        duration = float(video[offset]["duration"])
        for track in (video, narration, captions):
            track[offset]["start"] = cursor
            track[offset]["duration"] = duration
        cursor += duration
    timeline["duration"] = cursor
    timeline["revision"] = int(timeline.get("revision") or 1) + 1
    return timeline


def _draw_card(title: str, beat: str, destination: Path, number: int,
               media_path: Path | None = None) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    if media_path is not None:
        if not media_path.is_file():
            raise RuntimeError(f"Shot {number} image is missing")
        with Image.open(media_path) as source:
            frame = ImageOps.fit(source.convert("RGB"), (960, 540))
    else:
        frame = Image.new("RGB", (960, 540), (18, 25, 38))
    draw = ImageDraw.Draw(frame)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 36)
        body_font = ImageFont.truetype("DejaVuSans.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
        body_font = font
    draw.rectangle((0, 0, 960, 12), fill=(82, 166, 218))
    if media_path is not None:
        draw.rectangle((0, 404, 960, 540), fill=(12, 18, 26))
        draw.text((40, 422), title[:48], fill=(240, 244, 250), font=font)
        draw.text((40, 480), f"SHOT {number:02d}", fill=(100, 190, 225), font=body_font)
    else:
        draw.text((55, 55), title[:48], fill=(240, 244, 250), font=font)
        draw.text((55, 125), f"SHOT {number:02d}  ·  STORYBOARD PREVIEW", fill=(100, 190, 225), font=body_font)
        wrapped = textwrap.wrap(beat, width=53, max_lines=7, placeholder="…")
        for line_no, line in enumerate(wrapped):
            draw.text((55, 200 + line_no * 38), line, fill=(222, 229, 236), font=body_font)
    frame.save(destination)


def render_preview(timeline: dict, directory: Path, *, ffmpeg: str | None = None) -> Path:
    """Render shot cards or stills with per-shot narration; requires no GPU."""
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for storyboard preview rendering")
    directory.mkdir(parents=True, exist_ok=True)
    concat_file = directory / "frames.ffconcat"
    lines = ["ffconcat version 1.0"]
    clips = timeline["tracks"]["video"]
    for index, clip in enumerate(clips, start=1):
        frame_name = f"shot-{index:03d}.png"
        media_path = None
        if clip.get("media_path"):
            relative = Path(clip["media_path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Shot image path is invalid")
            media_path = directory / relative
        _draw_card(clip["title"], clip["visual_prompt"], directory / frame_name,
                   index, media_path)
        lines.extend((f"file {frame_name}", f"duration {clip['duration']}"))
    lines.append(f"file shot-{len(clips):03d}.png")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    captions_file = write_subtitles(timeline, directory)
    audio_concat = directory / "audio.ffconcat"
    audio_lines = ["ffconcat version 1.0"]
    audio_segments = []
    try:
        for index, clip in enumerate(timeline["tracks"]["narration"], start=1):
            segment = directory / f"audio-segment-{index:03d}.wav"
            audio_segments.append(segment)
            duration = str(clip["duration"])
            if clip.get("audio_path"):
                relative = Path(clip["audio_path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise RuntimeError("Narration path is invalid")
                source = directory / relative
                if not source.is_file():
                    raise RuntimeError(f"Shot {index} narration is missing")
                offset = float(clip.get("audio_offset") or 0)
                audio_command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                 "-ss", str(offset), "-i", str(source), "-vn", "-af",
                                 f"apad,atrim=duration={duration},asetpts=PTS-STARTPTS",
                                 "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(segment)]
            else:
                audio_command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                 "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                                 "-t", duration, "-c:a", "pcm_s16le", str(segment)]
            subprocess.run(audio_command, cwd=directory, check=True, capture_output=True,
                           text=True, timeout=60)
            audio_lines.append(f"file {segment.name}")
        audio_concat.write_text("\n".join(audio_lines) + "\n", encoding="utf-8")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        for segment in audio_segments:
            segment.unlink(missing_ok=True)
        detail = getattr(error, "stderr", "") or str(error)
        raise RuntimeError(f"FFmpeg narration failed: {detail[-600:]}") from error
    output = directory / "preview.mp4"
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "concat", "-safe", "0", "-i", str(concat_file),
               "-f", "concat", "-safe", "0", "-i", str(audio_concat),
               ]
    if captions_file.stat().st_size:
        command.extend(["-i", str(captions_file)])
    command.extend(["-map", "0:v:0", "-map", "1:a:0"])
    if captions_file.stat().st_size:
        command.extend(["-map", "2:s:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng"])
    command.extend(["-vf", "fps=12,format=yuv420p", "-t", str(timeline["duration"]),
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-b:a", "96k", "-movflags", "+faststart", str(output)])
    try:
        subprocess.run(command, cwd=directory, check=True, capture_output=True,
                       text=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        output.unlink(missing_ok=True)
        detail = getattr(error, "stderr", "") or str(error)
        raise RuntimeError(f"FFmpeg preview failed: {detail[-600:]}") from error
    finally:
        for segment in audio_segments:
            segment.unlink(missing_ok=True)
    return output
