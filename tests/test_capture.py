from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.hardware import CaptureDeviceInfo
from framework.interfaces import StampedFrame
from d4_bot.capture import build_capture, load_hardware_config


@pytest.fixture
def hardware_config(tmp_path: Path) -> dict[str, Any]:
    config = {
        "capture": {
            "device_name": "Capture A",
            "backend": "dshow",
            "width": 4,
            "height": 3,
            "fps": 60.0,
            "latency_frames": 6,
        },
        "controller": {
            "udp_ip": "127.0.0.1",
            "udp_port": 5005,
            "response_port": 5006,
            "response_mode": 0,
        },
        "active_season": "test",
    }
    _write_config(tmp_path, config)
    return config


def _write_config(config_dir: Path, config: dict[str, Any]) -> None:
    (config_dir / "hardware.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")


def _diagnostic() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "diag_list_capture_devices", REPO_ROOT / "scripts" / "diag_list_capture_devices.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_capture_passes_name_optional_fps_settings_and_prints_banner(
    tmp_path: Path, hardware_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hardware_config["capture"].update({"fps_check_frames": 15, "min_fps_fraction": 0.8})
    _write_config(tmp_path, hardware_config)
    calls: list[dict[str, Any]] = []
    frame = StampedFrame(frame_id=0, timestamp=0.0, frame=np.zeros((3, 4, 3), dtype=np.uint8))

    class FakeCapture:
        fps = 60.0
        latency_frames = 6
        device_name_resolved = "Capture A model"
        device_path = "test-path"
        active_backend = "dshow"
        achieved_fps = 59.9

        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

        def get_frame(self) -> StampedFrame:
            return frame

    monkeypatch.setattr("d4_bot.capture.AVerMediaCapture", FakeCapture)
    _, first = build_capture(tmp_path)
    assert first is frame
    assert calls == [{
        "device_name": "Capture A", "width": 4, "height": 3, "fps": 60.0,
        "latency_frames": 6, "backend": "dshow", "fps_check_frames": 15, "min_fps_fraction": 0.8,
    }]
    banner = capsys.readouterr().out
    assert 'device="Capture A model" path=test-path backend=dshow achieved_fps=59.9' in banner
    assert "resolution=4x3 fps=60.0 latency_frames=6" in banner


def test_build_capture_uses_framework_fps_defaults(
    tmp_path: Path, hardware_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    frame = StampedFrame(frame_id=0, timestamp=0.0, frame=np.zeros((3, 4, 3), dtype=np.uint8))
    fake = SimpleNamespace(
        get_frame=lambda: frame, fps=60.0, latency_frames=6, device_name_resolved="Capture A",
        device_path=None, active_backend="dshow", achieved_fps=60.0,
    )

    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return fake

    monkeypatch.setattr("d4_bot.capture.AVerMediaCapture", create)
    build_capture(tmp_path)
    assert "fps_check_frames" not in calls[0]
    assert "min_fps_fraction" not in calls[0]


def test_build_capture_closes_device_on_geometry_failure(
    tmp_path: Path, hardware_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []
    frame = StampedFrame(frame_id=0, timestamp=0.0, frame=np.zeros((2, 4, 3), dtype=np.uint8))
    fake = SimpleNamespace(get_frame=lambda: frame, close=lambda: closed.append(True))
    monkeypatch.setattr("d4_bot.capture.AVerMediaCapture", lambda **kwargs: fake)
    with pytest.raises(RuntimeError, match="capture geometry mismatch"):
        build_capture(tmp_path)
    assert closed == [True]


def test_hardware_rejects_old_index_alongside_name(tmp_path: Path, hardware_config: dict[str, Any]) -> None:
    hardware_config["capture"]["device_index"] = 0
    _write_config(tmp_path, hardware_config)
    with pytest.raises(ValueError, match="delete.*capture.device_name"):
        load_hardware_config(tmp_path)


def test_hardware_requires_device_name(tmp_path: Path, hardware_config: dict[str, Any]) -> None:
    del hardware_config["capture"]["device_name"]
    _write_config(tmp_path, hardware_config)
    with pytest.raises(ValueError, match="capture.device_name"):
        load_hardware_config(tmp_path)


@pytest.mark.parametrize("device_name", ["", "  ", None, 123])
def test_hardware_rejects_invalid_device_name(
    tmp_path: Path, hardware_config: dict[str, Any], device_name: object
) -> None:
    hardware_config["capture"]["device_name"] = device_name
    _write_config(tmp_path, hardware_config)
    with pytest.raises(ValueError, match="capture.device_name must be a non-empty string"):
        load_hardware_config(tmp_path)


def test_capture_rejects_non_integer_fps_check_frames(
    tmp_path: Path, hardware_config: dict[str, Any]
) -> None:
    hardware_config["capture"]["fps_check_frames"] = 2.5
    _write_config(tmp_path, hardware_config)
    with pytest.raises(ValueError, match="capture.fps_check_frames must be an integer"):
        build_capture(tmp_path)


@pytest.mark.parametrize(("names", "expected"), [
    (["Capture A", "Other"], 1), (["Other"], 0), (["Capture A", "Capture A second"], 2),
])
def test_capture_device_diagnostic_reports_selection(
    tmp_path: Path, hardware_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], names: list[str], expected: int,
) -> None:
    diagnostic = _diagnostic()
    devices = [CaptureDeviceInfo(i, name, f"path-{i}", "dshow") for i, name in enumerate(names)]
    monkeypatch.setattr(diagnostic, "list_capture_devices", lambda backend: devices)
    monkeypatch.setattr(sys, "argv", ["diag_list_capture_devices.py", "--config-dir", str(tmp_path)])
    assert diagnostic.main() == (0 if expected == 1 else 1)
    output = capsys.readouterr().out
    for device in devices:
        assert f"index={device.index}" in output
        assert device.name in output
        assert device.path in output
    assert f"{expected} matches" in output
    assert output.count("[configured match]") == (1 if expected == 1 else 0)


def test_capture_device_diagnostic_without_hardware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostic = _diagnostic()
    monkeypatch.setattr(diagnostic, "list_capture_devices", lambda backend: [])
    monkeypatch.setattr(sys, "argv", ["diag_list_capture_devices.py", "--config-dir", str(tmp_path)])
    assert diagnostic.main() == 0
    assert "No hardware.yaml" in capsys.readouterr().out
