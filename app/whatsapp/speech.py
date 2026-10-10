"""Speech helpers: Groq Whisper transcription and Edge TTS converted to OGG/Opus."""
import asyncio
import logging
import tempfile
from pathlib import Path

import edge_tts
import httpx

from app.config import Settings

logger = logging.getLogger(__name__)
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MAX_TRANSCRIPT_CHARS = 2000


class SpeechError(RuntimeError):
    """Raised when speech input/output cannot be processed safely."""


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    content_type: str | None,
    settings: Settings,
) -> str:
    """Transcribe a WhatsApp audio file using the configured Groq Whisper model."""
    if not settings.groq_api_key:
        raise SpeechError("GROQ_API_KEY is not configured")
    if not audio_bytes:
        raise SpeechError("The received audio file was empty")
    if len(audio_bytes) > settings.max_audio_bytes:
        raise SpeechError("The received audio file exceeds the configured size limit")

    mime = (content_type or "audio/ogg").split(";", maxsplit=1)[0].strip()
    headers = {"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"}
    files = {"file": (filename, audio_bytes, mime or "audio/ogg")}
    data = {"model": settings.speech_to_text_model, "response_format": "json"}

    try:
        async with httpx.AsyncClient(timeout=settings.speech_timeout_seconds) as http:
            response = await http.post(
                GROQ_TRANSCRIPTION_URL,
                headers=headers,
                files=files,
                data=data,
            )
            response.raise_for_status()
            transcript = str(response.json().get("text", "")).strip()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Groq transcription API error: status=%s body=%s",
            exc.response.status_code,
            exc.response.text[:300],
        )
        raise SpeechError("Speech transcription failed") from exc
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning(
            "Speech transcription failed: type=%s detail=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        raise SpeechError("Speech transcription failed") from exc

    if not transcript:
        raise SpeechError("No speech could be detected")
    return transcript[:MAX_TRANSCRIPT_CHARS]


async def synthesize_speech(text: str, settings: Settings) -> bytes:
    """Generate speech via Edge TTS and convert it to WhatsApp-compatible OGG/Opus."""
    cleaned_text = text.strip()[:MAX_TRANSCRIPT_CHARS]
    if not cleaned_text:
        raise SpeechError("Cannot synthesize empty text")

    try:
        with tempfile.TemporaryDirectory(prefix="whatsapp-tts-") as temp_dir:
            mp3_path = Path(temp_dir) / "reply.mp3"
            ogg_path = Path(temp_dir) / "reply.ogg"

            communicator = edge_tts.Communicate(
                cleaned_text,
                voice=settings.tts_voice,
                rate=settings.tts_rate,
            )
            await communicator.save(str(mp3_path))

            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(mp3_path),
                "-vn",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-ac",
                "1",
                str(ogg_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise SpeechError("Audio conversion timed out") from exc

            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace")[:300]
                logger.warning("ffmpeg audio conversion failed: %s", detail)
                raise SpeechError("Audio conversion failed; check that FFmpeg is installed")

            audio_bytes = ogg_path.read_bytes()
            if not audio_bytes or len(audio_bytes) > settings.max_audio_bytes:
                raise SpeechError("Generated audio is empty or too large")
            return audio_bytes
    except SpeechError:
        raise
    except Exception as exc:
        logger.warning("speech synthesis failed type=%s", type(exc).__name__)
        raise SpeechError("Speech synthesis failed") from exc
