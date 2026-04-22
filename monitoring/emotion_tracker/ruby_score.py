"""Ruby Score: a custom engagement/wellbeing metric trained on Ruby.

Not generic emotion labels — a composite score specific to Ruby, based on:
  1. Eye contact (inspireface gaze/face pose)
  2. Volume (microphone input level)
  3. Speed of response (latency between prompt and reply)

Runs entirely on-device. No cloud. This is the sovereign mode model.

The score is 0-100:
  80-100: Ruby is engaged, responsive, doing great
  60-80:  Ruby is okay, moderate engagement
  40-60:  Ruby is quieter than usual, check in
  20-40:  Ruby seems withdrawn or uncomfortable
  0-20:   Something is wrong, alert Mom

Training approach:
  - Collect labeled data over time (caregiver tags moments as "good day" / "rough day")
  - Simple model: weighted combination → logistic regression → small neural net
  - Runs on Jetson CPU, no GPU needed for inference
  - Retrain weekly as we collect more data
"""

import time
import numpy as np
from dataclasses import dataclass
from pathlib import Path

try:
    import pickle
    MODEL_PATH = Path(__file__).parent.parent / "ruby_score_model.pkl"
except ImportError:
    pass


@dataclass
class RubySignals:
    """Raw signals collected for the Ruby Score."""
    eye_contact_ratio: float    # 0-1, fraction of time with eye contact in window
    volume_level: float         # 0-1, normalized audio level
    response_latency: float     # seconds, time to respond to prompt
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class RubyScoreEngine:
    """Computes the Ruby Score from raw signals.

    Starts with a hand-tuned weighted model.
    Can be replaced with a trained model as data accumulates.
    """

    def __init__(self, model_path=None):
        self.model_path = model_path or MODEL_PATH
        self.model = None
        self.history = []

        # hand-tuned weights (v0 — before we have training data)
        self.weights = {
            "eye_contact": 0.45,   # strongest signal for Ruby
            "volume": 0.25,        # louder = more engaged
            "response_speed": 0.30 # faster response = more engaged
        }

        # Ruby's baseline (calibrated to her normal ranges)
        self.baseline = {
            "eye_contact_typical": 0.4,   # Ruby's typical eye contact ratio
            "volume_typical": 0.35,        # Ruby's typical volume
            "response_typical": 3.0,       # Ruby's typical response time (seconds)
        }

        self._load_model()

    def _load_model(self):
        """Load trained model if it exists."""
        if self.model_path and self.model_path.exists():
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                print("[Ruby Score] Loaded trained model")
            except Exception:
                self.model = None

    def compute(self, signals: RubySignals) -> dict:
        """Compute the Ruby Score from current signals.

        Returns dict with score (0-100), level, and component breakdown.
        """
        if self.model is not None:
            return self._compute_trained(signals)

        return self._compute_weighted(signals)

    def _compute_weighted(self, signals: RubySignals) -> dict:
        """Hand-tuned weighted model (v0)."""
        # normalize each signal relative to Ruby's baseline
        eye_score = min(signals.eye_contact_ratio / max(self.baseline["eye_contact_typical"] * 1.5, 0.01), 1.0)
        volume_score = min(signals.volume_level / max(self.baseline["volume_typical"] * 1.5, 0.01), 1.0)

        # response speed: faster is better, cap at baseline
        if signals.response_latency <= 0:
            speed_score = 0.5  # no response measured
        else:
            speed_score = min(self.baseline["response_typical"] / max(signals.response_latency, 0.1), 1.0)

        # weighted combination
        raw = (
            eye_score * self.weights["eye_contact"] +
            volume_score * self.weights["volume"] +
            speed_score * self.weights["response_speed"]
        )

        score = int(round(raw * 100))
        score = max(0, min(100, score))

        level = self._score_to_level(score)

        result = {
            "score": score,
            "level": level,
            "components": {
                "eye_contact": round(eye_score * 100),
                "volume": round(volume_score * 100),
                "response_speed": round(speed_score * 100),
            },
            "timestamp": signals.timestamp,
        }

        self.history.append(result)
        return result

    def _compute_trained(self, signals: RubySignals) -> dict:
        """Use trained model for prediction."""
        features = np.array([[
            signals.eye_contact_ratio,
            signals.volume_level,
            signals.response_latency,
        ]])
        score = int(round(float(self.model.predict(features)[0])))
        score = max(0, min(100, score))

        return {
            "score": score,
            "level": self._score_to_level(score),
            "components": {
                "eye_contact": round(signals.eye_contact_ratio * 100),
                "volume": round(signals.volume_level * 100),
                "response_speed": round(min(self.baseline["response_typical"] / max(signals.response_latency, 0.1), 1.0) * 100),
            },
            "timestamp": signals.timestamp,
        }

    def _score_to_level(self, score: int) -> str:
        if score >= 80: return "great"
        if score >= 60: return "okay"
        if score >= 40: return "quiet"
        if score >= 20: return "withdrawn"
        return "alert"

    def calibrate(self, eye_contact_typical, volume_typical, response_typical):
        """Calibrate baseline to Ruby's normal ranges."""
        self.baseline["eye_contact_typical"] = eye_contact_typical
        self.baseline["volume_typical"] = volume_typical
        self.baseline["response_typical"] = response_typical
        print(f"[Ruby Score] Calibrated: eye={eye_contact_typical}, vol={volume_typical}, resp={response_typical}s")

    def save_training_sample(self, signals: RubySignals, label: int, path=None):
        """Save a labeled sample for future model training.

        Args:
            signals: the raw signals
            label: caregiver-provided score 0-100 (or bucketed: 0/25/50/75/100)
            path: where to save (default: training_data.csv)
        """
        path = path or Path(__file__).parent.parent / "training_data.csv"
        header = not path.exists()

        with open(path, "a") as f:
            if header:
                f.write("timestamp,eye_contact,volume,response_latency,label\n")
            f.write(f"{signals.timestamp},{signals.eye_contact_ratio},{signals.volume_level},{signals.response_latency},{label}\n")

    def get_trend(self, window=10) -> str:
        """Get recent trend from score history."""
        if len(self.history) < 2:
            return "insufficient_data"

        recent = self.history[-window:]
        scores = [r["score"] for r in recent]

        if len(scores) < 2:
            return "stable"

        first_half = np.mean(scores[:len(scores)//2])
        second_half = np.mean(scores[len(scores)//2:])
        diff = second_half - first_half

        if diff > 10: return "improving"
        if diff < -10: return "declining"
        return "stable"
