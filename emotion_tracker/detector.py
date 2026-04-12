"""Abstract interface for emotion detection backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PersonEmotion:
    """Result from analyzing a single person in a frame."""
    person_detected: bool = False
    description: str = ""
    emotion: str = ""
    confidence: str = ""
    context: str = ""


@dataclass
class MatchResult:
    """Result from matching a person against the registry."""
    match_found: bool = False
    matched_person_id: Optional[int] = None
    confidence: str = ""
    reasoning: str = ""


class EmotionDetector(ABC):
    """Abstract base class for emotion detection.

    Today: GeminiDetector (cloud API)
    Future: LocalDetector (on-device inference on Jetson GPU)
    """

    @abstractmethod
    def analyze_frame(self, frame_base64: str) -> PersonEmotion:
        """Analyze a frame and return emotion data for the primary person."""
        ...

    @abstractmethod
    def match_person(self, new_description: str, known_people: list[dict]) -> MatchResult:
        """Check if a detected person matches any known person."""
        ...
