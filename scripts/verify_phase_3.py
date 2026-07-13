from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.hardware import ReplayCapture

from d4_bot.capture import load_hardware_config
from d4_bot.detectors import build_detectors, load_rois, load_season_overrides
from d4_bot.state import GameStateUpdater, diff


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 3 verification harness")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--replay-dir",
        default=str(REPO_ROOT / "frames" / "walk_stand_01" / "frames"),
        help="Replay frames directory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("[phase3] replay: pytest suite")
    _run([sys.executable, "-m", "pytest", "tests/test_state.py", "-q"], cwd=REPO_ROOT)

    print("[phase3] replay: GameStateUpdater edges and staleness")
    _check_replay(Path(args.config_dir), Path(args.replay_dir))

    print("[phase3] PASS")
    return 0


def _check_replay(config_dir: Path, replay_dir: Path) -> None:
    rois = load_rois(config_dir / "rois.yaml")
    season = str(load_hardware_config(config_dir)["active_season"])
    season_overrides = load_season_overrides(config_dir, season)
    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)

    updater = GameStateUpdater(detectors)
    replay = ReplayCapture(replay_dir, fps=60.0)

    nav_detector = detectors.get("nav_arrow")
    if nav_detector is None:
        raise RuntimeError("Missing shipped detector config: nav_arrow")

    nav_cadence = int(getattr(nav_detector, "_cadence", 1))

    prev_state = None
    movement_started_frames: list[int] = []
    movement_stopped_frames: list[int] = []
    nav_appeared_frames: list[int] = []

    snapshots = 0
    while True:
        try:
            frame = replay.get_frame()
        except IndexError:
            break

        curr_state = updater.update(frame)
        snapshot_diff = diff(prev_state, curr_state)

        if snapshot_diff.movement_started:
            movement_started_frames.append(curr_state.frame_id)
        if snapshot_diff.movement_stopped:
            movement_stopped_frames.append(curr_state.frame_id)
        if snapshot_diff.nav_guide_appeared:
            nav_appeared_frames.append(curr_state.frame_id)

        if curr_state.nav_arrows_frame_id is not None:
            if curr_state.staleness(curr_state.nav_arrows_frame_id) > nav_cadence:
                raise RuntimeError(
                    "nav_arrows staleness exceeded configured cadence: "
                    f"frame_id={curr_state.frame_id} nav_arrows_frame_id={curr_state.nav_arrows_frame_id} "
                    f"cadence={nav_cadence}"
                )

        prev_state = curr_state
        snapshots += 1

    if snapshots == 0:
        raise RuntimeError("Replay dataset is empty")
    if not movement_started_frames:
        raise RuntimeError("Expected at least one movement_started edge on replay")
    if not movement_stopped_frames:
        raise RuntimeError("Expected at least one movement_stopped edge on replay")
    if not nav_appeared_frames:
        raise RuntimeError("Expected at least one nav_guide_appeared edge on replay")

    print(
        f"  snapshots={snapshots} "
        f"movement_started={movement_started_frames} "
        f"movement_stopped={movement_stopped_frames} "
        f"nav_guide_appeared={nav_appeared_frames} "
        f"nav_cadence={nav_cadence}"
    )


def _run(cmd: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


if __name__ == "__main__":
    raise SystemExit(main())
