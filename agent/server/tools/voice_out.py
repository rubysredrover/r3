"""ElevenLabs TTS tool for MARS voice output."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"


def _mock_reason(missing: str) -> None:
    msg = f"[mock] reason: missing {missing}"
    print(msg, file=sys.stderr)
    logger.warning(msg)


def _speak_sync(text: str, voice_id: str) -> bytes:
    from elevenlabs.client import ElevenLabs  # type: ignore

    client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
    stream = client.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=DEFAULT_MODEL_ID,
    )

    if isinstance(stream, (bytes, bytearray)):
        return bytes(stream)

    chunks: list[bytes] = []
    for chunk in stream:
        if chunk:
            chunks.append(chunk if isinstance(chunk, bytes) else bytes(chunk))
    return b"".join(chunks)


async def speak(text: str, voice_id: Optional[str] = None) -> bytes:
    """Synthesize ``text`` to MP3 bytes via ElevenLabs."""
    if not ELEVENLABS_API_KEY:
        _mock_reason("ELEVENLABS_API_KEY")
        print(f"[mock] would speak: {text}", file=sys.stderr)
        return b""

    voice = voice_id or DEFAULT_VOICE_ID

    try:
        return await asyncio.to_thread(_speak_sync, text, voice)
    except Exception as exc:
        logger.exception("speak failed, falling back to mock: %s", exc)
        _mock_reason("ElevenLabs call failed")
        print(f"[mock] would speak: {text}", file=sys.stderr)
        return b""
