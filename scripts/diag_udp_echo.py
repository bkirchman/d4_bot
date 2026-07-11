from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.interfaces import Action

from d4_bot.capture import build_output
from d4_bot.commands import build_command_registry, load_buttons_config

BUTTON_KEY_RE = re.compile(r"^button_(\d+)$")
BUTTON_DURATION_KEY_RE = re.compile(r"^button_(\d+)_duration$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send one named buttons.yaml command over UDP and print payload")
    parser.add_argument("--command", required=True, help="Command name from configs/buttons.yaml")
    parser.add_argument("--config-dir", default=str(REPO_ROOT / "configs"), help="Path to config directory")
    parser.add_argument("--debug-responses", action="store_true", help="Enable UDPXboxOutput debug response prints")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    buttons_config = load_buttons_config(Path(args.config_dir) / "buttons.yaml")
    registry = build_command_registry(buttons_config)

    try:
        payload = registry.get(args.command)()
    except KeyError as exc:
        raise SystemExit(f"Unknown command '{args.command}' in buttons registry") from exc

    _validate_protocol_shape(payload)
    print(json.dumps(payload, separators=(",", ":")))

    output = build_output(args.config_dir, debug_mode=args.debug_responses)
    try:
        action = Action(frame_id=0, timestamp=time.monotonic(), payload=payload)
        output.execute(action)
    finally:
        output.close()

    return 0


def _validate_protocol_shape(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise SystemExit("Invalid payload: registry entry must return one mapping payload")

    button_keys = [key for key in payload if BUTTON_KEY_RE.match(key)]
    duration_keys = [key for key in payload if BUTTON_DURATION_KEY_RE.match(key)]

    if len(button_keys) == 1 and len(duration_keys) == 1:
        button_key = button_keys[0]
        duration_key = duration_keys[0]

        if payload[button_key] != 1:
            raise SystemExit("Invalid payload: button_N_duration shape requires button_N:1 press")

        expected_duration_key = f"{button_key}_duration"
        if duration_key != expected_duration_key:
            raise SystemExit("Invalid payload: button_N and button_N_duration index mismatch")

        if int(payload[duration_key]) <= 0:
            raise SystemExit("Invalid payload: button_N_duration must be a positive integer")

        if len(payload) != 2:
            raise SystemExit("Invalid payload: unexpected extra keys for button_N_duration command")

        return

    raise SystemExit(
        "Invalid payload: only single-packet self-releasing protocol shapes are allowed here; "
        "expected button_N + button_N_duration"
    )


if __name__ == "__main__":
    raise SystemExit(main())
