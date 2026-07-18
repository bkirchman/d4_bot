from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.interfaces import StampedFrame

from d4_bot.capture import load_hardware_config
from d4_bot.detectors import build_detectors, load_rois, load_season_overrides
from d4_bot.detectors.minimap_pin import MinimapPinDetector, MinimapPinResult


def _frame(frame_id: int, image: np.ndarray) -> StampedFrame:
    return StampedFrame(frame_id=frame_id, timestamp=frame_id / 60.0, frame=image)


def test_minimap_pin_detector_sentinel_then_match(tmp_path: Path) -> None:
    template = np.zeros((10, 8, 3), dtype=np.uint8)
    template[2:8, 2:6] = (255, 128, 64)
    template_path = tmp_path / "template.png"
    assert cv2.imwrite(str(template_path), template)

    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    x, y = 1600, 80
    frame[y : y + template.shape[0], x : x + template.shape[1]] = template

    config = {
        "minimap_pin_template_path": str(template_path),
        "minimap_pin_search_roi_x1": 1590,
        "minimap_pin_search_roi_y1": 41,
        "minimap_pin_search_roi_x2": 1922,
        "minimap_pin_search_roi_y2": 271,
        "minimap_pin_match_threshold": 0.7,
        "minimap_pin_detector_cadence": 3,
    }

    detector = MinimapPinDetector(config, template_path)

    sentinel = detector.update(_frame(1, frame))
    assert sentinel == MinimapPinResult(pin_visible=False, pin_position=None, confidence=0.0)

    still_sentinel = detector.update(_frame(2, frame))
    assert still_sentinel == MinimapPinResult(pin_visible=False, pin_position=None, confidence=0.0)

    match = detector.update(_frame(3, frame))
    assert match.pin_visible is True
    assert match.pin_position == (x + template.shape[1] // 2, y + template.shape[0] // 2)
    assert match.confidence >= 0.7


def test_build_detectors_includes_minimap_pin() -> None:
    config_dir = REPO_ROOT / "configs"
    rois = load_rois(config_dir / "rois.yaml")
    hardware = load_hardware_config(config_dir)
    season = str(hardware["active_season"])
    season_overrides = load_season_overrides(config_dir, season)

    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)

    assert "minimap_pin" in detectors
    assert isinstance(detectors["minimap_pin"], MinimapPinDetector)