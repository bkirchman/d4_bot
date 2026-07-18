from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.interfaces import StampedFrame

from d4_bot.capture import load_hardware_config
from d4_bot.detectors import load_season_overrides
from d4_bot.detectors.minimap_pin import MinimapPinDetector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline minimap pin detector tuner")
    parser.add_argument("--recording-dir", required=True, help="Directory containing frame_*.jpg images")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--threshold-override",
        type=float,
        default=None,
        help="Override minimap_pin_match_threshold for this run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_dir = Path(args.config_dir)
    recording_dir = Path(args.recording_dir)

    detector = _build_detector(config_dir, args.threshold_override)

    frame_paths = sorted(recording_dir.glob("*.jpg"))
    if not frame_paths:
        raise RuntimeError(f"no .jpg frames found in {recording_dir}")

    visible_frame_ids: list[str] = []
    hidden_frame_ids: list[str] = []
    confidences: list[float] = []

    for frame_path in frame_paths:
        frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            raise RuntimeError(f"failed to load frame '{frame_path.name}'")

        frame_id = _frame_id_from_name(frame_path.name)
        stamped = StampedFrame(frame_id=frame_id, timestamp=frame_id / 60.0, frame=frame)
        result = detector.update(stamped)

        confidences.append(result.confidence)
        if result.pin_visible:
            visible_frame_ids.append(frame_path.stem)
        else:
            hidden_frame_ids.append(frame_path.stem)

        print(
            f"{frame_path.stem}: pin_visible={result.pin_visible} "
            f"confidence={result.confidence:.3f} position={result.pin_position}"
        )

    _print_summary(frame_paths, visible_frame_ids, hidden_frame_ids, confidences)
    return 0


def _build_detector(config_dir: Path, threshold_override: float | None) -> MinimapPinDetector:
    hardware = load_hardware_config(config_dir)
    season = str(hardware["active_season"])
    navigation_cfg = _load_navigation_config(config_dir, season)

    if threshold_override is not None:
        navigation_cfg["minimap_pin_match_threshold"] = float(threshold_override)

    template_path = Path(str(navigation_cfg["minimap_pin_template_path"]))
    if not template_path.is_absolute():
        template_path = config_dir / template_path

    return MinimapPinDetector(navigation_cfg, template_path)


def _load_navigation_config(config_dir: Path, season: str) -> dict[str, object]:
    base_path = config_dir / "navigation.yaml"
    loaded = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise RuntimeError(f"navigation config must be a mapping: {base_path}")

    season_overrides = load_season_overrides(config_dir, season)
    nav_override = season_overrides.get("navigation", {}) if isinstance(season_overrides, dict) else {}
    if isinstance(nav_override, dict):
        loaded = _merge_dicts(loaded, nav_override)

    if isinstance(loaded.get("navigation"), dict):
        loaded = dict(loaded["navigation"])

    return dict(loaded)


def _merge_dicts(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged: dict[str, object] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = value
    return merged


def _frame_id_from_name(filename: str) -> int:
    stem = Path(filename).stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    if not digits:
        raise RuntimeError(f"frame filename does not contain an id: {filename}")
    return int(digits)


def _print_summary(
    frame_paths: list[Path],
    visible_frame_ids: list[str],
    hidden_frame_ids: list[str],
    confidences: list[float],
) -> None:
    total_frames = len(frame_paths)
    visible_count = len(visible_frame_ids)
    hidden_count = len(hidden_frame_ids)
    min_confidence = min(confidences)
    max_confidence = max(confidences)
    mean_confidence = sum(confidences) / len(confidences)

    print("summary:")
    print(f"  total_frames={total_frames}")
    print(f"  pin_visible_true={visible_count}")
    print(f"  pin_visible_false={hidden_count}")
    print(f"  confidence_min={min_confidence:.3f}")
    print(f"  confidence_max={max_confidence:.3f}")
    print(f"  confidence_mean={mean_confidence:.3f}")
    print(f"  first_visible={visible_frame_ids[:5]}")
    print(f"  first_hidden={hidden_frame_ids[:5]}")


if __name__ == "__main__":
    raise SystemExit(main())