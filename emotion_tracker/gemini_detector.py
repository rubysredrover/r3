"""Gemini Vision implementation of EmotionDetector."""

import json
import os
import base64

from google import genai
from google.genai import types

from .detector import EmotionDetector, PersonEmotion, MatchResult


ANALYZE_PROMPT = """You are an emotion recognition system for a home robot that supports people with disabilities including cerebral palsy.

Analyze the primary person (closest/most prominent) in this image. Return ONLY valid JSON:

{
    "person_detected": true/false,
    "description": "Stable physical description for re-identification: hair color/style, approximate age range, glasses, facial hair, build, distinguishing features. Be consistent across sightings.",
    "emotion": "primary emotion",
    "confidence": "high/medium/low",
    "context": "what cues indicate this emotion"
}

IMPORTANT - Emotion detection for people with motor disabilities:
- Distinguish involuntary muscle movements/spasticity from emotional expressions
- Grimacing from motor difficulty is NOT anger or pain unless other cues confirm it
- Look beyond facial muscles: body tension, breathing patterns, eye engagement, vocalization tone
- Fatigue and physical exhaustion present differently than sadness
- Frustration from motor challenges vs general emotional distress
- Comfort signals: relaxed posture, steady eye contact, calm breathing

Valid emotions: happy, sad, angry, surprised, fearful, disgusted, neutral, tired, stressed, excited, confused, content, frustrated, in_pain, uncomfortable, relaxed

If no person visible: {"person_detected": false}"""


MATCH_PROMPT_TEMPLATE = """You are a person re-identification system.

Given a NEW description of a person and a list of KNOWN people, determine if the new person matches any known person.

NEW PERSON: {new_description}

KNOWN PEOPLE:
{known_people}

Return ONLY valid JSON:
{{
    "match_found": true/false,
    "matched_person_id": <id or null>,
    "confidence": "high/medium/low",
    "reasoning": "brief explanation"
}}

Match on stable physical features (hair, build, glasses, age range). Ignore transient features like expression or clothing. Only return match_found=true if reasonably confident."""


class GeminiDetector(EmotionDetector):
    """Cloud-based emotion detection via Gemini Vision API."""

    def __init__(self, api_key=None, model="gemini-2.0-flash"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY required — set env var or pass api_key")
        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def analyze_frame(self, frame_base64: str) -> PersonEmotion:
        response = self.client.models.generate_content(
            model=self.model,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_text(ANALYZE_PROMPT),
                        types.Part.from_bytes(
                            data=base64.b64decode(frame_base64),
                            mime_type="image/jpeg",
                        ),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)

        if not data.get("person_detected"):
            return PersonEmotion(person_detected=False)

        return PersonEmotion(
            person_detected=True,
            description=data.get("description", ""),
            emotion=data.get("emotion", "unknown"),
            confidence=data.get("confidence", "low"),
            context=data.get("context", ""),
        )

    def match_person(self, new_description: str, known_people: list[dict]) -> MatchResult:
        if not known_people:
            return MatchResult(match_found=False)

        known_str = "\n".join(
            f"  ID {p['id']}: {p['name']} — {p['description']}"
            for p in known_people
        )
        prompt = MATCH_PROMPT_TEMPLATE.format(
            new_description=new_description,
            known_people=known_str,
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        data = json.loads(response.text)

        return MatchResult(
            match_found=data.get("match_found", False),
            matched_person_id=data.get("matched_person_id"),
            confidence=data.get("confidence", "low"),
            reasoning=data.get("reasoning", ""),
        )
