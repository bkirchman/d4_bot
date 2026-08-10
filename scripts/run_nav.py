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
from framework.interfaces import Action
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
    "nav_arrow_only_arrival_backstop_ticks",
    "stuck_window_ticks",
    "stuck_quiet_fraction",
    "stuck_event_budget",
    "emission_interval_ms",
    "burst_duration_ms",
    "significant_direction_change_degrees",
    "stale_direction_tolerance_ticks",
    "history_capacity",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4a navigation processor")
    parser.add_argument("--record", action="store_true", help="Record frames/actions to disk via FrameRecorder")
    parser.add_argument("--season", default=None, help="Season override folder name (defaults to hardware.yaml active_season)")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--verbose", action="store_true", help="Print throttled per-tick navigation diagnostics")
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
    nav_arrow_detector = detectors.get("nav_arrow")

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

    runtime_ticks = 0
    bursts_emitted = 0
    prev_nav_state = processor.nav_state
    last_frame_id = -1
    last_logged_skip_frame_id: int | None = None

    try:
        loop.start()
        while True:
            frame, action = loop.step()
            runtime_ticks += 1
            last_frame_id = frame.frame_id

            if action is not None and isinstance(action.payload, dict) and "move_duration" in action.payload:
                burst_payload = action.payload
                bursts_emitted += 1
                if args.verbose:
                    print(
                        f"[f={frame.frame_id}] BURST "
                        f"move_x={burst_payload['move_x']} "
                        f"move_y={burst_payload['move_y']} "
                        f"duration_ms={burst_payload['move_duration']} "
                        f"sig_change={'Y' if processor.last_emission_sig_change else 'N'} "
                        f"stale_reuse={'Y' if processor.last_emission_stale_reuse else 'N'}"
                    )

            if args.verbose:
                skip_frame_id = processor.last_skip_emission_frame_id
                skip_stale_ticks = processor.last_skip_emission_stale_ticks
                if (
                    skip_frame_id is not None
                    and skip_stale_ticks is not None
                    and skip_frame_id == frame.frame_id
                    and skip_frame_id != last_logged_skip_frame_id
                ):
                    print(f"[f={skip_frame_id}] SKIP_EMISSION stale_ticks={skip_stale_ticks}")
                    last_logged_skip_frame_id = skip_frame_id

            if args.verbose and processor.nav_state != prev_nav_state:
                print(f"[f={frame.frame_id}] transition: {prev_nav_state.name} -> {processor.nav_state.name}")
                prev_nav_state = processor.nav_state

            if args.verbose and (runtime_ticks % 30 == 0):
                nav_arrows_count = len(getattr(nav_arrow_detector, "last_result", []))
                latest_state = processor.latest_state
                pin_visible = bool(latest_state.pin_visible) if latest_state is not None else False
                nav_guide_lost_frame_id = processor.nav_guide_lost_frame_id
                frames_since_guide_lost = (
                    frame.frame_id - nav_guide_lost_frame_id + 1
                    if nav_guide_lost_frame_id is not None
                    else None
                )
                print(
                    f"[f={frame.frame_id}] "
                    f"state={processor.nav_state.name} "
                    f"nav_arrows={nav_arrows_count} "
                    f"pin_visible={pin_visible} "
                    f"both_lost={processor.both_lost_ticks} "
                    f"arrow_lost={processor.nav_arrow_lost_ticks} "
                    f"acquired={processor.target_acquired} "
                    f"last_sig_change_f={processor.last_significant_change_frame_id} "
                    f"stale_ticks={processor.stale_ticks_since_non_stale_detection} "
                    f"frames_since_guide_lost={frames_since_guide_lost} "
                    f"last_burst_frame_id={processor.last_burst_frame_id} "
                    f"bursts={bursts_emitted} "
                    f"terminal={processor.terminal_status}"
                )

            if recorder is not None:
                recorder.record(frame, _decorate_action_for_recording(action, processor))
            if processor.is_terminal:
                break
    finally:
        loop.stop()
        if recorder is not None:
            recorder.close()
        output.close()
        capture.close()

    terminal_frame_id = last_frame_id if last_frame_id >= 0 else runtime_ticks
    print(
        f"[f={terminal_frame_id}] TERMINAL "
        f"status={processor.terminal_status} "
        f"via_backstop={processor.arrival_via_backstop} "
        f"bursts_emitted={bursts_emitted} "
        f"runtime_ticks={runtime_ticks}"
    )
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


def _decorate_action_for_recording(action: Action | None, processor: NavigationProcessor) -> Action | None:
    if action is None:
        return None
    if not isinstance(action.payload, dict):
        return action
    if "move_duration" not in action.payload:
        return action

    payload = dict(action.payload)
    payload["__nav_sig_change"] = bool(processor.last_emission_sig_change)
    payload["__nav_stale_reuse"] = bool(processor.last_emission_stale_reuse)
    payload["__nav_stale_ticks"] = int(processor.stale_ticks_since_non_stale_detection)
    return Action(frame_id=action.frame_id, timestamp=action.timestamp, payload=payload)


if __name__ == "__main__":
    raise SystemExit(main())
