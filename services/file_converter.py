"""
FFmpeg-based audio/video conversion.

Responsibilities:
- Convert any audio/video format to mono WAV 16kHz (optimal for Whisper)
- Extract duration in seconds
- Validate that the input file is a valid media file

All operations are async (subprocess does not block the event loop).
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

_FFMPEG = settings.FFMPEG_PATH or "ffmpeg"
_FFPROBE = (
    str(Path(settings.FFMPEG_PATH).parent / "ffprobe")
    if settings.FFMPEG_PATH
    else "ffprobe"
)


class ConversionError(Exception):
    """Raised when FFmpeg fails to process the file."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: str
    duration_seconds: int  # rounded up


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def get_duration(input_path: str) -> float:
    """
    Return media duration in seconds using ffprobe.
    Raises ConversionError if the file is not valid media.
    """
    cmd = [
        _FFPROBE,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        input_path,
    ]
    code, stdout, stderr = await _run(cmd)
    if code != 0:
        raise ConversionError(
            f"ffprobe failed (exit {code}): {stderr.strip()[:300]}"
        )
    try:
        info = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ConversionError(f"Could not parse ffprobe output: {exc}") from exc

    # Prefer container-level duration; fall back to the longest stream duration.
    # Some Telegram voice formats (ogg/opus, webm) omit format.duration but carry
    # it on the audio stream.
    duration_str = info.get("format", {}).get("duration")
    if duration_str is None:
        stream_durations = [
            float(s["duration"])
            for s in info.get("streams", [])
            if s.get("duration") not in (None, "N/A")
        ]
        if not stream_durations:
            raise ConversionError("ffprobe returned no duration in format or streams")
        return max(stream_durations)
    try:
        return float(duration_str)
    except ValueError as exc:
        raise ConversionError(f"Invalid duration value: {duration_str!r}") from exc


async def convert_to_wav(input_path: str, output_path: str) -> ConversionResult:
    """
    Convert input_path to 16kHz mono WAV at output_path.
    Returns ConversionResult with output path and duration.
    Raises ConversionError on failure.
    """
    # Validate first so we get a clean error before spending time converting
    duration_f = await get_duration(input_path)

    cmd = [
        _FFMPEG,
        "-y",                    # overwrite output without asking
        "-i", input_path,
        "-ar", "16000",          # 16kHz sample rate — optimal for Whisper
        "-ac", "1",              # mono
        "-c:a", "pcm_s16le",     # 16-bit PCM WAV
        "-vn",                   # strip video stream if present
        output_path,
    ]
    code, _, stderr = await _run(cmd)
    if code != 0:
        raise ConversionError(
            f"ffmpeg conversion failed (exit {code}): {stderr.strip()[:300]}"
        )

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise ConversionError("ffmpeg produced an empty output file")

    return ConversionResult(
        output_path=output_path,
        duration_seconds=max(1, round(duration_f)),
    )
