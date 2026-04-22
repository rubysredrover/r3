"""Face detection, recognition, and basic emotion via inspireface (on-device).

InspireFace runs entirely on the Jetson — no cloud calls.
Handles: face detection, identity matching, and basic emotion classification.
Gemini is only called for CP-aware nuance when needed.
"""

import numpy as np

try:
    import inspireface as isf
    INSPIREFACE_AVAILABLE = True
except ImportError:
    INSPIREFACE_AVAILABLE = False


class FaceEncoder:
    """On-device face detection, recognition, and emotion via inspireface.

    Capabilities:
    - Detect faces in a frame
    - Extract face embeddings for identity
    - Match against known faces
    - Basic emotion classification (on-device)
    """

    def __init__(self, recognition=True, emotion=True):
        if not INSPIREFACE_AVAILABLE:
            raise ImportError(
                "inspireface not available. "
                "Should be pre-installed on MARS (innate-os)."
            )

        # build feature flags
        opt = isf.HF_ENABLE_NONE
        if recognition:
            opt |= isf.HF_ENABLE_FACE_RECOGNITION
        if emotion:
            opt |= isf.HF_ENABLE_FACE_EMOTION
        opt |= isf.HF_ENABLE_QUALITY

        self.session = isf.InspireFaceSession(opt, isf.HF_DETECT_MODE_ALWAYS_DETECT)
        self._recognition = recognition
        self._emotion = emotion

    def detect_and_analyze(self, frame: np.ndarray) -> dict | None:
        """Detect the primary face, extract embedding and emotion.

        Returns dict with:
            - embedding: face feature vector (for identity matching)
            - emotion: basic emotion string from on-device model
            - bbox: face bounding box
        Or None if no face detected.
        """
        # create image stream from BGR frame
        stream = isf.ImageStream.load_from_cv_image(frame)
        faces = self.session.face_detection(stream)

        if not faces:
            return None

        # pick the largest face (closest person)
        if len(faces) > 1:
            face = max(faces, key=lambda f: f.location[2] * f.location[3])
        else:
            face = faces[0]

        result = {"bbox": face.location}

        # extract face embedding for identity
        if self._recognition:
            self.session.face_feature_extract(stream, face)
            result["embedding"] = face.embedding

        # get on-device emotion
        if self._emotion:
            self.session.face_emotion_detect(stream, face)
            result["emotion"] = face.emotion if hasattr(face, 'emotion') else None

        return result

    def compare(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Compare two face embeddings. Returns similarity score 0-1."""
        return isf.feature_comparison(embedding1, embedding2)

    def match(self, embedding: np.ndarray, known_embeddings: list[dict], threshold: float = 0.5) -> dict | None:
        """Compare an embedding against known people.

        known_embeddings: list of {"person_id": int, "embedding": np.ndarray}
        Returns the best match or None.
        """
        if not known_embeddings:
            return None

        best_match = None
        best_score = 0.0

        for known in known_embeddings:
            score = self.compare(embedding, known["embedding"])
            if score > best_score:
                best_score = score
                best_match = known

        if best_score >= threshold:
            return {
                "person_id": best_match["person_id"],
                "score": float(best_score),
                "confidence": "high" if best_score > 0.7 else "medium",
            }

        return None

    @staticmethod
    def embedding_to_bytes(embedding: np.ndarray) -> bytes:
        """Serialize embedding for storage in SQLite."""
        return embedding.tobytes()

    @staticmethod
    def bytes_to_embedding(data: bytes) -> np.ndarray:
        """Deserialize embedding from SQLite storage."""
        return np.frombuffer(data, dtype=np.float32)
