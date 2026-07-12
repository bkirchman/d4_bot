from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.config import load_layered_config
from framework.contrib.hardware import ReplayCapture
from framework.contrib.ml import YoloDetector

from d4_bot.capture import load_hardware_config
from d4_bot.detectors import build_detector_registry, build_detectors, load_rois, load_season_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 2 verification harness")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--replay-dir",
        default=str(REPO_ROOT / "frames" / "walk_stand_01" / "frames"),
        help="Replay frames directory",
    )
    parser.add_argument("--offline-only", action="store_true", help="Run replay/offline checks only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_dir = Path(args.config_dir)

    print("[phase2] replay: FG-1 YOLO cadence and detections")
    _check_fg1_replay(config_dir, Path(args.replay_dir))

    print("[phase2] replay: FG-2 ROI motion hysteresis")
    _check_fg2_replay(config_dir, Path(args.replay_dir))

    print("[phase2] replay: detector build and loud failures")
    _check_detector_build_errors(config_dir)

    print("[phase2] replay: season override smoke")
    _check_season_override_smoke(config_dir)

    if args.offline_only:
        print("[phase2] offline checks PASS")
        return 0

    print("[phase2] live checks")
    _require_yes("diag_detector_tuner.py --detector minimap_motion shows False while standing and True while walking")
    _require_yes("diag_detector_tuner.py --detector nav_arrow draws boxes on pinned nav guide")
    _require_yes("capture_icons.py captures a crop that immediately matches with TemplateMatchDetector")

    print("[phase2] PASS")
    return 0


def _check_fg1_replay(config_dir: Path, replay_dir: Path) -> None:
    rois = load_rois(config_dir / "rois.yaml")
    season = str(load_hardware_config(config_dir)["active_season"])
    season_overrides = load_season_overrides(config_dir, season)
    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)

    if "nav_arrow" not in detectors:
        raise RuntimeError("Missing shipped detector config: nav_arrow")
    nav_detector = detectors["nav_arrow"]
    if not isinstance(nav_detector, YoloDetector):
        raise RuntimeError("nav_arrow must construct as YoloDetector")

    replay = ReplayCapture(replay_dir, fps=60.0)

    frames = 0
    infer_calls = 0
    expected_calls = 0
    detections_present = 0
    detections_absent = 0
    last_inference_seen: int | None = None

    while True:
        try:
            frame = replay.get_frame()
        except IndexError:
            break

        frames += 1
        if frame.frame_id % 2 == 0:
            expected_calls += 1

        detections = nav_detector.update(frame)
        if detections:
            detections_present += 1
        else:
            detections_absent += 1

        if nav_detector.last_inference_frame_id != last_inference_seen:
            infer_calls += 1
            last_inference_seen = nav_detector.last_inference_frame_id

        for det in detections:
            if det.frame_id > frame.frame_id:
                raise RuntimeError("Detection.frame_id must not exceed current frame_id")
            if nav_detector.last_inference_frame_id is not None and det.frame_id != nav_detector.last_inference_frame_id:
                raise RuntimeError("Detection.frame_id must match origin inference frame")

    if frames == 0:
        raise RuntimeError("Replay dataset is empty")
    if detections_present == 0:
        raise RuntimeError("FG-1 replay check failed: no nav_arrow detections on replay")
    if detections_absent == 0:
        raise RuntimeError("FG-1 replay check failed: no nav_arrow-absent frames on replay")
    if infer_calls != expected_calls:
        raise RuntimeError(
            f"FG-1 cadence check failed: expected {expected_calls} inferences, observed {infer_calls}"
        )

    print(
        f"  frames={frames} inference_calls={infer_calls} "
        f"detected_frames={detections_present} empty_frames={detections_absent}"
    )


def _check_fg2_replay(config_dir: Path, replay_dir: Path) -> None:
    rois = load_rois(config_dir / "rois.yaml")
    season = str(load_hardware_config(config_dir)["active_season"])
    season_overrides = load_season_overrides(config_dir, season)
    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)

    if "minimap_motion" not in detectors:
        raise RuntimeError("Missing shipped detector config: minimap_motion")
    motion_detector = detectors["minimap_motion"]

    replay = ReplayCapture(replay_dir, fps=60.0)

    values: list[bool] = []
    transitions: list[int] = []

    while True:
        try:
            frame = replay.get_frame()
        except IndexError:
            break

        value = bool(motion_detector.update(frame))
        if values and values[-1] != value:
            transitions.append(frame.frame_id)
        values.append(value)

    if not values:
        raise RuntimeError("Replay dataset is empty")
    if not any(values):
        raise RuntimeError("FG-2 replay check failed: detector never entered moving=True")
    if all(values):
        raise RuntimeError("FG-2 replay check failed: detector never entered moving=False")

    hysteresis_ticks = int(getattr(motion_detector, "hysteresis_ticks"))
    run_lengths = _run_lengths(values)
    short_runs = [length for length in run_lengths[1:-1] if length < hysteresis_ticks]
    if short_runs:
        raise RuntimeError(f"FG-2 flicker check failed: found short runs {short_runs}")

    print(
        f"  frames={len(values)} transitions={len(transitions)} "
        f"hysteresis_ticks={hysteresis_ticks} min_run={min(run_lengths)}"
    )


def _check_detector_build_errors(config_dir: Path) -> None:
    rois = load_rois(config_dir / "rois.yaml")
    season = str(load_hardware_config(config_dir)["active_season"])
    season_overrides = load_season_overrides(config_dir, season)

    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)
    if set(detectors.keys()) != {"minimap_motion", "nav_arrow"}:
        raise RuntimeError(f"Expected shipped detectors minimap_motion/nav_arrow, found {sorted(detectors.keys())}")

    _ = build_detector_registry(config_dir / "detectors", rois, season_overrides)

    with tempfile.TemporaryDirectory(prefix="phase2_detectors_") as temp_dir:
        temp_path = Path(temp_dir)

        unknown_type = temp_path / "unknown_type.yaml"
        unknown_type.write_text("type: unknown\n", encoding="utf-8")
        try:
            build_detectors(temp_path, rois, {})
        except ValueError as exc:
            if str(unknown_type) not in str(exc):
                raise RuntimeError("Unknown detector type error must name offending file") from exc
        else:
            raise RuntimeError("Unknown detector type did not fail")

        bad_roi = temp_path / "bad_roi.yaml"
        bad_roi.write_text("type: roi_motion\nroi: does_not_exist\ndiff_threshold: 10\nchanged_fraction: 0.1\nhysteresis_ticks: 2\n", encoding="utf-8")
        try:
            build_detectors(temp_path, rois, {})
        except ValueError as exc:
            if str(bad_roi) not in str(exc):
                raise RuntimeError("Unknown ROI error must name offending file") from exc
        else:
            raise RuntimeError("Unknown ROI did not fail")


def _check_season_override_smoke(config_dir: Path) -> None:
    rois = load_rois(config_dir / "rois.yaml")

    with tempfile.TemporaryDirectory(prefix="phase2_overrides_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        overrides_path = temp_dir_path / "overrides.yaml"
        overrides_path.write_text(
            yaml.safe_dump({"detectors": {"nav_arrow": {"cadence": 5}}}, sort_keys=False),
            encoding="utf-8",
        )

        season_overrides = load_layered_config(overrides_path)
        detectors = build_detectors(config_dir / "detectors", rois, season_overrides)
        nav_detector = detectors["nav_arrow"]
        if not isinstance(nav_detector, YoloDetector):
            raise RuntimeError("nav_arrow must construct as YoloDetector")

        replay = ReplayCapture(config_dir.parent / "frames" / "walk_stand_01" / "frames", fps=60.0)
        observed_inference_ids: set[int] = set()

        for _ in range(30):
            frame = replay.get_frame()
            nav_detector.update(frame)
            if nav_detector.last_inference_frame_id is not None:
                observed_inference_ids.add(nav_detector.last_inference_frame_id)

        if not observed_inference_ids:
            raise RuntimeError("Season override cadence check had no inferences")

        max_mod = max(fid % 5 for fid in observed_inference_ids)
        if max_mod != 0:
            raise RuntimeError("Season override cadence was not applied to nav_arrow detector")

        print(f"  applied_override_frames={sorted(observed_inference_ids)[:5]}...")


def _run_lengths(values: list[bool]) -> list[int]:
    if not values:
        return []

    lengths: list[int] = []
    current = values[0]
    count = 1

    for value in values[1:]:
        if value == current:
            count += 1
        else:
            lengths.append(count)
            current = value
            count = 1

    lengths.append(count)
    return lengths


def _require_yes(prompt: str) -> None:
    answer = input(f"{prompt} [y/n]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise RuntimeError(f"Live check failed: {prompt}")


if __name__ == "__main__":
    raise SystemExit(main())
