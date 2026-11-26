from __future__ import annotations

from framework.contrib.detection import FillLevelDetector, FillLevelResult
from framework.interfaces import StampedFrame


class CadencedFillLevelDetector:
    def __init__(self, detector: FillLevelDetector, cadence: int) -> None:
        if cadence < 1:
            raise ValueError("cadence must be >= 1")
        self.detector = detector
        self._cadence = cadence
        self._last_result: FillLevelResult | None = None
        self.last_inference_frame_id: int | None = None

    def update(self, frame: StampedFrame) -> FillLevelResult | None:
        if frame.frame_id % self._cadence == 0:
            self._last_result = self.detector(frame.frame)
            self.last_inference_frame_id = frame.frame_id
        return self._last_result
