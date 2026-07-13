from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.config import load_layered_config
from framework.contrib.recording import FrameRecorder
from framework.loop import BotLoop
from framework.temporal import FrameHistory

from d4_bot.capture import build_capture, build_output, load_hardware_config
from d4_bot.commands import build_command_registry, load_buttons_config
from d4_bot.detectors import build_detectors, load_rois, load_season_overrides
from d4_bot.processors.navigation import NavigationProcessor
from d4_bot.state import GameStateUpdater, diff


REQUIRED_NAV_CONFIG_KEYS = (
    "steering_command",
    "stick_magnitude",
    "search_grace_ticks",
    "arrival_confirm_ticks",
    "recent_movement_window_ticks",
    "history_capacity",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4a navigation processor")
    parser.add_argument("--record", action="store_true", help="Record frames/actions to disk via FrameRecorder")
    parser.add_argument("--season", default=None, help="Season override folder name (defaults to hardware.yaml active_season)")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_dir = Path(args.config_dir)

    hardware = load_hardware_config(config_dir)
    season = args.season or str(hardware["active_season"])

    navigation_config = load_navigation_config(config_dir=config_dir, season=season)
    _validate_required_navigation_keys(navigation_config)

    buttons = load_buttons_config(config_dir / "buttons.yaml")
    commands = build_command_registry(buttons)

    rois = load_rois(config_dir / "rois.yaml")
    season_overrides = load_season_overrides(config_dir, season)
    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)
    updater = GameStateUpdater(detectors)

    capture, first_frame = build_capture(config_dir)
    output = build_output(config_dir)

    history = FrameHistory(capacity=int(navigation_config["history_capacity"]))
    processor = NavigationProcessor(
        updater=updater,
        state_differ=diff,
        commands=commands,
        latency_frames=capture.latency_frames,
        config=navigation_config,
    )

    loop = BotLoop(capture=capture, output=output, processor=processor, history=history)

    recorder = _build_recorder_if_enabled(args.record, navigation_config)
    print(f"run_nav: latency_frames={capture.latency_frames} season={season} record={bool(recorder)}")
    _ = first_frame

    try:
        loop.start()
        while True:
            frame, action = loop.step()
            if recorder is not None:
                recorder.record(frame, action)
            if processor.is_terminal:
                break
    finally:
        loop.stop()
        if recorder is not None:
            recorder.close()
        output.close()
        capture.close()

    print(f"run_nav terminal_status={processor.terminal_status} nav_state={processor.nav_state.value}")
    return 0


def load_navigation_config(config_dir: Path, season: str) -> dict[str, Any]:
    base_path = config_dir / "navigation.yaml"
    overrides_path = config_dir / "seasons" / season / "overrides.yaml"

    if overrides_path.exists():
        merged = load_layered_config(base_path, overrides_path)
    else:
        merged = load_layered_config(base_path)

    if isinstance(merged.get("navigation"), dict):
        return dict(merged["navigation"])

    return dict(merged)


def _build_recorder_if_enabled(enabled: bool, navigation_config: dict[str, Any]) -> FrameRecorder | None:
    if not enabled:
        return None

    output_dir = Path(str(navigation_config.get("record_output_dir", REPO_ROOT / "frames" / "nav_run")))
    every_n = navigation_config.get("record_every_n")
    jpeg_quality = navigation_config.get("record_jpeg_quality")

    kwargs: dict[str, Any] = {}
    if every_n is not None:
        kwargs["every_n"] = int(every_n)
    if jpeg_quality is not None:
        kwargs["jpeg_quality"] = int(jpeg_quality)

    recorder = FrameRecorder(output_dir=output_dir, **kwargs)
    print(f"recording enabled: output_dir={output_dir}")
    return recorder


def _validate_required_navigation_keys(config: dict[str, Any]) -> None:
    for key in REQUIRED_NAV_CONFIG_KEYS:
        if key not in config:
            raise ValueError(f"navigation config missing required key '{key}'")


if __name__ == "__main__":
    raise SystemExit(main())
