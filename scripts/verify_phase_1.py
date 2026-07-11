from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.hardware import ReplayCapture
from framework.contrib.recording import FrameRecorder
from framework.interfaces import StampedFrame

from d4_bot.capture import assert_capture_geometry
from d4_bot.commands import build_command_registry, load_buttons_config

BUTTON_KEY_RE = re.compile(r"^button_(\d+)$")
BUTTON_DURATION_KEY_RE = re.compile(r"^button_(\d+)_duration$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 1 verification harness")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--offline-only", action="store_true", help="Run replay/offline checks only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("[phase1] offline: buttons schema and payload shape")
    _check_buttons_and_registry(args.config_dir)

    print("[phase1] offline: capture geometry assertion behavior")
    _check_capture_geometry_assertion()

    print("[phase1] offline: FrameRecorder output replay compatibility")
    _check_frame_recorder_replay_compatibility()

    if args.offline_only:
        print("[phase1] offline checks PASS")
        return 0

    print("[phase1] live checks")
    _require_yes("Startup banner prints 1920x1080, fps 60, and latency_frames from CaptureSource object")
    _require_yes("Geometry assertion fails when configured resolution is deliberately falsified")
    _require_yes("diag_udp_echo.py works for press_a and press_b with correct visible in-game effect")
    _require_yes("diag_roi_viewer.py overlays minimap and nav_arrow_window correctly")
    _require_yes("30s recorded run sustains >=45 FPS and ReplayCapture replays output without error")

    print("[phase1] PASS")
    return 0


def _check_buttons_and_registry(config_dir: str) -> None:
    buttons_path = Path(config_dir) / "buttons.yaml"
    buttons = load_buttons_config(buttons_path)

    expected_names = {"press_a", "press_b"}
    if set(buttons.keys()) != expected_names:
        raise RuntimeError(
            "buttons.yaml must contain exactly press_a and press_b in Phase 1; "
            f"found {sorted(buttons.keys())}"
        )

    registry = build_command_registry(buttons)
    for name in sorted(expected_names):
        payload = registry.get(name)()
        _validate_button_duration_shape(name, payload)


def _check_capture_geometry_assertion() -> None:
    ok_frame = StampedFrame(frame_id=0, timestamp=0.0, frame=np.zeros((1080, 1920, 3), dtype=np.uint8))
    assert_capture_geometry(ok_frame, expected_width=1920, expected_height=1080)

    bad_frame = StampedFrame(frame_id=1, timestamp=0.1, frame=np.zeros((720, 1280, 3), dtype=np.uint8))
    try:
        assert_capture_geometry(bad_frame, expected_width=1920, expected_height=1080)
    except RuntimeError as exc:
        if "expected 1920x1080" not in str(exc):
            raise RuntimeError("Geometry assertion error did not include expected dimensions") from exc
    else:
        raise RuntimeError("Geometry assertion did not fail for mismatched frame shape")


def _check_frame_recorder_replay_compatibility() -> None:
    with tempfile.TemporaryDirectory(prefix="phase1_recorder_") as temp_dir:
        recorder = FrameRecorder(temp_dir, every_n=1, jpeg_quality=90)

        frame0 = StampedFrame(frame_id=0, timestamp=0.0, frame=np.zeros((1080, 1920, 3), dtype=np.uint8))
        frame1 = StampedFrame(frame_id=1, timestamp=0.016, frame=np.zeros((1080, 1920, 3), dtype=np.uint8))

        recorder.record(frame0, None)
        recorder.record(frame1, None)
        recorder.close()

        actions_lines = recorder.actions_path.read_text(encoding="utf-8").strip().splitlines()
        if len(actions_lines) != 2:
            raise RuntimeError(f"actions.jsonl must contain one line per record call, found {len(actions_lines)}")

        for line in actions_lines:
            parsed = json.loads(line)
            if "frame_id" not in parsed or "timestamp" not in parsed or "action" not in parsed:
                raise RuntimeError("actions.jsonl line missing required fields")

        replay = ReplayCapture(recorder.frames_dir)
        replay.get_frame()
        replay.get_frame()


def _validate_button_duration_shape(command_name: str, payload: object) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError(f"Command '{command_name}' payload must be a mapping")

    button_keys = [key for key in payload if BUTTON_KEY_RE.match(key)]
    duration_keys = [key for key in payload if BUTTON_DURATION_KEY_RE.match(key)]

    if len(button_keys) != 1 or len(duration_keys) != 1:
        raise RuntimeError(f"Command '{command_name}' must emit button_N + button_N_duration")

    button_key = button_keys[0]
    duration_key = duration_keys[0]

    if payload[button_key] != 1:
        raise RuntimeError(f"Command '{command_name}' must emit button_N:1 press for duration command")

    expected_duration_key = f"{button_key}_duration"
    if duration_key != expected_duration_key:
        raise RuntimeError(f"Command '{command_name}' button index does not match duration key")

    if int(payload[duration_key]) <= 0:
        raise RuntimeError(f"Command '{command_name}' duration must be positive")

    if len(payload) != 2:
        raise RuntimeError(f"Command '{command_name}' includes unsupported extra keys: {sorted(payload.keys())}")


def _require_yes(prompt: str) -> None:
    answer = input(f"{prompt} [y/n]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise RuntimeError(f"Live check failed: {prompt}")


if __name__ == "__main__":
    raise SystemExit(main())
