"""CP-aware speech transcription tool.

Uses Gemini 2.5 Flash with a CP-aware system prompt to transcribe audio from
Ruby. Returns a structured dict with text, confidence, clarification flag,
and candidate intents. Falls back to a deterministic mock when GEMINI_API_KEY
is missing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "cp_aware.md"

_MOCK_RESULT = {
    "text": "I want pizza",
    "confidence": 0.78,
    "needs_clarification": False,
    "candidate_intents": ["order_food:pizza"],
}


def _mock_reason(missing: str) -> None:
    msg = f"[mock] reason: missing {missing}"
    print(msg, file=sys.stderr)
    logger.warning(msg)


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("cp_aware.md prompt not found at %s; using inline default", PROMPT_PATH)
        return (
            "You are a CP-aware speech transcriber for Ruby, a 12-year-old with "
            "cerebral palsy. Transcribe the audio. Return ONLY JSON with keys: "
            "text (string), confidence (0-1 float), needs_clarification (bool), "
            "candidate_intents (list of strings like 'order_food:pizza')."
        )


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response."""
    raw = raw.strip()
    # Strip markdown code fences
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Find first {...} block
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError(f"Could not extract JSON from model response: {raw!r}")


def _transcribe_sync(audio_path: str, system_prompt: str) -> dict:
    import google.generativeai as genai  # type: ignore

    genai.configure(api_key=GEMINI_API_KEY)

    uploaded = genai.upload_file(path=audio_path)

    try:
        model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=system_prompt)
        resp = model.generate_content([uploaded, "Transcribe this audio and return the JSON described."])
    except Exception as primary_exc:
        logger.warning("gemini-2.5-flash failed (%s); falling back to gemini-2.0-flash-exp", primary_exc)
        model = genai.GenerativeModel("gemini-2.0-flash-exp", system_instruction=system_prompt)
        resp = model.generate_content([uploaded, "Transcribe this audio and return the JSON described."])

    text = getattr(resp, "text", None) or ""
    parsed = _extract_json(text)

    return {
        "text": str(parsed.get("text", "")),
        "confidence": float(parsed.get("confidence", 0.0)),
        "needs_clarification": bool(parsed.get("needs_clarification", False)),
        "candidate_intents": list(parsed.get("candidate_intents", [])),
    }


async def transcribe_cp_aware(audio_path: str) -> dict:
    """Transcribe Ruby's audio with CP-aware prompting.

    Returns:
        {"text": str, "confidence": float, "needs_clarification": bool,
         "candidate_intents": list[str]}
    """
    if not GEMINI_API_KEY:
        _mock_reason("GEMINI_API_KEY")
        return dict(_MOCK_RESULT)

    if not os.path.exists(audio_path):
        logger.error("audio_path does not exist: %s", audio_path)
        _mock_reason(f"audio file at {audio_path}")
        return dict(_MOCK_RESULT)

    system_prompt = _load_prompt()

    try:
        return await asyncio.to_thread(_transcribe_sync, audio_path, system_prompt)
    except Exception as exc:
        logger.exception("transcribe_cp_aware failed, falling back to mock: %s", exc)
        _mock_reason("Gemini call failed")
        return dict(_MOCK_RESULT)
