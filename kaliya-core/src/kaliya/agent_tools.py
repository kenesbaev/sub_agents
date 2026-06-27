from __future__ import annotations

import asyncio
import base64
import csv
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from kaliya.link_reader import extract_urls, fetch_link_summaries, format_link_context
from kaliya.text_safety import redact_sensitive_text

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 32 * 1024 * 1024
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav"}
VIDEO_SUFFIXES = {".avi", ".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".webm", ".mkv"}
CSV_SUFFIXES = {".csv", ".tsv"}
VIDEO_HOST_RE = re.compile(
    r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com|instagram\.com|instagr\.am)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UploadedAttachment:
    name: str
    content_type: str
    size: int
    path: Path


@dataclass(frozen=True)
class TurnContext:
    message: str
    context_blocks: list[str] = field(default_factory=list)
    image_paths: list[Path] = field(default_factory=list)
    attachments: list[UploadedAttachment] = field(default_factory=list)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None

    @property
    def tool_context(self) -> str:
        blocks = [block for block in self.context_blocks if block.strip()]
        if not blocks:
            return ""
        return "\n\n".join(blocks)

    def cleanup(self) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()


def build_turn_context(
    *,
    message: str,
    raw_attachments: list[dict[str, Any]],
    upload_parts: list[dict[str, Any]],
    data_dir: Path,
) -> TurnContext:
    temp_dir = tempfile.TemporaryDirectory(prefix="n1n-turn-")
    temp_path = Path(temp_dir.name)
    attachments = save_attachments(
        raw_attachments=raw_attachments,
        upload_parts=upload_parts,
        target_dir=temp_path,
    )
    context_blocks: list[str] = []
    image_paths: list[Path] = []

    link_context = build_link_context(message)
    if link_context:
        context_blocks.append("Link context:\n" + link_context)

    for url in extract_urls(message):
        if is_supported_video_link(url):
            context_blocks.append(video_link_context(url, data_dir=data_dir))

    for attachment in attachments:
        if is_image_attachment(attachment):
            image_paths.append(attachment.path)
            context_blocks.append(
                f"Attachment image: {attachment.name} ({attachment.content_type}, {attachment.size} bytes)"
            )
        elif is_csv_attachment(attachment):
            saved_path = persist_dataset_file(attachment, data_dir=data_dir)
            context_blocks.append(
                "CSV context:\n"
                + summarize_csv(attachment.path, attachment.name)
                + f"\nSaved dataset: {saved_path}"
            )
        elif is_video_attachment(attachment) or is_audio_attachment(attachment):
            context_blocks.append(media_file_context(attachment))
        else:
            context_blocks.append(
                f"Attachment: {attachment.name} ({attachment.content_type or 'unknown'}, {attachment.size} bytes). "
                "No specialized parser is available for this file type."
            )

    return TurnContext(
        message=message,
        context_blocks=context_blocks,
        image_paths=image_paths,
        attachments=attachments,
        temp_dir=temp_dir,
    )


def save_attachments(
    *,
    raw_attachments: list[dict[str, Any]],
    upload_parts: list[dict[str, Any]],
    target_dir: Path,
) -> list[UploadedAttachment]:
    target_dir.mkdir(parents=True, exist_ok=True)
    result: list[UploadedAttachment] = []
    total = 0

    for item in raw_attachments:
        name = safe_filename(str(item.get("name") or "attachment"))
        content_type = str(item.get("type") or guess_type(name))
        encoded = str(item.get("dataBase64") or "")
        data = base64.b64decode(encoded, validate=True)
        total += len(data)
        validate_attachment_size(len(data), total)
        path = unique_path(target_dir / name)
        path.write_bytes(data)
        result.append(UploadedAttachment(name=name, content_type=content_type, size=len(data), path=path))

    for item in upload_parts:
        name = safe_filename(str(item.get("name") or "attachment"))
        content_type = str(item.get("content_type") or guess_type(name))
        data = bytes(item.get("data") or b"")
        total += len(data)
        validate_attachment_size(len(data), total)
        path = unique_path(target_dir / name)
        path.write_bytes(data)
        result.append(UploadedAttachment(name=name, content_type=content_type, size=len(data), path=path))

    return result


def validate_attachment_size(size: int, total: int) -> None:
    if size > MAX_ATTACHMENT_BYTES:
        raise ValueError("Файл слишком большой для анализа.")
    if total > MAX_TOTAL_ATTACHMENT_BYTES:
        raise ValueError("Суммарный размер вложений слишком большой.")


def build_link_context(message: str) -> str:
    urls = [url for url in extract_urls(message) if not is_supported_video_link(url)]
    if not urls or os.environ.get("KALIYA_LINK_FETCH_ENABLED", "true").lower() in {"0", "false", "no"}:
        return ""
    try:
        summaries = asyncio.run(
            fetch_link_summaries(
                urls,
                timeout_seconds=int(os.environ.get("KALIYA_LINK_FETCH_TIMEOUT_SECONDS", "10")),
                max_bytes=int(os.environ.get("KALIYA_LINK_FETCH_MAX_BYTES", str(512 * 1024))),
                limit=int(os.environ.get("KALIYA_LINK_FETCH_LIMIT", "3")),
            )
        )
    except Exception as exc:
        return f"Link fetch unavailable: {redact_sensitive_text(str(exc))}"
    return redact_sensitive_text(format_link_context(summaries))


def is_supported_video_link(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return bool(host and VIDEO_HOST_RE.search(host))


def video_link_context(url: str, *, data_dir: Path) -> str:
    if os.environ.get("KALIYA_VIDEO_LINK_DOWNLOAD_ENABLED", "true").lower() in {"0", "false", "no"}:
        return f"Video URL: {url}\nVideo download disabled."
    if not shutil.which("yt-dlp"):
        return f"Video URL: {url}\nVideo analysis unavailable: yt-dlp is not installed."
    target_dir = data_dir / "media" / "links"
    target_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(target_dir / "%(extractor)s_%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--no-playlist",
        "--max-filesize",
        os.environ.get("KALIYA_VIDEO_LINK_MAX_BYTES", str(100 * 1024 * 1024)),
        "--socket-timeout",
        "20",
        "-o",
        output_template,
        "--print",
        "after_move:filepath",
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("KALIYA_VIDEO_LINK_TIMEOUT_SECONDS", "120")),
            check=False,
        )
    except Exception as exc:
        return f"Video URL: {url}\nVideo download failed: {redact_sensitive_text(str(exc))}"
    if completed.returncode != 0:
        detail = redact_sensitive_text((completed.stderr or completed.stdout or "yt-dlp failed").strip())
        return f"Video URL: {url}\nVideo download failed: {detail[-500:]}"
    for line in reversed(completed.stdout.splitlines()):
        path = Path(line.strip())
        if path.exists():
            return media_file_context(
                UploadedAttachment(path.name, guess_type(path.name), path.stat().st_size, path),
                source_url=url,
            )
    return f"Video URL: {url}\nyt-dlp finished but no downloaded file was found."


def media_file_context(attachment: UploadedAttachment, *, source_url: str = "") -> str:
    path = attachment.path
    lines = [
        f"Media: {attachment.name}",
        f"Type: {attachment.content_type or guess_type(attachment.name)}",
    ]
    if source_url:
        lines.append(f"Source URL: {source_url}")

    if is_audio_attachment(attachment) or is_video_attachment(attachment):
        transcript = transcribe_media(path)
        if transcript:
            lines.append("Transcript:\n" + transcript)
        else:
            lines.append("Transcript unavailable: faster-whisper is not installed or no speech was detected.")

    if is_video_attachment(attachment):
        frame_context = sample_video_frames(path)
        if frame_context:
            lines.append(frame_context)
    return "\n".join(lines)


def transcribe_media(path: Path) -> str:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return ""
    if not shutil.which("ffmpeg"):
        return ""
    audio_path = path.with_suffix(".wav")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        return ""
    model_name = os.environ.get("KALIYA_WHISPER_MODEL", "base")
    device = os.environ.get("KALIYA_WHISPER_DEVICE", "cpu")
    compute_type = os.environ.get("KALIYA_WHISPER_COMPUTE_TYPE", "int8")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(str(audio_path), vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip())


def sample_video_frames(path: Path) -> str:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return "Video frame sampling unavailable: ffmpeg/ffprobe is not installed."
    metadata = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    duration = 0.0
    try:
        duration = float(json.loads(metadata.stdout or "{}").get("format", {}).get("duration") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        duration = 0.0
    if duration <= 0:
        return ""
    interval = float(os.environ.get("KALIYA_VIDEO_FRAME_INTERVAL_SECONDS", "2.0"))
    max_frames = int(os.environ.get("KALIYA_VIDEO_MAX_FRAMES", "8"))
    timestamps = [round(index * interval, 2) for index in range(max(1, min(max_frames, int(duration // interval) + 1)))]
    frame_dir = path.parent / f"{path.stem}_frames"
    frame_dir.mkdir(exist_ok=True)
    ocr_lines: list[str] = []
    for index, timestamp in enumerate(timestamps):
        frame = frame_dir / f"frame_{index:03d}.jpg"
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{timestamp:.2f}", "-i", str(path), "-frames:v", "1", str(frame)],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0 and shutil.which("tesseract"):
            ocr = subprocess.run(
                ["tesseract", str(frame), "stdout", "-l", os.environ.get("KALIYA_VIDEO_OCR_LANGS", "rus+eng")],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            text = " ".join((ocr.stdout or "").split())
            if text:
                ocr_lines.append(f"{timestamp:.1f}s {frame.name}: {redact_sensitive_text(text)}")
    summary = f"Sampled video frames: {len(timestamps)}"
    if ocr_lines:
        summary += "\nOCR text:\n" + "\n".join(ocr_lines[:20])
    elif not shutil.which("tesseract"):
        summary += "\nOCR unavailable: tesseract is not installed."
    return summary


def summarize_csv(path: Path, filename: str) -> str:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows: list[list[str]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file, delimiter=delimiter)
            for index, row in enumerate(reader):
                rows.append([redact_sensitive_text(cell) for cell in row])
                if index >= 10:
                    break
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1", newline="") as file:
            reader = csv.reader(file, delimiter=delimiter)
            for index, row in enumerate(reader):
                rows.append([redact_sensitive_text(cell) for cell in row])
                if index >= 10:
                    break
    if not rows:
        return f"{filename}: CSV file is empty."
    header = rows[0]
    data_rows = rows[1:]
    lines = [
        f"File: {filename}",
        f"Columns ({len(header)}): {', '.join(header[:30])}",
        f"Preview rows: {len(data_rows)} shown",
    ]
    for row in data_rows[:8]:
        values = [f"{header[i] if i < len(header) else f'col_{i+1}'}={row[i]}" for i in range(min(len(row), 12))]
        lines.append("- " + "; ".join(values))
    return "\n".join(lines)


def persist_dataset_file(attachment: UploadedAttachment, *, data_dir: Path) -> Path:
    dataset_dir = data_dir / "tables" / "local"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(dataset_dir / safe_filename(attachment.name))
    target.write_bytes(attachment.path.read_bytes())
    return target


def is_image_attachment(attachment: UploadedAttachment) -> bool:
    return attachment.path.suffix.lower() in IMAGE_SUFFIXES or attachment.content_type.startswith("image/")


def is_audio_attachment(attachment: UploadedAttachment) -> bool:
    return attachment.path.suffix.lower() in AUDIO_SUFFIXES or attachment.content_type.startswith("audio/")


def is_video_attachment(attachment: UploadedAttachment) -> bool:
    return attachment.path.suffix.lower() in VIDEO_SUFFIXES or attachment.content_type.startswith("video/")


def is_csv_attachment(attachment: UploadedAttachment) -> bool:
    return attachment.path.suffix.lower() in CSV_SUFFIXES or attachment.content_type in {"text/csv", "text/tab-separated-values"}


def safe_filename(name: str) -> str:
    base = Path(name).name.strip() or "attachment"
    clean = re.sub(r"[^A-Za-z0-9А-Яа-яЁё._-]+", "_", base)[:160].strip("._")
    return clean or "attachment"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError("Could not create a unique upload path.")


def guess_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
