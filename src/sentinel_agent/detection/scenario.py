"""Deterministic synthetic camera feed for the zero-AWS demo.

We draw the scene ourselves (OpenCV primitives), so we know ground truth for
every frame. That's what lets `sentinel demo` fit the confidence calibrators
(see `calibration/calibrators.py`) without needing an external labeled dataset
— a real deployment would instead calibrate against a human-reviewed history
of true/false positives (see the confidence-calibration skill, section 1).

The detector itself (`ClassicalCVDetector`) still only ever sees raw pixels —
it does not receive the ground truth directly.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from sentinel_agent.detection.models import Detection
from sentinel_agent.detection.zones import RESTRICTED_ZONE, point_in_zone

FRAME_WIDTH = 320
FRAME_HEIGHT = 240


@dataclass(frozen=True)
class SyntheticFrame:
    camera_id: str
    frame_index: int
    timestamp: float
    frame: np.ndarray
    target_center: tuple[int, int]
    target_in_zone: bool


@dataclass
class _Decoy:
    center: tuple[int, int]
    shape: str  # "square" | "ellipse"
    size: int
    frames_left: int


def generate_scenario(
    *,
    camera_id: str = "cam-01",
    n_frames: int = 90,
    fps: float = 5.0,
    seed: int = 1,
    decoy_spawn_prob: float = 0.12,
) -> list[SyntheticFrame]:
    """A round "target" blob drifts left-to-right and crosses the restricted
    zone partway through. Short-lived decoys flicker in and out at random
    positions: boxy ones (easy for the detector to reject on shape) and round
    ellipses (which the detector mistakes for a person — the realistic false
    positives the calibration and reasoning stages have to deal with)."""
    rng = np.random.default_rng(seed)
    frames: list[SyntheticFrame] = []
    decoys: list[_Decoy] = []

    y_track = FRAME_HEIGHT // 2 + 10
    x_start, x_end = 20, FRAME_WIDTH - 20

    for i in range(n_frames):
        t = i / fps
        frame = np.full((FRAME_HEIGHT, FRAME_WIDTH, 3), 24, dtype=np.uint8)

        zx, zy, zw, zh = RESTRICTED_ZONE
        cv2.rectangle(frame, (zx, zy), (zx + zw, zy + zh), (40, 40, 90), thickness=-1)
        cv2.rectangle(frame, (zx, zy), (zx + zw, zy + zh), (70, 70, 140), thickness=1)

        progress = i / max(n_frames - 1, 1)
        cx = int(x_start + progress * (x_end - x_start))
        cy = y_track + int(4 * np.sin(progress * 6))
        radius = 10
        cv2.circle(frame, (cx, cy), radius, (210, 210, 210), thickness=-1)

        if rng.random() < decoy_spawn_prob:
            decoys.append(
                _Decoy(
                    center=(
                        int(rng.integers(20, FRAME_WIDTH - 20)),
                        int(rng.integers(20, FRAME_HEIGHT - 20)),
                    ),
                    shape="ellipse" if rng.random() < 0.5 else "square",
                    size=int(rng.integers(7, 12)),
                    frames_left=int(rng.integers(1, 5)),
                )
            )
        for decoy in decoys:
            dx, dy = decoy.center
            if decoy.shape == "square":
                cv2.rectangle(
                    frame,
                    (dx - decoy.size, dy - decoy.size),
                    (dx + decoy.size, dy + decoy.size),
                    (150, 150, 150),
                    thickness=-1,
                )
            else:
                cv2.ellipse(
                    frame, (dx, dy), (decoy.size, decoy.size - 2), 30, 0, 360, (150, 150, 150), -1
                )
            decoy.frames_left -= 1
        decoys = [d for d in decoys if d.frames_left > 0]

        frames.append(
            SyntheticFrame(
                camera_id=camera_id,
                frame_index=i,
                timestamp=t,
                frame=frame,
                target_center=(cx, cy),
                target_in_zone=point_in_zone((cx, cy)),
            )
        )

    return frames


def label_detections(frame: SyntheticFrame, detections: list[Detection]) -> list[Detection]:
    """Attach ground truth: a detection is a true positive iff its box contains
    the target's (known) center. Only possible because we drew the scene."""
    cx, cy = frame.target_center
    labeled = []
    for d in detections:
        x, y, w, h = d.bbox
        hit = x <= cx <= x + w and y <= cy <= y + h
        labeled.append(d.model_copy(update={"is_true_positive": hit}))
    return labeled
