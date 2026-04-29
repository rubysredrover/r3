"""ElevenLabs voice cloning for Ruby.

``setup_ruby_clone`` clones Ruby's voice (Instant Voice Cloning) so MARS can
speak phone calls in her voice. ``synthesize_as_ruby`` produces TTS audio in
that cloned voice.
"""
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
RUBY_VOICE_ID = os.environ.get("RUBY_VOICE_ID")
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"


def _mock_reason(missing: str) -> None:
    msg = f"[mock] reason: missing {missing}"
    print(msg, file=sys.stderr)
    logger.warning(msg)


def setup_ruby_clone(training_audio_paths: list[str]) -> str:
    """Create (or reuse) a cloned ElevenLabs voice for Ruby. Returns voice_id."""
    existing = os.environ.get("RUBY_VOICE_ID")
    if existing:
        logger.info("Reusing existing RUBY_VOICE_ID=%s", existing)
        return existing

    if not ELEVENLABS_API_KEY:
        _mock_reason("ELEVENLABS_API_KEY")
        return "mock-ruby-voice-id"

    valid_paths = [p for p in training_audio_paths if os.path.exists(p)]
    if not valid_paths:
        _mock_reason("training audio files")
        return "mock-ruby-voice-id"

    try:
        from elevenlabs.client import ElevenLabs  # type: ignore

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        files = [open(p, "rb") for p in valid_paths]
        try:
            voice = client.voices.ivc.create(
                name="Ruby",
                description="Ruby's cloned voice for MARS phone calls.",
                files=files,
            )
        finally:
            for f in files:
                try:
                    f.close()
                except Exception:
                    pass

        voice_id = getattr(voice, "voice_id", None) or getattr(voice, "id", None)
        if not voice_id:
            raise RuntimeError(f"ElevenLabs IVC returned no voice_id: {voice!r}")

        # Cache in-process so subsequent calls reuse it.
        os.environ["RUBY_VOICE_ID"] = voice_id
        logger.info("Cloned Ruby's voice: %s", voice_id)
        return voice_id
    except Exception as exc:
        logger.exception("setup_ruby_clone failed, falling back to mock: %s", exc)
        _mock_reason("ElevenLabs IVC call failed")
        return "mock-ruby-voice-id"


def _synth_sync(text: str, voice_id: str) -> bytes:
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


async def _resolve_ruby_voice_id() -> Optional[str]:
    """Pull Ruby's voice ID from her self-grant to MARS in Bolo.

    The voice ID lives in the grant payload, not in env config — so revoking
    the grant is the canonical way to revoke Ruby's voice from the agent.
    Falls back to env if Bolo is unreachable.
    """
    try:
        from server.tools import bolo
        grant = await bolo.get_grants(grantor="@ruby", grantee="@mars", widget="voice")
        scopes = grant.get("scopes", {}) if isinstance(grant, dict) else {}
        if scopes.get("demo_input") and scopes.get("elevenlabs_voice_id"):
            return scopes["elevenlabs_voice_id"]
    except Exception as exc:
        logger.warning("Ruby voice grant lookup failed (using env fallback): %s", exc)
    return os.environ.get("RUBY_VOICE_ID") or RUBY_VOICE_ID


async def synthesize_as_ruby(text: str) -> bytes:
    """TTS via ElevenLabs in Ruby's cloned voice (gated by her Bolo self-grant)."""
    voice_id: Optional[str] = await _resolve_ruby_voice_id()

    if not ELEVENLABS_API_KEY:
        _mock_reason("ELEVENLABS_API_KEY")
        print(f"[mock] would synthesize as Ruby: {text}", file=sys.stderr)
        return b""

    if not voice_id:
        _mock_reason("RUBY_VOICE_ID")
        print(f"[mock] would synthesize as Ruby: {text}", file=sys.stderr)
        return b""

    try:
        return await asyncio.to_thread(_synth_sync, text, voice_id)
    except Exception as exc:
        logger.exception("synthesize_as_ruby failed, falling back to mock: %s", exc)
        _mock_reason("ElevenLabs call failed")
        print(f"[mock] would synthesize as Ruby: {text}", file=sys.stderr)
        return b""
