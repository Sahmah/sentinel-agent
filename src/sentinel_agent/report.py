"""Markdown reports of what happened, written to a local lab folder.

`sentinel demo` and `sentinel webcam` write one for their own run when they
finish; `sentinel report` writes one for any period. A report is a plain
Markdown file with the counts, what needs a person, and every event with its
crop, so it opens in any editor or Markdown viewer and can be diffed or kept.

The folder is `lab/` (SENTINEL_LAB_DIR), which git ignores: it is for local
test runs, not for the repository.
"""

import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sentinel_agent.snapshots import snapshot_dir
from sentinel_agent.storage.base import EventFilter, EventRecord, Storage

ACTION_ORDER = ["alert", "human_review", "logged", "dismissed"]


def lab_dir() -> Path:
    return Path(os.environ.get("SENTINEL_LAB_DIR", "lab"))


def collect(
    storage: Storage, filters: EventFilter, *, run_id: str | None = None
) -> list[EventRecord]:
    """Every matching event, oldest first."""
    records: list[EventRecord] = []
    cursor = None
    while True:
        page = storage.query(filters, limit=100, cursor=cursor)
        records += [r for r in page.events if run_id is None or r.run_id == run_id]
        cursor = page.next_cursor
        if cursor is None:
            break
    return sorted(records, key=lambda r: r.occurred_at)


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def render(records: list[EventRecord], *, title: str, image_root: Path, out_dir: Path) -> str:
    """The report as Markdown. Image links are relative to `out_dir`, where the file goes."""
    lines = [f"# {title}", ""]
    if not records:
        return "\n".join([*lines, "No events in this period."]) + "\n"

    first, last = records[0].occurred_at, records[-1].occurred_at
    actions = Counter(r.action for r in records)
    labels = Counter(r.label for r in records)
    reviewed = [r for r in records if r.review]
    calibrated = sum(r.p_cv_calibrated for r in records)
    lines += [
        f"{len(records)} events from {first:%Y-%m-%d %H:%M:%S} to {last:%H:%M:%S} UTC "
        f"({', '.join(sorted({r.camera_id for r in records}))}).",
        "",
        "| Decision | Events |",
        "| --- | --- |",
        *[f"| {a} | {actions[a]} |" for a in ACTION_ORDER if actions[a]],
        "",
        "Labels: " + ", ".join(f"{label} {n}" for label, n in labels.most_common()) + ".",
        f"Vision and agent disagreed on {sum(r.disagreement for r in records)} events. "
        f"People reviewed {len(reviewed)} ({sum(r.review == 'real' for r in reviewed)} real, "
        f"{sum(r.review == 'false_alarm' for r in reviewed)} false alarms). "
        f"p_cv was calibrated on {calibrated} of {len(records)} events.",
        "",
    ]

    need_a_person = [r for r in records if r.action in ("alert", "human_review") and not r.review]
    if need_a_person:
        lines += ["## Needs a person", ""]
        lines += [f"- {_event_line(r)}" for r in need_a_person]
        lines.append("")

    lines += ["## All events", ""]
    for r in records:
        lines += [f"### {r.occurred_at:%H:%M:%S} · {r.label} · {r.action}", ""]
        if r.snapshot and (image_root / r.snapshot).is_file():
            crop = os.path.relpath(image_root / r.snapshot, out_dir)
            lines += [f"![{r.label} crop]({crop})", ""]
        lines += [
            f"- {r.detection_count} detections over {r.duration_seconds:.1f} s, "
            + ("entered the restricted zone" if r.entered_restricted_zone else "outside the zone"),
            f"- vision {_pct(r.p_cv)}{'' if r.p_cv_calibrated else ' (raw)'}, "
            f"agent {_pct(r.llm_confidence)}, fused {_pct(r.combined_confidence)}"
            + (", **disagreement**" if r.disagreement else ""),
        ]
        if r.reasoning:
            lines.append(f"- agent: {r.reasoning}")
        elif r.triage_reason:
            lines.append(f"- not sent to the agent: {r.triage_reason}")
        if r.review:
            lines.append(f"- reviewed: {r.review.replace('_', ' ')}")
        if r.is_true_positive is not None:
            lines.append(f"- synthetic ground truth: {'real' if r.is_true_positive else 'false'}")
        lines += [f"- id `{r.id}`", ""]
    return "\n".join(lines)


def _event_line(r: EventRecord) -> str:
    return (
        f"{r.occurred_at:%H:%M:%S} **{r.action}** {r.label}, vision {_pct(r.p_cv)}, "
        f"agent {_pct(r.llm_confidence)} (`{r.id[:8]}`)"
    )


def write_report(
    storage: Storage,
    *,
    title: str,
    filters: EventFilter | None = None,
    run_id: str | None = None,
    name: str | None = None,
) -> Path:
    out_dir = lab_dir() / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = collect(storage, filters or EventFilter(), run_id=run_id)
    name = name or f"report-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    path = out_dir / f"{name}.md"
    path.write_text(render(records, title=title, image_root=snapshot_dir(), out_dir=out_dir))
    return path
