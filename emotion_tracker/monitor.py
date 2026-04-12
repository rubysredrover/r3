"""Always-on emotion monitor with adaptive scan timing.

Two-tier emotion detection:
  - FAST (on-device): inspireface detects face + basic emotion — no API call
  - DEEP (Gemini): CP-aware nuanced analysis — only when mood changes or distress detected
"""

import time
import subprocess

from .camera import MARSCamera
from .detector import EmotionDetector, PersonEmotion
from .face_encoder import FaceEncoder, INSPIREFACE_AVAILABLE
from .mood_ring import MoodRing
from .person_registry import PersonRegistry


# Adaptive timing intervals (seconds)
INTERVAL_NO_PERSON = 10      # nobody in frame
INTERVAL_STABLE = 30         # same mood 3+ readings in a row
INTERVAL_CHANGED = 10        # mood just shifted
INTERVAL_DISTRESS = 5        # pain, frustration, distress detected

DISTRESS_EMOTIONS = {"in_pain", "frustrated", "stressed", "angry", "fearful", "uncomfortable"}

# Emotions that warrant a deeper Gemini analysis (CP-aware)
NEEDS_DEEP_ANALYSIS = {"angry", "in_pain", "frustrated", "fearful", "sad", "disgusted"}


class EmotionMonitor:
    """Always-on loop: detect person, identify, read emotion, log, adapt timing.

    Uses inspireface on-device for fast face ID + basic emotion.
    Escalates to Gemini only when:
      - Mood changes (need CP-aware context)
      - Distress emotions detected (is it real distress or motor artifact?)
      - First time seeing someone (need physical description)
    """

    def __init__(self, detector: EmotionDetector, camera: MARSCamera,
                 registry: PersonRegistry, mood_ring: MoodRing = None):
        self.detector = detector  # Gemini (deep analysis)
        self.camera = camera
        self.registry = registry
        self.face_encoder = FaceEncoder() if INSPIREFACE_AVAILABLE else None
        self.mood_ring = mood_ring or MoodRing()

        # adaptive state
        self.last_emotion = None
        self.stable_count = 0
        self.current_interval = INTERVAL_NO_PERSON
        self.scan_count = 0
        self.verbose_scans = 3  # full detail for first N scans

    def _identify_and_read(self, frame):
        """Fast path: use inspireface for identity + basic emotion (on-device).

        Returns (person_id, embedding, local_emotion) or (None, embedding, local_emotion).
        """
        if self.face_encoder is None:
            return None, None, None

        face_data = self.face_encoder.detect_and_analyze(frame)
        if face_data is None:
            return None, None, None

        embedding = face_data.get("embedding")
        local_emotion = face_data.get("emotion")

        # match against known faces
        if embedding is not None:
            known = self.registry.get_all_face_embeddings()
            match = self.face_encoder.match(embedding, known)
            if match:
                return match["person_id"], embedding, local_emotion

        return None, embedding, local_emotion

    def _needs_gemini(self, local_emotion, person_id):
        """Decide if we should call Gemini for deeper CP-aware analysis."""
        # always call Gemini for new people (need physical description)
        if person_id is None:
            return True

        # call Gemini when mood changes
        if local_emotion != self.last_emotion:
            return True

        # call Gemini for emotions that could be motor artifacts
        if local_emotion in NEEDS_DEEP_ANALYSIS:
            return True

        return False

    def _register_new_person(self, description, embedding, emotion, confidence, context):
        """Register someone MARS hasn't seen before."""
        speak("Hi there! I don't think we've met. What's your name?")
        try:
            name = input("Enter name for new person: ").strip()
        except (EOFError, KeyboardInterrupt):
            name = "Unknown"
        if not name:
            name = "Unknown"

        person_id = self.registry.register_person(name, description, face_embedding=embedding)
        self.registry.log_mood(person_id, emotion, confidence, context)
        speak(f"Nice to meet you, {name}! I'll remember you.")
        return person_id

    def _adapt_interval(self, emotion):
        """Adjust scan frequency based on emotional state."""
        if emotion in DISTRESS_EMOTIONS:
            self.stable_count = 0
            self.last_emotion = emotion
            self.current_interval = INTERVAL_DISTRESS
            return

        if emotion == self.last_emotion:
            self.stable_count += 1
        else:
            self.stable_count = 0
            self.current_interval = INTERVAL_CHANGED

        self.last_emotion = emotion

        if self.stable_count >= 3:
            self.current_interval = INTERVAL_STABLE

    def _on_mood_change(self, person, old_mood, new_emotion):
        """Called when a tracked person's mood changes."""
        name = person["name"]
        if old_mood:
            old = old_mood["emotion"]
            if new_emotion in DISTRESS_EMOTIONS:
                speak(f"{name}, I notice you seem {new_emotion}. Is everything okay?")
            else:
                print(f"[Mood shift] {name}: {old} → {new_emotion}")
        else:
            print(f"[First reading] {name}: {new_emotion}")

    def scan_once(self):
        """Run a single scan cycle. Returns the interval to wait before next scan.

        Flow:
        1. Capture frame
        2. inspireface: detect face, get identity + basic emotion (FREE, on-device)
        3. If mood changed or distress → call Gemini for CP-aware analysis
        4. Log mood, update mood ring, adapt scan timing
        """
        self.scan_count += 1
        verbose = self.scan_count <= self.verbose_scans

        if verbose:
            print(f"\n{'='*50}")
            print(f"[Scan #{self.scan_count}] Analyzing...")
            print(f"{'='*50}")

        frame = self.camera.capture_frame()

        # FAST PATH: on-device face ID + basic emotion
        person_id, embedding, local_emotion = self._identify_and_read(frame)

        if verbose and self.face_encoder:
            if embedding is not None:
                print(f"  Face detected: yes (embedding captured)")
                print(f"  On-device emotion: {local_emotion or 'unknown'}")
                print(f"  Known person: {'yes (ID: ' + str(person_id) + ')' if person_id else 'no (new face)'}")
            else:
                print(f"  Face detected: no")

        if embedding is None and local_emotion is None:
            # no face detected at all
            if verbose:
                print(f"  No face in frame. Waiting {INTERVAL_NO_PERSON}s...")
            self.current_interval = INTERVAL_NO_PERSON
            return self.current_interval

        # decide emotion source
        emotion = local_emotion
        description = ""
        confidence = "medium"
        context = "on-device detection"

        # DEEP PATH: call Gemini when needed for CP-aware nuance
        if self._needs_gemini(local_emotion, person_id):
            if verbose:
                print(f"  Calling Gemini (CP-aware deep analysis)...")
            frame_b64 = self.camera.frame_to_base64(frame)
            result = self.detector.analyze_frame(frame_b64)
            if result.person_detected:
                emotion = result.emotion
                description = result.description
                confidence = result.confidence
                context = result.context
                if verbose:
                    print(f"  Emotion:     {emotion} ({confidence})")
                    print(f"  Context:     {context}")
                    print(f"  Description: {description}")
                else:
                    print(f"[Gemini] {emotion} ({context})")
            else:
                print("[Gemini] no person detected in deep analysis")
        else:
            if verbose:
                print(f"  Skipping Gemini (mood stable)")
                print(f"  Emotion:     {emotion} (on-device)")
            else:
                print(f"[On-device] {emotion} (stable, skipping Gemini)")

        # handle person identity
        if person_id is None:
            person_id = self._register_new_person(
                description, embedding, emotion, confidence, context
            )
            if verbose:
                print(f"  Registered new person (ID: {person_id})")
        else:
            person = self.registry.get_person(person_id)
            last_mood = self.registry.get_last_mood(person_id)
            self.registry.log_mood(person_id, emotion, confidence, context)

            if verbose:
                print(f"  Logged mood for {person['name']} (ID: {person_id})")

            # update face embedding if we got a better one
            if embedding is not None and person.get("face_embedding") is None:
                self.registry.update_face_embedding(person_id, embedding)

            if not last_mood or last_mood["emotion"] != emotion:
                self._on_mood_change(person, last_mood, emotion)

        self._adapt_interval(emotion)
        self.mood_ring.set_mood(emotion)

        if verbose:
            print(f"  Mood ring:   {emotion}")
            print(f"  Next scan:   {self.current_interval}s")
            if self.scan_count == self.verbose_scans:
                print(f"\n  (Switching to compact output)")
        else:
            print(f"[{emotion}] next scan in {self.current_interval}s")
        return self.current_interval

    def run(self):
        """Main always-on loop."""
        print("=== MARS Emotion Monitor (always-on) ===")
        if self.face_encoder:
            print("inspireface: ON (face ID + basic emotion on-device)")
        else:
            print("inspireface: OFF (using Gemini for everything)")
        print("Gemini: CP-aware deep analysis (on mood change / distress)")
        print("Press Ctrl+C to stop.\n")

        while True:
            try:
                interval = self.scan_once()
                time.sleep(interval)
            except KeyboardInterrupt:
                self.mood_ring.clear()
                print("\nShutting down.")
                break
            except Exception as e:
                print(f"[Error] {e}")
                time.sleep(INTERVAL_NO_PERSON)


def speak(text):
    """Speak via espeak on the Jetson. Falls back to print."""
    print(f"[MARS]: {text}")
    try:
        subprocess.run(["espeak", "-s", "140", text], timeout=10, capture_output=True)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
