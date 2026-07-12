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
    parser = argparse.ArgumentParser(description="Capture ROI crops for seasonal template icons")
    parser.add_argument("--roi", required=True, help="ROI name from rois.yaml")
    parser.add_argument("--out", required=True, help="Output directory for captured icons")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--window", default="capture_icons", help="OpenCV window title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rois = _load_rois(Path(args.config_dir) / "rois.yaml")
    if args.roi not in rois:
        raise KeyError(f"Unknown ROI '{args.roi}' in rois.yaml")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    x, y, w, h = rois[args.roi]

    capture, frame = build_capture(args.config_dir)
    capture_index = 0

    try:
        while True:
            view = frame.frame.copy()
            cv2.rectangle(view, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(view, "press c to capture, q to quit", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow(args.window, view)

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("c"):
                crop = frame.frame[y : y + h, x : x + w]
                output_path = out_dir / f"{args.roi}_{capture_index:03d}.png"
                ok = cv2.imwrite(str(output_path), crop)
                if not ok:
                    raise RuntimeError(f"Failed to write icon crop: {output_path}")
                print(f"captured: {output_path}")
                capture_index += 1

            frame = capture.get_frame()
    finally:
        capture.close()
        cv2.destroyAllWindows()

    return 0


def _load_rois(path: Path) -> dict[str, tuple[int, int, int, int]]:
    if not path.exists():
        raise FileNotFoundError(f"rois config file not found: {path}")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"rois config root must be a mapping: {path}")

    rois: dict[str, tuple[int, int, int, int]] = {}
    for name, value in loaded.items():
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f"roi '{name}' must be [x, y, w, h]")
        rois[name] = tuple(int(v) for v in value)
    return rois


if __name__ == "__main__":
    raise SystemExit(main())
