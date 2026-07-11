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

from d4_bot.capture import build_capture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Overlay all configured ROIs on live capture")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--window", default="diag_roi_viewer", help="OpenCV window title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rois = _load_rois(Path(args.config_dir) / "rois.yaml")

    capture, first_frame = build_capture(args.config_dir)
    try:
        frame = first_frame
        while True:
            view = frame.frame.copy()
            _draw_rois(view, rois)
            cv2.imshow(args.window, view)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

            frame = capture.get_frame()
    finally:
        capture.close()
        cv2.destroyAllWindows()

    return 0


def _load_rois(path: Path) -> dict[str, list[int]]:
    if not path.exists():
        raise FileNotFoundError(f"rois config file not found: {path}")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"rois config root must be a mapping: {path}")

    rois: dict[str, list[int]] = {}
    for name, value in loaded.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"rois config has invalid name: {name!r}")
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f"roi '{name}' must be [x, y, w, h]")
        rois[name] = [int(v) for v in value]
    return rois


def _draw_rois(frame: object, rois: dict[str, list[int]]) -> None:
    for name, (x, y, w, h) in rois.items():
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(frame, name, (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


if __name__ == "__main__":
    raise SystemExit(main())
