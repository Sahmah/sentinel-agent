import threading
import time

import numpy as np

from sentinel_agent.capture import LatestFrameReader


class _FakeCamera:
    """Delivers numbered frames at a steady rate, like a webcam, then stops."""

    def __init__(self, n_frames: int, interval: float = 0.01):
        self.n_frames, self.interval, self.sent = n_frames, interval, 0
        self.lock = threading.Lock()

    def read(self):
        time.sleep(self.interval)
        with self.lock:
            if self.sent >= self.n_frames:
                return False, None
            self.sent += 1
            return True, np.full((2, 2), self.sent, np.uint8)


def test_slow_consumer_gets_the_newest_frame_not_a_backlog():
    reader = LatestFrameReader(_FakeCamera(n_frames=40))
    ok, frame, seq = reader.read(0)
    assert ok and seq >= 1 and frame[0, 0] == seq
    time.sleep(0.15)  # a slow detector: ~15 frames arrive meanwhile
    ok, frame, newer = reader.read(seq)
    assert ok and newer >= seq + 10 and frame[0, 0] == newer  # skipped ahead, not queued
    reader.close()


def test_reports_the_end_of_the_stream():
    reader = LatestFrameReader(_FakeCamera(n_frames=3))
    seq = 0
    while True:
        ok, _, seq = reader.read(seq, timeout=1.0)
        if not ok:
            break
    assert seq == 3
    reader.close()
