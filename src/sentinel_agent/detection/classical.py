"""A classical (non-deep-learning) computer-vision detector.

Thresholds the frame against a known background level, finds contours, and
scores each by shape (circularity) and size — the same category of technique
referenced on the "ajuste de parâmetros e análise de scores de confiança" line
of a CV production background, just intentionally simple so the repo installs
and runs anywhere with no GPU/large model download.

Swap in a real model (e.g. YOLO) by implementing the `Detector` protocol in
`base.py` — nothing else in the pipeline needs to change.
"""

import cv2
import numpy as np

from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.zones import point_in_zone

# A discretized filled circle scores ~0.83 and a filled square exactly pi/4 ~= 0.785,
# so 0.80 separates round blobs from boxy clutter. Round-ish ellipses still land
# above it — those are the realistic "looks like a person, isn't" false positives.
CIRCULARITY_PERSON_THRESHOLD = 0.80


class ClassicalCVDetector:
    def __init__(
        self, *, background_level: int = 24, min_contrast: int = 80, min_area: float = 20.0
    ):
        self.background_level = background_level
        # High enough that painted scene markings (the restricted-zone overlay) stay
        # below threshold — only foreground objects should become contours.
        self.min_contrast = min_contrast
        self.min_area = min_area

    def detect(
        self, frame: np.ndarray, *, camera_id: str, frame_index: int, timestamp: float
    ) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(
            gray, self.background_level + self.min_contrast, 255, cv2.THRESH_BINARY
        )
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: list[Detection] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue

            circularity = float(np.clip(4 * np.pi * area / (perimeter**2), 0.0, 1.0))
            x, y, w, h = cv2.boundingRect(contour)
            center = (x + w // 2, y + h // 2)
            label = "person" if circularity >= CIRCULARITY_PERSON_THRESHOLD else "object"

            # Classical shape-match confidence is typically overconfident —
            # that's intentional here, it's exactly what calibration/ corrects.
            raw_confidence = float(np.clip(0.5 + 0.5 * circularity, 0.0, 0.99))

            detections.append(
                Detection(
                    camera_id=camera_id,
                    frame_index=frame_index,
                    timestamp=timestamp,
                    label=label,
                    bbox=(x, y, w, h),
                    raw_confidence=raw_confidence,
                    in_restricted_zone=point_in_zone(center),
                )
            )
        return detections
