from typing import Protocol

import numpy as np

from sentinel_agent.detection.models import Detection


class Detector(Protocol):
    """Anything that can turn a video frame into detections.

    `ClassicalCVDetector` is the bundled implementation. A production deployment
    can swap in a deep-learning detector (e.g. YOLO) by implementing this same
    protocol — no other code in the pipeline needs to change.
    """

    def detect(
        self, frame: np.ndarray, *, camera_id: str, frame_index: int, timestamp: float
    ) -> list[Detection]: ...
