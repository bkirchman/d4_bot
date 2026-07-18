from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from d4_bot.detectors.minimap_pin import MinimapPinResult
from framework.contrib.ml import Detection
from framework.interfaces import StampedFrame


@dataclass(frozen=True, slots=True)
class GameState:
    frame_id: int
    timestamp: float
    character_moving: bool
    character_moving_frame_id: int
    nav_arrows: list[Detection] = field(default_factory=list)
    nav_arrows_frame_id: int | None = None
    pin_visible: bool = False
    pin_position: tuple[int, int] | None = None
    enemy_present: bool = False
    screen_mode: str = "hud"

    def staleness(self, field_frame_id: int) -> int:
        return self.frame_id - field_frame_id


@dataclass(frozen=True, slots=True)
class StateDiff:
    movement_started: bool = False
    movement_stopped: bool = False
    nav_guide_appeared: bool = False
    nav_guide_lost: bool = False
    enemy_appeared: bool = False


def diff(prev: GameState | None, curr: GameState) -> StateDiff:
    if prev is None:
        return StateDiff()

    prev_has_nav = bool(prev.nav_arrows)
    curr_has_nav = bool(curr.nav_arrows)

    return StateDiff(
        movement_started=(not prev.character_moving and curr.character_moving),
        movement_stopped=(prev.character_moving and not curr.character_moving),
        nav_guide_appeared=(not prev_has_nav and curr_has_nav),
        nav_guide_lost=(prev_has_nav and not curr_has_nav),
        enemy_appeared=(not prev.enemy_present and curr.enemy_present),
    )


class GameStateUpdater:
    def __init__(self, detectors: dict[str, object]) -> None:
        self._detectors = dict(detectors)

    def update(self, frame: StampedFrame) -> GameState:
        detector_results: dict[str, Any] = {}

        for name, detector in self._detectors.items():
            update_method = getattr(detector, "update", None)
            if callable(update_method):
                detector_results[name] = update_method(frame)
                continue

            if callable(detector):
                detector_results[name] = detector(frame)
                continue

            raise TypeError(f"Detector '{name}' is not callable and has no update(frame) method")

        character_moving = bool(detector_results.get("minimap_motion", False))

        nav_arrows_raw = detector_results.get("nav_arrow", [])
        if nav_arrows_raw is None:
            nav_arrows: list[Detection] = []
        else:
            nav_arrows = list(nav_arrows_raw)

        nav_arrows_frame_id: int | None = None
        nav_detector = self._detectors.get("nav_arrow")
        if nav_detector is not None:
            nav_arrows_frame_id = getattr(nav_detector, "last_inference_frame_id", None)
        if nav_arrows_frame_id is None and nav_arrows:
            nav_arrows_frame_id = nav_arrows[0].frame_id

        pin_result = detector_results.get("minimap_pin")
        if isinstance(pin_result, MinimapPinResult):
            pin_visible = pin_result.pin_visible
            pin_position = pin_result.pin_position
        else:
            pin_visible = False
            pin_position = None

        return GameState(
            frame_id=frame.frame_id,
            timestamp=frame.timestamp,
            character_moving=character_moving,
            character_moving_frame_id=frame.frame_id,
            nav_arrows=nav_arrows,
            nav_arrows_frame_id=nav_arrows_frame_id,
            pin_visible=pin_visible,
            pin_position=pin_position,
        )
