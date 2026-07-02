"""
Whisper API transcription service.

Returns full_text (plain string) and segments (list of timed chunks).
Segments format: [{"start": 0.0, "end": 2.5, "text": "Здравствуйте"}, ...]

Retry logic: up to MAX_RETRY_ATTEMPTS with exponential backoff.
After all retries fail, raises TranscriptionError.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from config import settings

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


class TranscriptionError(Exception):
    """Raised when transcription fails after all retries."""


@dataclass
class TranscriptionResult:
    full_text: str
    language: str
    segments: list[dict] = field(default_factory=list)


async def transcribe(audio_path: str) -> TranscriptionResult:
    """
    Transcribe an audio file using OpenAI Whisper.
    audio_path must be a local path to a WAV/MP3/etc. file.
    Raises TranscriptionError after MAX_RETRY_ATTEMPTS failures.
    """
    last_exc: Exception | None = None

    for attempt in range(1, settings.MAX_RETRY_ATTEMPTS + 1):
        try:
            with open(audio_path, "rb") as f:
                response = await _client.audio.transcriptions.create(
                    model=settings.WHISPER_MODEL,
                    file=f,
                    response_format="verbose_json",  # returns segments with timestamps
                    timestamp_granularities=["segment"],
                )

            full_text: str = response.text or ""
            language: str = getattr(response, "language", "unknown") or "unknown"
            raw_segments = getattr(response, "segments", None) or []

            segments = [
                {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": (seg.text or "").strip(),
                }
                for seg in raw_segments
            ]

            logger.info(
                "Transcribed %s: %d chars, %d segments, lang=%s",
                audio_path, len(full_text), len(segments), language,
            )
            return TranscriptionResult(
                full_text=full_text,
                language=language,
                segments=segments,
            )

        except (APITimeoutError, APIError) as exc:
            last_exc = exc
            if attempt < settings.MAX_RETRY_ATTEMPTS:
                delay = settings.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Whisper API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt, settings.MAX_RETRY_ATTEMPTS, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Whisper API failed after %d attempts: %s",
                    settings.MAX_RETRY_ATTEMPTS, exc,
                )

        except RateLimitError as exc:
            last_exc = exc
            if attempt < settings.MAX_RETRY_ATTEMPTS:
                delay = settings.RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning("Whisper rate limit hit (attempt %d/%d), waiting %.1fs: %s",
                               attempt, settings.MAX_RETRY_ATTEMPTS, delay, exc)
                await asyncio.sleep(delay)

    raise TranscriptionError(
        f"Transcription failed after {settings.MAX_RETRY_ATTEMPTS} attempts: {last_exc}"
    )
