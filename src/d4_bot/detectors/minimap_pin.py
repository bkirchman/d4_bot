from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from framework.interfaces import StampedFrame


@dataclass(frozen=True, slots=True)
class MinimapPinResult:
    pin_visible: bool
    pin_position: tuple[int, int] | None
    confidence: float


@dataclass(slots=True)
class MinimapPinDetector:
    config: dict[str, Any]
    template_path: str | Path
    _template: Any = field(init=False, repr=False)
    _template_width: int = field(init=False, repr=False)
    _template_height: int = field(init=False, repr=False)
    _search_roi: tuple[int, int, int, int] = field(init=False, repr=False)
    _match_threshold: float = field(init=False, repr=False)
    _cadence: int = field(init=False, repr=False)
    _last_result: MinimapPinResult = field(init=False, repr=False)
    _last_inference_frame_id: int | None = field(default=None, init=False, repr=False)
    _frame_bounds_validated: bool = field(default=False, init=False, repr=False)
    _validated_search_roi: tuple[int, int, int, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._search_roi = self._validate_search_roi(self.config)
        self._match_threshold = float(self._require_config_key("minimap_pin_match_threshold"))
        self._cadence = int(self._require_config_key("minimap_pin_detector_cadence"))

        if self._cadence < 1:
            raise ValueError("minimap_pin_detector_cadence must be >= 1")
        if not 0.0 <= self._match_threshold <= 1.0:
            raise ValueError("minimap_pin_match_threshold must be between 0.0 and 1.0")

        self._template = self._load_template(Path(self.template_path))
        self._template_height, self._template_width = self._template.shape[:2]
        if self._template_height <= 0 or self._template_width <= 0:
            raise ValueError(f"template image '{self.template_path}' is empty")

        self._last_result = MinimapPinResult(pin_visible=False, pin_position=None, confidence=0.0)

    @property
    def last_result(self) -> MinimapPinResult:
        return self._last_result

    @property
    def last_inference_frame_id(self) -> int | None:
        return self._last_inference_frame_id

    def update(self, frame: StampedFrame) -> MinimapPinResult:
        frame_view = frame.frame
        self._ensure_frame_bounds(frame_view)

        if frame.frame_id % self._cadence != 0:
            return self._last_result

        x1, y1, x2, y2 = self._validated_search_roi
        assert x1 is not None and y1 is not None and x2 is not None and y2 is not None

        cv2 = self._import_cv2()
        search_region = frame_view[y1:y2, x1:x2]
        if search_region.size == 0:
            raise ValueError("search ROI is empty for the current frame")
        if search_region.shape[0] < self._template_height or search_region.shape[1] < self._template_width:
            raise ValueError("search ROI is smaller than the template image")

        match = cv2.matchTemplate(search_region, self._template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_loc = cv2.minMaxLoc(match)

        center_x = x1 + int(max_loc[0]) + (self._template_width // 2)
        center_y = y1 + int(max_loc[1]) + (self._template_height // 2)
        pin_visible = float(max_value) >= self._match_threshold
        pin_position = (center_x, center_y) if pin_visible else None

        self._last_result = MinimapPinResult(
            pin_visible=pin_visible,
            pin_position=pin_position,
            confidence=float(max_value),
        )
        self._last_inference_frame_id = frame.frame_id
        return self._last_result

    def _ensure_frame_bounds(self, frame_view: Any) -> None:
        if self._frame_bounds_validated:
            return

        if not hasattr(frame_view, "shape"):
            raise ValueError("frame must provide a shape attribute")

        height, width = frame_view.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("frame is empty")

        x1, y1, x2, y2 = self._search_roi
        clipped_x2 = min(x2, width)
        clipped_y2 = min(y2, height)

        if x1 >= width or y1 >= height:
            raise ValueError("search ROI origin lies outside the frame")
        if clipped_x2 <= x1 or clipped_y2 <= y1:
            raise ValueError("search ROI does not overlap the current frame")

        self._validated_search_roi = (x1, y1, clipped_x2, clipped_y2)
        self._frame_bounds_validated = True

    def _validate_search_roi(self, config: dict[str, Any]) -> tuple[int, int, int, int]:
        x1 = self._require_positive_int("minimap_pin_search_roi_x1")
        y1 = self._require_positive_int("minimap_pin_search_roi_y1")
        x2 = self._require_positive_int("minimap_pin_search_roi_x2")
        y2 = self._require_positive_int("minimap_pin_search_roi_y2")

        if x2 <= x1:
            raise ValueError("minimap_pin_search_roi_x2 must be greater than minimap_pin_search_roi_x1")
        if y2 <= y1:
            raise ValueError("minimap_pin_search_roi_y2 must be greater than minimap_pin_search_roi_y1")
        return (x1, y1, x2, y2)

    def _require_positive_int(self, key: str) -> int:
        value = int(self._require_config_key(key))
        if value <= 0:
            raise ValueError(f"{key} must be a positive integer")
        return value

    def _require_config_key(self, key: str) -> Any:
        if key not in self.config:
            raise ValueError(f"minimap pin config missing required key '{key}'")
        return self.config[key]

    @staticmethod
    def _load_template(path: Path) -> Any:
        cv2 = MinimapPinDetector._import_cv2()
        template = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if template is None or template.size == 0:
            raise ValueError(f"failed to load template image '{path}'")
        return template

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("OpenCV is required for MinimapPinDetector") from exc
        return cv2