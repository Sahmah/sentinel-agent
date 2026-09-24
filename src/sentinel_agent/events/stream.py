"""Incremental version of `cluster_into_events` for live input (webcam/video).

Detections are buffered; an event is closed and emitted once its object has
not been seen for `gap_seconds`. A track that is still going after
`max_event_seconds` is emitted anyway (and a fresh event starts), so someone
standing in front of the camera for minutes still gets reasoned about.
"""

from sentinel_agent.detection.models import Detection
from sentinel_agent.events.aggregator import build_event, cluster_detections
from sentinel_agent.events.models import Event


class StreamingAggregator:
    def __init__(
        self,
        *,
        gap_seconds: float = 1.0,
        max_distance_px: float = 80.0,
        max_event_seconds: float = 30.0,
    ):
        self.gap_seconds = gap_seconds
        self.max_distance_px = max_distance_px
        self.max_event_seconds = max_event_seconds
        self._buffer: list[Detection] = []

    def add(self, detections: list[Detection]) -> None:
        self._buffer.extend(detections)

    def pop_closed(self, now: float) -> list[Event]:
        """Emit events that ended more than `gap_seconds` before `now`, or that
        have run longer than `max_event_seconds`."""
        return self._pop(lambda c: self._is_closed(c, now))

    def flush(self) -> list[Event]:
        """Emit everything still buffered (end of stream)."""
        return self._pop(lambda c: True)

    def _is_closed(self, cluster: list[Detection], now: float) -> bool:
        idle = now - cluster[-1].timestamp > self.gap_seconds
        too_long = cluster[-1].timestamp - cluster[0].timestamp >= self.max_event_seconds
        return idle or too_long

    def _pop(self, should_emit) -> list[Event]:
        clusters = cluster_detections(
            self._buffer, gap_seconds=self.gap_seconds, max_distance_px=self.max_distance_px
        )
        emitted = [c for c in clusters if should_emit(c)]
        emitted_ids = {id(d) for c in emitted for d in c}
        self._buffer = [d for d in self._buffer if id(d) not in emitted_ids]
        events = [build_event(c) for c in emitted]
        events.sort(key=lambda e: (e.start_ts, e.label))
        return events
