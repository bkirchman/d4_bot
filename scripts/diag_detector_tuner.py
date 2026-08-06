from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.hardware import ReplayCapture
from framework.contrib.ml import YoloDetector

from d4_bot.capture import build_capture, load_hardware_config
from d4_bot.detectors import build_detectors, load_rois, load_season_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display detector outputs for live tuning")
    parser.add_argument("--detector", required=True, help="Detector config name (without .yaml)")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--season", default=None, help="Season override folder, e.g. s09")
    parser.add_argument("--replay-dir", default=None, help="Replay frames directory for offline display")
    parser.add_argument("--window", default="diag_detector_tuner", help="OpenCV window title")
    parser.add_argument(
        "--log",
        default=str(REPO_ROOT / "logs" / "diag_detector_tuner.jsonl"),
        help="JSONL session log path; use '-' or 'none' to disable",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    config_dir = Path(args.config_dir)
    hardware = load_hardware_config(config_dir)
    season = args.season or str(hardware["active_season"])

    rois = load_rois(config_dir / "rois.yaml")
    season_overrides = load_season_overrides(config_dir, season)
    detectors = build_detectors(config_dir / "detectors", rois, season_overrides)

    if args.detector not in detectors:
        raise KeyError(f"Unknown detector '{args.detector}'")

    detector = detectors[args.detector]
    initial_threshold = _get_active_threshold(detector)
    active_threshold = initial_threshold
    log_fp = _open_log_file(args.log)

    if args.replay_dir:
        capture = ReplayCapture(args.replay_dir, fps=60.0)
        frame = capture.get_frame()
    else:
        capture, frame = build_capture(config_dir)

    try:
        while True:
            view = frame.frame.copy()
            text, log_row = _render_detector(view, detector, frame)
            cv2.imshow(args.window, view)
            print(text)
            if log_fp is not None:
                log_fp.write(json.dumps(log_row) + "\n")
                log_fp.flush()

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

            if active_threshold is not None and initial_threshold is not None:
                if key == ord("]"):
                    _set_active_threshold(detector, active_threshold + 0.001)
                    active_threshold = _get_active_threshold(detector)
                elif key == ord("["):
                    _set_active_threshold(detector, active_threshold - 0.001)
                    active_threshold = _get_active_threshold(detector)
                elif key == ord("r"):
                    _set_active_threshold(detector, initial_threshold)
                    active_threshold = _get_active_threshold(detector)

            frame = capture.get_frame()
    except IndexError:
        pass
    finally:
        if log_fp is not None:
            log_fp.close()
        close = getattr(capture, "close", None)
        if callable(close):
            close()
        cv2.destroyAllWindows()

    return 0


def _render_detector(frame_view: object, detector: object, frame: object) -> tuple[str, dict[str, object]]:
    if isinstance(detector, YoloDetector):
        detections = detector.update(frame)
        for det in detections:
            x, y, w, h = det.bbox
            cv2.rectangle(frame_view, (x, y), (x + w, y + h), (0, 255, 255), 2)
            label = f"{det.class_name} {det.confidence:.2f} src={det.frame_id}"
            cv2.putText(frame_view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        text = (
            f"frame={frame.frame_id} detections={len(detections)} "
            f"last_inference={detector.last_inference_frame_id}"
        )
        return text, {
            "frame_id": frame.frame_id,
            "fraction": None,
            "raw": None,
            "value": None,
            "threshold": None,
        }

    if hasattr(detector, "update"):
        value = bool(detector.update(frame))
        raw_motion = getattr(detector, "raw_motion", None)
        raw_str = "n/a" if raw_motion is None else str(bool(raw_motion))
        fraction = getattr(detector, "last_changed_fraction", None)
        threshold = _get_active_threshold(detector)

        if fraction is not None and threshold is not None:
            display = f"value={value} raw={raw_str} frac={float(fraction):.4f} thr={float(threshold):.4f}"
            text = (
                f"frame={frame.frame_id} value={value} raw={raw_str} "
                f"frac={float(fraction):.4f} thr={float(threshold):.4f}"
            )
        else:
            display = f"value={value} raw={raw_str}"
            text = f"frame={frame.frame_id} value={value} raw={raw_str}"

        cv2.putText(
            frame_view,
            display,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2,
        )
        return text, {
            "frame_id": frame.frame_id,
            "fraction": None if fraction is None else float(fraction),
            "raw": None if raw_motion is None else bool(raw_motion),
            "value": value,
            "threshold": None if threshold is None else float(threshold),
        }

    value = bool(detector(frame.frame))
    cv2.putText(frame_view, f"value={value}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    return f"frame={frame.frame_id} value={value}", {
        "frame_id": frame.frame_id,
        "fraction": None,
        "raw": None,
        "value": value,
        "threshold": None,
    }


def _get_active_threshold(detector: object) -> float | None:
    value = getattr(detector, "changed_fraction", None)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _set_active_threshold(detector: object, value: float) -> None:
    clamped = max(0.0, min(1.0, float(value)))
    setattr(detector, "changed_fraction", clamped)


def _open_log_file(log_arg: str):
    normalized = log_arg.strip().lower()
    if normalized in {"", "-", "none", "off", "false", "0"}:
        return None
    log_path = Path(log_arg)
    if not log_path.is_absolute():
        log_path = REPO_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path.open("w", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
