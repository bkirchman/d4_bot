from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import os
from pathlib import Path
from typing import Any


REQUIRED_HARDWARE_KEYS = (
    "capture.device_name",
    "capture.backend",
    "capture.width",
    "capture.height",
    "capture.fps",
    "capture.latency_frames",
    "controller.udp_ip",
    "controller.udp_port",
    "controller.response_port",
    "controller.response_mode",
    "active_season",
)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    framework_root = repo_root.parent / "bot_framework"

    if not framework_root.exists():
        raise RuntimeError(f"Expected sibling bot_framework repo at: {framework_root}")

    print("[phase0] fresh venv editable install checks")
    venv_python = _verify_fresh_venv_installs(repo_root, framework_root)

    framework_src = str(framework_root)
    game_src = str(repo_root / "src")
    if framework_src not in sys.path:
        sys.path.insert(0, framework_src)
    if game_src not in sys.path:
        sys.path.insert(0, game_src)

    print("[phase0] import contract checks")
    _verify_imports_for_phase_0(venv_python, framework_src, game_src, repo_root)

    print("[phase0] running FG-4 pytest")
    env = _build_pythonpath_env([framework_src, game_src])
    _run([
        venv_python,
        "-m",
        "pytest",
        "tests/test_config_loading.py",
        "-q",
    ], cwd=repo_root, env=env)

    print("[phase0] hardware config required-key check")
    _verify_missing_required_key_error(repo_root / "configs" / "hardware.yaml")

    print("[phase0] PASS")
    return 0


def _verify_fresh_venv_installs(repo_root: Path, framework_root: Path) -> str:
    temp_dir = Path(tempfile.mkdtemp(prefix="d4_phase0_verify_"))
    venv_dir = temp_dir / "venv"
    _run([sys.executable, "-m", "venv", str(venv_dir)], cwd=repo_root)
    venv_python = _venv_python(venv_dir)

    _run([venv_python, "-m", "pip", "install", "--upgrade", "pip"], cwd=repo_root)
    _run([venv_python, "-m", "pip", "install", "-e", "../bot_framework[ml]"], cwd=repo_root)
    _run([venv_python, "-m", "pip", "install", "-e", "."], cwd=repo_root)
    _run([venv_python, "-m", "pip", "install", "pytest"], cwd=repo_root)

    return venv_python


def _verify_imports_for_phase_0(
    python_exe: str,
    framework_src: str,
    game_src: str,
    repo_root: Path,
) -> None:
    env = _build_pythonpath_env([framework_src, game_src])
    _run(
        [
            python_exe,
            "-c",
            (
                "import framework.interfaces, framework.loop, framework.temporal, "
                "framework.contrib.hardware, framework.contrib.detection, "
                "framework.contrib.content_loops, framework.contrib.config"
            ),
        ],
        cwd=repo_root,
        env=env,
    )


def _verify_missing_required_key_error(hardware_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="d4_hw_verify_") as temp_dir:
        temp_hardware_path = Path(temp_dir) / "hardware.yaml"
        shutil.copyfile(hardware_path, temp_hardware_path)

        loaded = _load_layered_config(temp_hardware_path)
        capture_section = loaded.get("capture")
        if not isinstance(capture_section, dict):
            raise RuntimeError("Missing required key: capture")
        capture_section.pop("fps", None)

        _write_yaml(temp_hardware_path, loaded)

        try:
            _load_and_validate_hardware_config(temp_hardware_path)
        except ValueError as exc:
            message = str(exc)
            print(f"caught expected error: {message}")
            if "capture.fps" not in message:
                raise RuntimeError("Missing-key error did not name capture.fps") from exc
            return

        raise RuntimeError("Expected missing-key error but validation succeeded")


def _load_and_validate_hardware_config(path: Path) -> dict[str, Any]:
    data = _load_layered_config(path)
    for dotted_key in REQUIRED_HARDWARE_KEYS:
        _require_nested_key(data, dotted_key)
    return data


def _require_nested_key(data: dict[str, Any], dotted_key: str) -> None:
    current: Any = data
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            raise ValueError(f"Missing required key: {dotted_key}")
        current = current[key]


def _load_layered_config(path: Path) -> dict[str, Any]:
    from framework.contrib.config import load_layered_config

    return load_layered_config(path)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to write YAML config files") from exc

    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _venv_python(venv_dir: Path) -> str:
    if sys.platform.startswith("win"):
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


def _build_pythonpath_env(extra_paths: list[str]) -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    parts = [path for path in extra_paths if path]
    if current:
        parts.append(current)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(cmd)}")


if __name__ == "__main__":
    raise SystemExit(main())