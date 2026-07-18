from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from framework.contrib.config import load_layered_config
from framework.contrib.content_loops import DetectorRegistry
from framework.contrib.detection import ColorMatchDetector, RoiMotionDetector, TemplateMatchDetector
from framework.contrib.ml import YoloDetector

from .minimap_pin import MinimapPinDetector


SUPPORTED_DETECTOR_TYPES = ("yolo", "roi_motion", "color_match", "template_match")


def build_detectors(
    detector_dir: str | Path,
    rois: dict[str, tuple[int, int, int, int]],
    season_overrides: dict[str, Any],
) -> dict[str, object]:
    detector_path = Path(detector_dir)
    if not detector_path.exists():
        raise FileNotFoundError(f"detector directory not found: {detector_path}")

    config_dir = detector_path.parent
    detectors: dict[str, object] = {}
    for cfg_path in sorted(detector_path.glob("*.yaml")):
        cfg = _load_yaml_mapping(cfg_path)
        detector_name = cfg_path.stem

        override_cfg = _resolve_detector_override(season_overrides, detector_name)
        if override_cfg:
            cfg = _merge_dicts(cfg, override_cfg)

        detector_type = str(_require_key(cfg, "type", cfg_path))
        if detector_type not in SUPPORTED_DETECTOR_TYPES:
            raise ValueError(
                f"detector config '{cfg_path}' has unsupported type '{detector_type}'. "
                f"Supported types: {', '.join(SUPPORTED_DETECTOR_TYPES)}"
            )

        roi = _resolve_roi(cfg, rois, cfg_path)
        cadence = int(cfg.get("cadence", 1))

        if detector_type == "yolo":
            weights = _require_key(cfg, "weights", cfg_path)
            classes = _require_key(cfg, "classes", cfg_path)
            threshold = float(_require_key(cfg, "confidence_threshold", cfg_path))
            class_map = _load_class_map(Path(weights), Path(classes))
            detectors[detector_name] = YoloDetector(
                weights_path=Path(weights),
                class_map=class_map,
                confidence_threshold=threshold,
                cadence=cadence,
                roi=roi,
                device=str(cfg.get("device", "cuda")),
            )
            continue

        if detector_type == "roi_motion":
            detectors[detector_name] = RoiMotionDetector(
                roi=roi,
                diff_threshold=int(_require_key(cfg, "diff_threshold", cfg_path)),
                changed_fraction=float(_require_key(cfg, "changed_fraction", cfg_path)),
                hysteresis_ticks=int(_require_key(cfg, "hysteresis_ticks", cfg_path)),
            )
            continue

        if detector_type == "color_match":
            hue_range = tuple(int(v) for v in _require_key(cfg, "hue_range", cfg_path))
            detectors[detector_name] = ColorMatchDetector(
                hue_range=hue_range,
                saturation_min=int(_require_key(cfg, "saturation_min", cfg_path)),
                value_min=int(_require_key(cfg, "value_min", cfg_path)),
                pixel_threshold=int(_require_key(cfg, "pixel_threshold", cfg_path)),
                roi=roi,
            )
            continue

        if detector_type == "template_match":
            template_path = Path(str(_require_key(cfg, "template", cfg_path)))
            template = _load_template(template_path)
            detectors[detector_name] = TemplateMatchDetector(
                template=template,
                roi=_to_template_roi(roi),
                threshold=float(cfg.get("threshold", 0.95)),
            )
            continue

    minimap_pin_cfg = _load_navigation_config(config_dir, season_overrides)
    if minimap_pin_cfg is not None:
        detectors["minimap_pin"] = MinimapPinDetector(
            minimap_pin_cfg,
            _resolve_template_path(config_dir, minimap_pin_cfg),
        )

    return detectors


def build_detector_registry(
    detector_dir: str | Path,
    rois: dict[str, tuple[int, int, int, int]],
    season_overrides: dict[str, Any],
) -> DetectorRegistry:
    detectors = build_detectors(detector_dir, rois, season_overrides)
    registry = DetectorRegistry()

    for name, detector in detectors.items():
        if isinstance(detector, YoloDetector):
            registry.register(name, lambda frame, detector=detector: bool(detector.update(frame)))
        elif isinstance(detector, RoiMotionDetector):
            registry.register(name, detector.update)
        elif isinstance(detector, MinimapPinDetector):
            registry.register(name, lambda frame, detector=detector: detector.update(frame).pin_visible)
        elif hasattr(detector, "update") and callable(getattr(detector, "update")):
            registry.register(name, getattr(detector, "update"))
        else:
            registry.register(name, detector)  # type: ignore[arg-type]

    return registry


def load_rois(path: str | Path) -> dict[str, tuple[int, int, int, int]]:
    rois_cfg = _load_yaml_mapping(Path(path))
    rois: dict[str, tuple[int, int, int, int]] = {}
    for name, value in rois_cfg.items():
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f"ROI '{name}' in '{path}' must be [x, y, w, h]")
        rois[name] = tuple(int(v) for v in value)
    return rois


def load_season_overrides(config_dir: str | Path, season: str) -> dict[str, Any]:
    overrides_path = Path(config_dir) / "seasons" / season / "overrides.yaml"
    if not overrides_path.exists():
        return {}
    return load_layered_config(overrides_path)


def _resolve_detector_override(season_overrides: dict[str, Any], detector_name: str) -> dict[str, Any]:
    detectors_map = season_overrides.get("detectors", {})
    if isinstance(detectors_map, dict):
        detector_override = detectors_map.get(detector_name)
        if isinstance(detector_override, dict):
            return detector_override

    root_override = season_overrides.get(detector_name)
    if isinstance(root_override, dict):
        return root_override

    return {}


def _resolve_roi(
    cfg: dict[str, Any],
    rois: dict[str, tuple[int, int, int, int]],
    cfg_path: Path,
) -> tuple[int, int, int, int] | None:
    roi_name = cfg.get("roi")
    if roi_name is None:
        return None
    if not isinstance(roi_name, str):
        raise ValueError(f"detector config '{cfg_path}' has non-string roi value")
    if roi_name not in rois:
        raise ValueError(f"detector config '{cfg_path}' references unknown roi '{roi_name}'")
    return rois[roi_name]


def _to_template_roi(roi: tuple[int, int, int, int] | None) -> tuple[int, int, int, int] | None:
    if roi is None:
        return None
    x, y, w, h = roi
    return (x, y, x + w, y + h)


def _load_class_map(weights_path: Path, classes_path: Path) -> dict[int, str]:
    classes_cfg = _load_yaml_mapping(classes_path)
    names = classes_cfg.get("names")
    if not isinstance(names, dict):
        raise ValueError(f"classes file '{classes_path}' must contain a 'names' mapping")

    class_map: dict[int, str] = {}
    for key, value in names.items():
        class_map[int(key)] = str(value)

    if not weights_path.exists():
        raise FileNotFoundError(f"YOLO weights file not found: {weights_path}")

    return class_map


def _load_template(path: Path) -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("OpenCV is required for template detectors") from exc

    template = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if template is None or template.size == 0:
        raise ValueError(f"failed to load template image '{path}'")
    return template


def _load_navigation_config(config_dir: Path, season_overrides: dict[str, Any]) -> dict[str, Any] | None:
    config_path = config_dir / "navigation.yaml"
    if not config_path.exists():
        return None

    navigation_cfg = _load_yaml_mapping(config_path)
    nav_override = season_overrides.get("navigation", {})
    if isinstance(nav_override, dict):
        navigation_cfg = _merge_dicts(navigation_cfg, nav_override)

    if isinstance(navigation_cfg.get("navigation"), dict):
        navigation_cfg = dict(navigation_cfg["navigation"])

    required_keys = (
        "minimap_pin_template_path",
        "minimap_pin_search_roi_x1",
        "minimap_pin_search_roi_y1",
        "minimap_pin_search_roi_x2",
        "minimap_pin_search_roi_y2",
        "minimap_pin_match_threshold",
        "minimap_pin_detector_cadence",
    )
    for key in required_keys:
        _require_key(navigation_cfg, key, config_path)

    return navigation_cfg


def _resolve_template_path(config_dir: Path, minimap_pin_cfg: dict[str, Any]) -> Path:
    template_path = Path(
        str(_require_key(minimap_pin_cfg, "minimap_pin_template_path", config_dir / "navigation.yaml"))
    )
    if not template_path.is_absolute():
        template_path = config_dir / template_path
    return template_path


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"config root must be a mapping: {path}")
    return loaded


def _require_key(cfg: dict[str, Any], key: str, cfg_path: Path) -> Any:
    if key not in cfg:
        raise ValueError(f"config '{cfg_path}' missing required key '{key}'")
    return cfg[key]


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged