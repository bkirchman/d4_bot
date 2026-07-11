from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.recording import FrameRecorder

from d4_bot.capture import build_capture


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture-only dataset recorder using FrameRecorder")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "frames" / "walk_stand_01"),
        help="Dataset output directory",
    )
    parser.add_argument("--seconds", type=float, default=60.0, help="Recording duration in seconds")
    parser.add_argument("--every-n", type=int, default=1, help="Record every Nth frame")
    parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG quality for recorded frames")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--mode",
        choices=("record", "capture-only"),
        default="record",
        help="record writes frames/actions, capture-only skips recorder writes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    capture, first_frame = build_capture(args.config_dir)
    recorder: FrameRecorder | None = None
    initial_jpeg_count = 0
    if args.mode == "record":
        recorder = FrameRecorder(args.output_dir, every_n=args.every_n, jpeg_quality=args.jpeg_quality)
        initial_jpeg_count = len(list(recorder.frames_dir.glob("frame_*.jpg")))

    start = time.monotonic()
    ticks = 0
    capture_wait_seconds: list[float] = []
    record_seconds: list[float] = []

    try:
        # The first frame is pulled by build_capture for geometry assert/startup banner.
        # Diagnostic timing starts after startup using repeated get_frame calls.
        _ = first_frame

        while (time.monotonic() - start) < args.seconds:
            loop_tick_started_at = time.monotonic()

            capture_started_at = time.monotonic()
            frame = capture.get_frame()
            capture_wait_seconds.append(time.monotonic() - capture_started_at)

            record_started_at = time.monotonic()
            if recorder is not None:
                recorder.record(frame, None)
            record_seconds.append(time.monotonic() - record_started_at)

            ticks += 1

            # Keep loop_tick_started_at in scope to make it explicit that loop rate uses wall time.
            _ = loop_tick_started_at
    finally:
        if recorder is not None:
            recorder.close()
        capture.close()

    elapsed = time.monotonic() - start
    loop_rate_fps = _rate(ticks, elapsed)
    capture_arrival_fps = _capture_arrival_rate(capture_wait_seconds)
    capture_wait_mean_ms = _mean_ms(capture_wait_seconds)
    capture_wait_max_ms = _max_ms(capture_wait_seconds)
    record_mean_ms = _mean_ms(record_seconds)
    record_max_ms = _max_ms(record_seconds)

    jpeg_written = 0
    frames_dir: Path | None = None
    actions_path: Path | None = None
    if recorder is not None:
        frames_dir = recorder.frames_dir
        actions_path = recorder.actions_path
        final_jpeg_count = len(list(frames_dir.glob("frame_*.jpg")))
        jpeg_written = max(0, final_jpeg_count - initial_jpeg_count)

    print(f"mode={args.mode}")
    print(f"elapsed_s={elapsed:.2f}")
    print(f"ticks={ticks}")
    print(f"loop_rate_fps={loop_rate_fps:.2f}")
    print(f"capture_arrival_fps={capture_arrival_fps:.2f}")
    print(f"capture_get_frame_mean_ms={capture_wait_mean_ms:.2f}")
    print(f"capture_get_frame_max_ms={capture_wait_max_ms:.2f}")
    print(f"record_call_mean_ms={record_mean_ms:.2f}")
    print(f"record_call_max_ms={record_max_ms:.2f}")
    print(f"jpeg_files_written={jpeg_written}")
    print(f"ticks_to_jpeg_ratio={ticks}:{jpeg_written}")
    if frames_dir is not None and actions_path is not None:
        print(f"frames_dir={frames_dir}")
        print(f"actions={actions_path}")

    return 0


def _rate(count: int, elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return 0.0
    return count / elapsed_seconds


def _capture_arrival_rate(capture_wait_seconds: list[float]) -> float:
    total_capture_wait = sum(capture_wait_seconds)
    if total_capture_wait <= 0:
        return 0.0
    return len(capture_wait_seconds) / total_capture_wait


def _mean_ms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return (sum(samples) / len(samples)) * 1000.0


def _max_ms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return max(samples) * 1000.0


if __name__ == "__main__":
    raise SystemExit(main())
