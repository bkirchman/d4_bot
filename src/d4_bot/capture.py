from __future__ import annotations

from pathlib import Path
from typing import Any

from framework.contrib.config import load_layered_config
from framework.contrib.hardware import AVerMediaCapture, UDPXboxOutput
from framework.interfaces import StampedFrame


REQUIRED_HARDWARE_KEYS = (
    "capture.device_index",
    "capture.backend",
    "capture.width",
    "capture.height",
    "capture.fps",
    "capture.latency_frames",
    "controller.udp_ip",
    "controller.udp_port",
    "controller.response_port",
    "controller.response_mode",
    "active_season",
)


def load_hardware_config(config_dir: str | Path) -> dict[str, Any]:
    config_path = Path(config_dir) / "hardware.yaml"
    config = load_layered_config(config_path)
    _validate_required_hardware_keys(config)
    return config


def build_capture(config_dir: str | Path) -> tuple[AVerMediaCapture, StampedFrame]:
    hardware = load_hardware_config(config_dir)
    capture_cfg = hardware["capture"]

    capture = AVerMediaCapture(
        device_index=int(capture_cfg["device_index"]),
        width=int(capture_cfg["width"]),
        height=int(capture_cfg["height"]),
        fps=float(capture_cfg["fps"]),
        latency_frames=int(capture_cfg["latency_frames"]),
        backend=str(capture_cfg["backend"]),
    )

    first_frame = capture.get_frame()
    assert_capture_geometry(
        first_frame,
        expected_width=int(capture_cfg["width"]),
        expected_height=int(capture_cfg["height"]),
    )

    print(
        "capture startup: "
        f"resolution={first_frame.frame.shape[1]}x{first_frame.frame.shape[0]} "
        f"fps={capture.fps:.1f} latency_frames={capture.latency_frames}"
    )

    return capture, first_frame


def build_output(config_dir: str | Path, debug_mode: bool = False) -> UDPXboxOutput:
    hardware = load_hardware_config(config_dir)
    controller_cfg = hardware["controller"]

    return UDPXboxOutput(
        udp_ip=str(controller_cfg["udp_ip"]),
        udp_port=int(controller_cfg["udp_port"]),
        response_port=int(controller_cfg["response_port"]),
        response_mode=int(controller_cfg["response_mode"]),
        debug_mode=debug_mode,
    )


def assert_capture_geometry(frame: StampedFrame, expected_width: int, expected_height: int) -> None:
    actual_height, actual_width = frame.frame.shape[:2]
    if actual_width != expected_width or actual_height != expected_height:
        raise RuntimeError(
            "capture geometry mismatch: "
            f"expected {expected_width}x{expected_height}, got {actual_width}x{actual_height}"
        )


def _validate_required_hardware_keys(config: dict[str, Any]) -> None:
    for dotted_key in REQUIRED_HARDWARE_KEYS:
        _require_nested_key(config, dotted_key)


def _require_nested_key(config: dict[str, Any], dotted_key: str) -> None:
    current: Any = config
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"hardware config missing required key '{dotted_key}'")
        current = current[key]
