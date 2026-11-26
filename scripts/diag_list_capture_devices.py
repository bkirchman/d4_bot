from __future__ import annotations

import argparse
from pathlib import Path

from framework.contrib.config import load_layered_config
from framework.contrib.hardware import list_capture_devices


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="List DirectShow capture devices and the configured match")
    parser.add_argument("--config-dir", type=Path, default=REPO_ROOT / "configs")
    args = parser.parse_args()

    hardware_path = args.config_dir / "hardware.yaml"
    device_name: str | None = None
    if hardware_path.exists():
        config = load_layered_config(hardware_path)
        capture = config.get("capture")
        if not isinstance(capture, dict) or not isinstance(capture.get("device_name"), str):
            raise ValueError("hardware config missing capture.device_name")
        device_name = capture["device_name"]
        if not device_name.strip():
            raise ValueError("hardware config capture.device_name must not be empty")

    devices = list_capture_devices("dshow")
    matches = [
        device for device in devices
        if device_name is not None and device_name.casefold() in device.name.casefold()
    ]
    for device in devices:
        marker = " [configured match]" if len(matches) == 1 and device == matches[0] else ""
        print(f"index={device.index} name={device.name!r} path={device.path!r}{marker}")

    if device_name is not None:
        print(f"device_name={device_name!r}: {len(matches)} matches")
        return 0 if len(matches) == 1 else 1
    print(f"No hardware.yaml at {hardware_path}; no configured device selected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
