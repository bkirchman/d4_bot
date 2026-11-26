from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from framework.contrib.content_loops import CommandRegistry


REQUIRED_COMMAND_KEYS = ("type", "duration_ms")


def load_buttons_config(path: str | Path) -> dict[str, dict[str, Any]]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"buttons config file not found: {config_path}")

    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"buttons config root must be a mapping: {config_path}")

    typed: dict[str, dict[str, Any]] = {}
    for name, entry in loaded.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"buttons config has invalid command name: {name!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"buttons config command '{name}' must be a mapping")
        typed[name] = entry
    return typed


def build_command_registry(buttons_config: dict[str, dict[str, Any]]) -> CommandRegistry:
    registry = CommandRegistry()

    for command_name, command in buttons_config.items():
        _validate_required_keys(command_name, command)
        command_type = command["type"]

        if command_type == "button_duration":
            _validate_required_key(command_name, command, "index")
            index = int(command["index"])
            duration_ms = int(command["duration_ms"])

            payload = {
                f"button_{index}": 1,
                f"button_{index}_duration": duration_ms,
            }
            registry.register(command_name, _payload_factory(payload))
            continue

        if command_type == "hat_duration":
            _validate_required_key(command_name, command, "hat_x")
            _validate_required_key(command_name, command, "hat_y")
            payload = {
                "hat_x": int(command["hat_x"]),
                "hat_y": int(command["hat_y"]),
                "hat_duration": int(command["duration_ms"]),
            }
            registry.register(command_name, _payload_factory(payload))
            continue

        if command_type == "move_duration":
            _validate_required_key(command_name, command, "move_x")
            _validate_required_key(command_name, command, "move_y")
            payload = {
                "move_x": int(command["move_x"]),
                "move_y": int(command["move_y"]),
                "move_duration": int(command["duration_ms"]),
            }
            registry.register(command_name, _payload_factory(payload))
            continue

        if command_type == "trigger_duration":
            has_rt = "trigger" in command
            has_lt = "trigger_lt" in command
            if has_rt and has_lt:
                raise ValueError(
                    f"buttons config command '{command_name}' must define only one of 'trigger' or 'trigger_lt'"
                )
            if not has_rt and not has_lt:
                raise ValueError(
                    f"buttons config command '{command_name}' missing required key 'trigger' or 'trigger_lt'"
                )

            if has_rt:
                payload = {
                    "trigger": int(command["trigger"]),
                    "trigger_duration": int(command["duration_ms"]),
                }
            else:
                payload = {
                    "trigger_lt": int(command["trigger_lt"]),
                    "trigger_lt_duration": int(command["duration_ms"]),
                }
            registry.register(command_name, _payload_factory(payload))
            continue

        raise ValueError(
            f"buttons config command '{command_name}' has unsupported type '{command_type}'. "
            "Supported types: button_duration, hat_duration, move_duration, trigger_duration"
        )

    return registry


def _payload_factory(payload: dict[str, Any]) -> Callable[[], dict[str, Any]]:
    def _factory() -> dict[str, Any]:
        return dict(payload)

    return _factory


def _validate_required_keys(command_name: str, command: dict[str, Any]) -> None:
    for key in REQUIRED_COMMAND_KEYS:
        _validate_required_key(command_name, command, key)


def _validate_required_key(command_name: str, command: dict[str, Any], key: str) -> None:
    if key not in command:
        raise ValueError(f"buttons config command '{command_name}' missing required key '{key}'")
