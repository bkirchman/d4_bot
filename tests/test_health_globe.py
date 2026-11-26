from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.detection import FillLevelDetector, FillLevelResult
from framework.interfaces import StampedFrame
from d4_bot.detectors import build_detector_registry, build_detectors, load_rois
from d4_bot.detectors.fill_level import CadencedFillLevelDetector
from d4_bot.state import GameStateUpdater


@pytest.fixture
def configured_detector_dir(tmp_path: Path) -> Path:
    detector_dir = tmp_path / "detectors"
    detector_dir.mkdir()
    shutil.copyfile(REPO_ROOT / "configs" / "detectors" / "health_globe.yaml", detector_dir / "health_globe.yaml")
    return detector_dir


def _config() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs" / "detectors" / "health_globe.yaml").read_text(encoding="utf-8"))


def _image(filled: bool) -> np.ndarray:
    rois = load_rois(REPO_ROOT / "configs" / "rois.yaml")
    x, y, w, h = rois["health_globe"]
    image = np.zeros((y + h, x + w, 3), dtype=np.uint8)
    if filled:
        top = _config()["full_row"]
        image[y + top : y + h, x : x + w] = (0, 0, 255)
    return image


def _frame(frame_id: int, filled: bool) -> StampedFrame:
    return StampedFrame(frame_id=frame_id, timestamp=float(frame_id), frame=_image(filled))


def test_build_health_globe_from_yaml(configured_detector_dir: Path) -> None:
    rois = load_rois(REPO_ROOT / "configs" / "rois.yaml")
    detector = build_detectors(configured_detector_dir, rois, {})["health_globe"]
    assert isinstance(detector, CadencedFillLevelDetector)
    assert isinstance(detector.detector, FillLevelDetector)
    cfg = _config()
    assert detector.detector.roi == rois["health_globe"]
    assert detector.detector.hue_range == tuple(cfg["hue_range"])
    assert detector.detector.saturation_min == cfg["saturation_min"]
    assert detector.detector.value_min == cfg["value_min"]
    assert detector.detector.row_fraction == cfg["row_fraction"]
    assert detector.detector.min_consecutive_rows == cfg["min_consecutive_rows"]
    assert detector.detector.full_row == cfg["full_row"]
    assert detector.detector.empty_row == cfg["empty_row"]


def test_health_globe_cadence_and_state_origin(configured_detector_dir: Path) -> None:
    rois = load_rois(REPO_ROOT / "configs" / "rois.yaml")
    detector = build_detectors(configured_detector_dir, rois, {})["health_globe"]
    updater = GameStateUpdater({"health_globe": detector})

    before_first = updater.update(_frame(1, True))
    assert before_first.health_fill_fraction is None
    assert before_first.health_liquid_found is False
    assert before_first.health_fill_frame_id is None

    measured = updater.update(_frame(2, True))
    assert measured.health_fill_fraction == pytest.approx(1.0)
    assert measured.health_liquid_found is True
    assert measured.health_fill_frame_id == 2

    cached = updater.update(_frame(3, False))
    assert cached.health_fill_fraction == measured.health_fill_fraction
    assert cached.health_liquid_found is True
    assert cached.health_fill_frame_id == 2

    missing = updater.update(_frame(4, False))
    assert missing.health_fill_fraction is None
    assert missing.health_liquid_found is False
    assert missing.health_fill_frame_id == 4


def test_health_state_defaults_when_detector_missing() -> None:
    state = GameStateUpdater({}).update(_frame(0, False))
    assert state.health_fill_fraction is None
    assert state.health_liquid_found is False
    assert state.health_fill_frame_id is None


def test_health_state_uses_current_frame_for_uncadenced_detector() -> None:
    result = FillLevelResult(True, 10, 0.75, 20)
    state = GameStateUpdater({"health_globe": lambda frame: result}).update(_frame(9, True))
    assert state.health_fill_fraction == 0.75
    assert state.health_liquid_found is True
    assert state.health_fill_frame_id == 9


def test_health_detector_registry_returns_liquid_found(configured_detector_dir: Path) -> None:
    rois = load_rois(REPO_ROOT / "configs" / "rois.yaml")
    registry = build_detector_registry(configured_detector_dir, rois, {})
    assert registry.get("health_globe")(_image(True)) is True
    assert registry.get("health_globe")(_image(False)) is False


def test_health_detector_rejects_missing_roi_and_invalid_cadence(configured_detector_dir: Path) -> None:
    cfg_path = configured_detector_dir / "health_globe.yaml"
    config = _config()
    rois = load_rois(REPO_ROOT / "configs" / "rois.yaml")
    del config["roi"]
    cfg_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required key 'roi'"):
        build_detectors(configured_detector_dir, rois, {})
    config["roi"] = "health_globe"
    config["cadence"] = 0
    cfg_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="cadence must be >= 1"):
        build_detectors(configured_detector_dir, rois, {})
