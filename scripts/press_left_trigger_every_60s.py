from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.hardware import UDPXboxOutput
from framework.interfaces import Action

from d4_bot.capture import build_output
from d4_bot.commands import build_command_registry, load_buttons_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Press left trigger every 60 seconds using the configured UDP Xbox output"
    )
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument(
        "--command",
        default="press_left_trigger",
        help="Command name from buttons.yaml used for the trigger press",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=60.0,
        help="Seconds to wait between trigger commands",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Optional number of trigger presses to send before exiting",
    )
    parser.add_argument("--debug-responses", action="store_true", help="Enable UDPXboxOutput debug response prints")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be greater than 0")
    if args.iterations is not None and args.iterations <= 0:
        raise SystemExit("--iterations must be greater than 0 when provided")

    buttons_config = load_buttons_config(Path(args.config_dir) / "buttons.yaml")
    registry = build_command_registry(buttons_config)

    try:
        trigger_factory = registry.get(args.command)
    except KeyError as exc:
        raise SystemExit(f"buttons registry is missing the '{args.command}' command") from exc

    output: UDPXboxOutput = build_output(args.config_dir, debug_mode=args.debug_responses)
    try:
        presses_sent = 0
        next_press_at = time.monotonic()

        while args.iterations is None or presses_sent < args.iterations:
            delay = next_press_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)

            timestamp = time.monotonic()
            action = Action(frame_id=0, timestamp=timestamp, payload=trigger_factory())
            output.execute(action)
            presses_sent += 1
            print(f"sent {args.command} #{presses_sent} at monotonic={timestamp:.3f}")
            next_press_at = timestamp + args.interval_seconds
    finally:
        output.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())