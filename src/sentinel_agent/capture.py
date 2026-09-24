"""Camera reading in a background thread, keeping only the newest frame.

When the same loop reads the camera and runs the detector, frames pile up in
the driver while the detector works, and slow links drop them: a webcam
forwarded into WSL with usbipd delivered ~14 fps on its own but only 3.5 fps
of analysis when read inline. Reading in a thread keeps the camera drained,
and the analysis loop always gets the latest frame.

Only for live cameras: a video file should be read frame by frame, in order.
"""

import threading

import numpy as np


class LatestFrameReader:
    def __init__(self, capture):
        """`capture` is anything with `read() -> (ok, frame)`, e.g. cv2.VideoCapture."""
        self._capture = capture
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._ok = True
        self._seq = 0  # number of frames read so far; doubles as a unique frame index
        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped:
            ok, frame = self._capture.read()
            with self._cond:
                self._ok = ok
                if ok:
                    self._frame = frame
                    self._seq += 1
                self._cond.notify_all()
            if not ok:
                return

    def read(self, last_seq: int, timeout: float = 5.0) -> tuple[bool, np.ndarray | None, int]:
        """Wait for a frame newer than `last_seq`. Returns (ok, frame, seq); ok is
        False when the camera stopped or nothing new arrived within `timeout`."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > last_seq or not self._ok, timeout=timeout)
            if self._seq > last_seq:
                return True, self._frame, self._seq
            return False, None, self._seq

    def close(self) -> None:
        self._stopped = True
        self._thread.join(timeout=2.0)
