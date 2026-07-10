from __future__ import annotations

from pathlib import Path

import yaml

from framework.contrib.config import load_layered_config


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_scalar_override(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overrides_path = tmp_path / "overrides.yaml"

    _write_yaml(base_path, {"capture": {"fps": 60.0}})
    _write_yaml(overrides_path, {"capture": {"fps": 30.0}})

    result = load_layered_config(base_path, overrides_path)

    assert result["capture"]["fps"] == 30.0


def test_nested_dict_merge(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overrides_path = tmp_path / "overrides.yaml"

    _write_yaml(
        base_path,
        {
            "capture": {"width": 1920, "height": 1080},
            "controller": {"udp_ip": "192.168.1.196", "udp_port": 5005},
        },
    )
    _write_yaml(overrides_path, {"controller": {"udp_port": 6000}})

    result = load_layered_config(base_path, overrides_path)

    assert result["capture"] == {"width": 1920, "height": 1080}
    assert result["controller"] == {"udp_ip": "192.168.1.196", "udp_port": 6000}


def test_list_replacement(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    overrides_path = tmp_path / "overrides.yaml"

    _write_yaml(base_path, {"values": [1, 2, 3]})
    _write_yaml(overrides_path, {"values": [9]})

    result = load_layered_config(base_path, overrides_path)

    assert result["values"] == [9]


def test_no_overrides_path_returns_base(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    _write_yaml(base_path, {"capture": {"fps": 60.0}})

    result = load_layered_config(base_path)

    assert result == {"capture": {"fps": 60.0}}