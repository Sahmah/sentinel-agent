"""Review memory: past events a person already judged, shown to the agent as examples.

Before the agent reasons about a new event, it gets the reviewed events from the
same camera that look most like it (same label, same side of the zone, a track
of similar length), each with the person's verdict and, when vision is on, its
crop. This is how the agent learns from corrections without any training: a
"dog" that was twice marked a false alarm on this camera makes the next similar
"dog" less credible.

Examples are balanced when possible (at least one real and one false alarm), so
the model sees the contrast rather than a streak of one answer.
"""

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sentinel_agent.events.models import Event
from sentinel_agent.storage.base import EventFilter, Storage


@dataclass(frozen=True)
class Example:
    id: str
    camera_id: str
    label: str
    entered_restricted_zone: bool
    detection_count: int
    duration_seconds: float
    verdict: str  # "real" or "false_alarm"
    occurred_at: datetime | None = None
    image_path: str | None = None

    def describe(self) -> str:
        where = "inside the restricted zone" if self.entered_restricted_zone else "outside the zone"
        verdict = "REAL" if self.verdict == "real" else "FALSE ALARM"
        return (
            f"reviewed as {verdict}: detected as {self.label}, {where}, "
            f"{self.detection_count} detections over {self.duration_seconds:.1f} s"
        )


def memory_enabled() -> bool:
    return os.environ.get("SENTINEL_LLM_MEMORY", "1").lower() not in ("0", "false", "no")


def _distance(example: Example, event: Event) -> float:
    zone = 0.0 if example.entered_restricted_zone == event.entered_restricted_zone else 1.0
    # Track length on a log scale: 1 vs 2 detections differ as much as 40 vs 80.
    length = abs(math.log1p(example.detection_count) - math.log1p(event.detection_count))
    return zone + length


class ReviewMemory:
    def __init__(
        self,
        load: Callable[[], list[Example]],
        *,
        k: int = 4,
        refresh_seconds: float | None = None,
    ):
        """`load` returns every reviewed example; with `refresh_seconds`, it is called
        again once that long has passed, so reviews made during a run are picked up."""
        self._load = load
        self.k = k
        self.refresh_seconds = refresh_seconds
        self._examples = load()
        self._loaded_at = time.monotonic()

    @property
    def examples(self) -> list[Example]:
        if (
            self.refresh_seconds is not None
            and time.monotonic() - self._loaded_at > self.refresh_seconds
        ):
            self._examples = self._load()
            self._loaded_at = time.monotonic()
        return self._examples

    def __len__(self) -> int:
        return len(self.examples)

    def examples_for(self, event: Event) -> list[Example]:
        candidates = [
            e
            for e in self.examples
            if e.camera_id == event.camera_id and e.label == event.label and e.id != event.id
        ]
        # Most similar first; among equals, the most recent.
        candidates.sort(
            key=lambda e: (
                _distance(e, event),
                -(e.occurred_at.timestamp() if e.occurred_at else 0),
            )
        )
        chosen = candidates[: self.k]
        verdicts = {e.verdict for e in chosen}
        if len(verdicts) == 1 and len(chosen) == self.k:
            # Swap the least similar pick for the best example of the other verdict.
            other = next((e for e in candidates if e.verdict not in verdicts), None)
            if other is not None:
                chosen[-1] = other
        return chosen

    @classmethod
    def from_storage(
        cls, storage: Storage, camera_id: str, *, image_root: Path | None = None, **kwargs
    ) -> "ReviewMemory":
        def load() -> list[Example]:
            examples: list[Example] = []
            cursor = None
            for _ in range(50):  # at most 5,000 events scanned
                page = storage.query(EventFilter(camera_id=camera_id), limit=100, cursor=cursor)
                for r in page.events:
                    if r.review is None:
                        continue
                    image = str(image_root / r.snapshot) if image_root and r.snapshot else None
                    examples.append(
                        Example(
                            id=r.id,
                            camera_id=r.camera_id,
                            label=r.label,
                            entered_restricted_zone=r.entered_restricted_zone,
                            detection_count=r.detection_count,
                            duration_seconds=r.duration_seconds,
                            verdict=r.review,
                            occurred_at=r.occurred_at,
                            image_path=image,
                        )
                    )
                cursor = page.next_cursor
                if cursor is None:
                    break
            return examples

        return cls(load, **kwargs)

    @classmethod
    def from_events(cls, events: list[Event], **kwargs) -> "ReviewMemory":
        """Synthetic events whose ground truth stands in for a person's verdict
        (how `sentinel eval-llm --memory` measures the effect of memory)."""
        examples = [
            Example(
                id=e.id,
                camera_id=e.camera_id,
                label=e.label,
                entered_restricted_zone=e.entered_restricted_zone,
                detection_count=e.detection_count,
                duration_seconds=round(e.end_ts - e.start_ts, 2),
                verdict="real" if e.is_true_positive else "false_alarm",
            )
            for e in events
            if e.is_true_positive is not None
        ]
        return cls(lambda: examples, **kwargs)
