from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from d4_bot.capture import load_hardware_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 4a verification harness")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--record-dir",
        default=str(REPO_ROOT / "frames" / "diag_record_10s"),
        help="Recorded run directory containing actions.jsonl and frames/",
    )
    parser.add_argument("--offline-only", action="store_true", help="Run replay/offline checks only")
    return parser.parse_args()


@dataclass(frozen=True, slots=True)
class RecordedAction:
    frame_id: int
    payload: dict[str, Any]


def main() -> int:
    args = parse_args()

    print("[phase4a] replay: latency-discipline audit")
    _check_latency_discipline(Path(args.config_dir), Path(args.record_dir))

    if args.offline_only:
        print("[phase4a] offline checks PASS")
        return 0

    print("[phase4a] live checks")
    _require_yes("Open-ground run #1: follows guide and exits ARRIVED cleanly")
    _require_yes("Open-ground run #2: follows guide and exits ARRIVED cleanly")
    _require_yes("Open-ground run #3: follows guide and exits ARRIVED cleanly")
    _require_yes("Unpin-marker test: transitions to SEARCHING, waits grace period, and exits guide_lost cleanly")

    print("[phase4a] PASS")
    return 0


def _check_latency_discipline(config_dir: Path, record_dir: Path) -> None:
    actions_path = record_dir / "actions.jsonl"
    frames_dir = record_dir / "frames"

    if not actions_path.exists():
        raise RuntimeError(f"Missing recorded action log: {actions_path}")
    if not frames_dir.exists():
        raise RuntimeError(f"Missing recorded frames directory: {frames_dir}")

    hardware = load_hardware_config(config_dir)
    capture_cfg = hardware["capture"]
    fps = float(capture_cfg["fps"])
    latency_frames = int(capture_cfg["latency_frames"])

    steering_actions = _load_steering_actions(actions_path)
    if len(steering_actions) < 2:
        raise RuntimeError(
            "Need at least two steering actions in actions.jsonl for latency-discipline audit"
        )

    failures: list[str] = []
    for prev_action, next_action in zip(steering_actions, steering_actions[1:]):
        prev_duration_ms = int(prev_action.payload["move_duration"])
        min_gap = latency_frames + _duration_ms_to_ticks(prev_duration_ms, fps)
        observed_gap = next_action.frame_id - prev_action.frame_id

        if observed_gap < min_gap:
            failures.append(
                "gap violation: "
                f"prev_frame_id={prev_action.frame_id} next_frame_id={next_action.frame_id} "
                f"observed_gap={observed_gap} required_min_gap={min_gap}"
            )

    if failures:
        joined = "\n".join(failures)
        raise RuntimeError(f"Latency-discipline audit failed:\n{joined}")

    print(
        f"  steering_actions={len(steering_actions)} "
        f"latency_frames={latency_frames} fps={fps:.1f}"
    )


def _load_steering_actions(actions_path: Path) -> list[RecordedAction]:
    steering_actions: list[RecordedAction] = []

    for line_no, line in enumerate(actions_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue

        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON in actions log at line {line_no}") from exc

        frame_id = parsed.get("frame_id")
        action_payload = parsed.get("action")

        if not isinstance(frame_id, int):
            raise RuntimeError(f"actions.jsonl line {line_no} missing integer frame_id")

        if action_payload is None:
            continue
        if not isinstance(action_payload, dict):
            raise RuntimeError(f"actions.jsonl line {line_no} action payload must be a mapping or null")

        if "move_duration" not in action_payload:
            continue
        if "move_x" not in action_payload or "move_y" not in action_payload:
            continue

        steering_actions.append(RecordedAction(frame_id=frame_id, payload=dict(action_payload)))

    for prev, curr in zip(steering_actions, steering_actions[1:]):
        if curr.frame_id <= prev.frame_id:
            raise RuntimeError(
                "Steering action frame_ids must be strictly increasing: "
                f"{prev.frame_id} then {curr.frame_id}"
            )

    return steering_actions


def _duration_ms_to_ticks(duration_ms: int, fps: float) -> int:
    if duration_ms <= 0:
        raise RuntimeError(f"move_duration must be positive, got {duration_ms}")
    if fps <= 0:
        raise RuntimeError(f"fps must be positive, got {fps}")
    return max(1, int((duration_ms * fps + 999.0) // 1000.0))


def _require_yes(prompt: str) -> None:
    answer = input(f"{prompt} [y/n]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise RuntimeError(f"Live check failed: {prompt}")


if __name__ == "__main__":
    raise SystemExit(main())
