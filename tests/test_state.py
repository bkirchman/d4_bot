from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from framework.contrib.ml import Detection
from framework.interfaces import StampedFrame

from d4_bot.state import GameState, GameStateUpdater, StateDiff, diff


class _FakeMotionDetector:
    def __init__(self, values: list[bool]) -> None:
        self._values = list(values)
        self._index = 0

    def update(self, frame: StampedFrame) -> bool:
        if self._index >= len(self._values):
            return self._values[-1]
        value = self._values[self._index]
        self._index += 1
        return value


class _FakeNavDetector:
    def __init__(self, cadence: int) -> None:
        self._cadence = cadence
        self._last_result: list[Detection] = []
        self.last_inference_frame_id: int | None = None

    def update(self, frame: StampedFrame) -> list[Detection]:
        if frame.frame_id % self._cadence != 0:
            return list(self._last_result)

        if frame.frame_id == 2:
            self._last_result = [
                Detection(
                    class_name="nav_arrow",
                    confidence=0.95,
                    bbox=(100, 100, 20, 20),
                    frame_id=frame.frame_id,
                )
            ]
        else:
            self._last_result = []

        self.last_inference_frame_id = frame.frame_id
        return list(self._last_result)


class _SpyDetector:
    def __init__(self) -> None:
        self.calls = 0

    def update(self, frame: StampedFrame) -> bool:
        self.calls += 1
        return False


def _state(
    *,
    frame_id: int = 10,
    character_moving: bool = False,
    nav: bool = False,
    enemy_present: bool = False,
) -> GameState:
    nav_arrows = []
    nav_frame_id = None
    if nav:
        nav_arrows = [
            Detection(
                class_name="nav_arrow",
                confidence=0.9,
                bbox=(0, 0, 10, 10),
                frame_id=frame_id,
            )
        ]
        nav_frame_id = frame_id

    return GameState(
        frame_id=frame_id,
        timestamp=frame_id / 60.0,
        character_moving=character_moving,
        character_moving_frame_id=frame_id,
        nav_arrows=nav_arrows,
        nav_arrows_frame_id=nav_frame_id,
        enemy_present=enemy_present,
    )


def _frame(frame_id: int) -> StampedFrame:
    return StampedFrame(
        frame_id=frame_id,
        timestamp=frame_id / 60.0,
        frame=np.zeros((1080, 1920, 3), dtype=np.uint8),
    )


def test_gamestate_defaults_and_immutability() -> None:
    state = GameState(
        frame_id=42,
        timestamp=1.0,
        character_moving=False,
        character_moving_frame_id=42,
    )

    assert state.nav_arrows == []
    assert state.nav_arrows_frame_id is None
    assert state.enemy_present is False
    assert state.screen_mode == "hud"

    with pytest.raises(FrozenInstanceError):
        state.character_moving = True  # type: ignore[misc]


def test_staleness_math() -> None:
    state = GameState(
        frame_id=120,
        timestamp=2.0,
        character_moving=True,
        character_moving_frame_id=120,
    )

    assert state.staleness(120) == 0
    assert state.staleness(115) == 5


def test_diff_prev_none_is_all_false() -> None:
    current = _state(frame_id=5, character_moving=True, nav=True)

    assert diff(None, current) == StateDiff()


def test_diff_table_driven_edges() -> None:
    cases = [
        {
            "name": "movement started",
            "prev": _state(character_moving=False),
            "curr": _state(character_moving=True),
            "expected": StateDiff(movement_started=True),
        },
        {
            "name": "movement stopped",
            "prev": _state(character_moving=True),
            "curr": _state(character_moving=False),
            "expected": StateDiff(movement_stopped=True),
        },
        {
            "name": "nav guide appeared",
            "prev": _state(nav=False),
            "curr": _state(nav=True),
            "expected": StateDiff(nav_guide_appeared=True),
        },
        {
            "name": "nav guide lost",
            "prev": _state(nav=True),
            "curr": _state(nav=False),
            "expected": StateDiff(nav_guide_lost=True),
        },
        {
            "name": "enemy appeared",
            "prev": _state(enemy_present=False),
            "curr": _state(enemy_present=True),
            "expected": StateDiff(enemy_appeared=True),
        },
        {
            "name": "no edge",
            "prev": _state(character_moving=True, nav=True, enemy_present=True),
            "curr": _state(character_moving=True, nav=True, enemy_present=True),
            "expected": StateDiff(),
        },
    ]

    for case in cases:
        actual = diff(case["prev"], case["curr"])
        assert actual == case["expected"], case["name"]


def test_updater_assembles_snapshot_and_tracks_nav_origin() -> None:
    motion = _FakeMotionDetector([False, True, True])
    nav = _FakeNavDetector(cadence=2)
    updater = GameStateUpdater({"minimap_motion": motion, "nav_arrow": nav})

    state0 = updater.update(_frame(1))
    state1 = updater.update(_frame(2))
    state2 = updater.update(_frame(3))

    assert state0.character_moving is False
    assert state0.character_moving_frame_id == 1
    assert state0.nav_arrows == []
    assert state0.nav_arrows_frame_id is None

    assert state1.character_moving is True
    assert state1.character_moving_frame_id == 2
    assert len(state1.nav_arrows) == 1
    assert state1.nav_arrows[0].frame_id == 2
    assert state1.nav_arrows_frame_id == 2

    # Frame 3 is off-cadence; nav detections remain cached from frame 2.
    assert len(state2.nav_arrows) == 1
    assert state2.nav_arrows[0].frame_id == 2
    assert state2.nav_arrows_frame_id == 2


def test_updater_feeds_all_detectors_it_was_given() -> None:
    motion = _FakeMotionDetector([False])
    nav = _FakeNavDetector(cadence=1)
    spy = _SpyDetector()

    updater = GameStateUpdater(
        {
            "minimap_motion": motion,
            "nav_arrow": nav,
            "extra": spy,
        }
    )

    _ = updater.update(_frame(10))

    assert spy.calls == 1
