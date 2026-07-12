from __future__ import annotations

import argparse
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

    if args.replay_dir:
        capture = ReplayCapture(args.replay_dir, fps=60.0)
        frame = capture.get_frame()
    else:
        capture, frame = build_capture(config_dir)

    try:
        while True:
            view = frame.frame.copy()
            text = _render_detector(view, detector, frame)
            cv2.imshow(args.window, view)
            print(text)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

            frame = capture.get_frame()
    except IndexError:
        pass
    finally:
        close = getattr(capture, "close", None)
        if callable(close):
            close()
        cv2.destroyAllWindows()

    return 0


def _render_detector(frame_view: object, detector: object, frame: object) -> str:
    if isinstance(detector, YoloDetector):
        detections = detector.update(frame)
        for det in detections:
            x, y, w, h = det.bbox
            cv2.rectangle(frame_view, (x, y), (x + w, y + h), (0, 255, 255), 2)
            label = f"{det.class_name} {det.confidence:.2f} src={det.frame_id}"
            cv2.putText(frame_view, label, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        return (
            f"frame={frame.frame_id} detections={len(detections)} "
            f"last_inference={detector.last_inference_frame_id}"
        )

    if hasattr(detector, "update"):
        value = bool(detector.update(frame))
        raw_motion = getattr(detector, "raw_motion", None)
        raw_str = "n/a" if raw_motion is None else str(bool(raw_motion))
        cv2.putText(
            frame_view,
            f"value={value} raw={raw_str}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2,
        )
        return f"frame={frame.frame_id} value={value} raw={raw_str}"

    value = bool(detector(frame.frame))
    cv2.putText(frame_view, f"value={value}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    return f"frame={frame.frame_id} value={value}"


if __name__ == "__main__":
    raise SystemExit(main())
