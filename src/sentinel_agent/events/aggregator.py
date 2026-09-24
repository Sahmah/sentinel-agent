"""Temporal + spatial clustering: raw per-frame detections -> Events.

Grouped by (camera_id, label); a detection extends an open event when it is
within `gap_seconds` of that event's latest detection AND its box center is
within `max_distance_px` of it (a minimal greedy tracker). Otherwise it starts
a new event. Without the spatial check, two unrelated objects with the same
label on the same camera would merge into one event.
"""

import math
import uuid
from collections import defaultdict

from sentinel_agent.detection.models import Detection
from sentinel_agent.events.models import Event


def cluster_into_events(
    detections: list[Detection], *, gap_seconds: float = 1.0, max_distance_px: float = 40.0
) -> list[Event]:
    clusters = cluster_detections(
        detections, gap_seconds=gap_seconds, max_distance_px=max_distance_px
    )
    events = [build_event(c) for c in clusters]
    events.sort(key=lambda e: (e.start_ts, e.label))
    return events


def cluster_detections(
    detections: list[Detection], *, gap_seconds: float = 1.0, max_distance_px: float = 40.0
) -> list[list[Detection]]:
    """The clusters themselves (each sorted by time), for callers that need to
    know which detections went into which event — e.g. a streaming aggregator
    that removes a closed event's detections from its buffer."""
    groups: dict[tuple[str, str], list[Detection]] = defaultdict(list)
    for d in detections:
        groups[(d.camera_id, d.label)].append(d)

    clusters: list[list[Detection]] = []
    for group in groups.values():
        group.sort(key=lambda d: (d.timestamp, d.bbox))
        open_clusters: list[list[Detection]] = []
        for d in group:
            best: list[Detection] | None = None
            best_dist = math.inf
            for cluster in open_clusters:
                last = cluster[-1]
                if d.timestamp - last.timestamp > gap_seconds or last.timestamp == d.timestamp:
                    continue
                dist = _center_distance(last, d)
                if dist <= max_distance_px and dist < best_dist:
                    best, best_dist = cluster, dist
            if best is None:
                open_clusters.append([d])
            else:
                best.append(d)
        clusters.extend(open_clusters)
    return clusters


def _center(d: Detection) -> tuple[float, float]:
    x, y, w, h = d.bbox
    return x + w / 2, y + h / 2


def _center_distance(a: Detection, b: Detection) -> float:
    (ax, ay), (bx, by) = _center(a), _center(b)
    return math.hypot(ax - bx, ay - by)


def build_event(cluster: list[Detection]) -> Event:
    camera_id, label = cluster[0].camera_id, cluster[0].label
    confidences = [d.raw_confidence for d in cluster]
    labeled = [d.is_true_positive for d in cluster if d.is_true_positive is not None]
    best = max(cluster, key=lambda d: d.raw_confidence)
    return Event(
        id=str(uuid.uuid4()),
        camera_id=camera_id,
        label=label,
        start_ts=cluster[0].timestamp,
        end_ts=cluster[-1].timestamp,
        detection_count=len(cluster),
        max_raw_confidence=max(confidences),
        mean_raw_confidence=sum(confidences) / len(confidences),
        entered_restricted_zone=any(d.in_restricted_zone for d in cluster),
        is_true_positive=(sum(labeled) * 2 > len(labeled)) if labeled else None,
        best_frame_index=best.frame_index,
        best_bbox=best.bbox,
    )
