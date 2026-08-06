from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.content_loops import CommandRegistry

from d4_bot.processors.navigation import NavigationProcessor, NavigationState
from d4_bot.state import GameState, diff

from test_state import _frame, _state


class _SequenceUpdater:
    def __init__(self, states: list[GameState]) -> None:
        self._states = list(states)
        self._index = 0

    def update(self, _frame_obj: object) -> GameState:
        if self._index >= len(self._states):
            return self._states[-1]
        state = self._states[self._index]
        self._index += 1
        return state


class _FakeCapture:
    def __init__(self, fps: float) -> None:
        self.fps = fps


def _make_config() -> dict[str, Any]:
    return {
        "steering_command": "move_nav_burst",
        "stick_magnitude": 100,
        "character_anchor_x": 960,
        "character_anchor_y": 450,
        "search_grace_ticks": 3,
        "arrival_confirm_ticks": 4,
        "nav_arrow_only_arrival_backstop_ticks": 12,
        "recent_movement_window_ticks": 30,
        "emission_interval_ms": 100,
        "burst_duration_ms": 400,
        "significant_direction_change_degrees": 15.0,
        "stale_direction_tolerance_ticks": 1,
        "target_class_name": "nav_arrow",
    }


def _make_processor(states: list[GameState], config: dict[str, Any] | None = None) -> NavigationProcessor:
    commands = CommandRegistry()
    selected_config = _make_config() if config is None else dict(config)
    commands.register(
        selected_config["steering_command"],
        lambda: {
            "move_duration": selected_config["burst_duration_ms"],
        },
    )
    return NavigationProcessor(
        updater=_SequenceUpdater(states),
        state_differ=diff,
        commands=commands,
        latency_frames=0,
        config=selected_config,
    )


def _run_ticks(processor: NavigationProcessor, tick_count: int) -> None:
    services = {"capture": _FakeCapture(fps=60.0)}
    for frame_id in range(tick_count):
        _ = processor.process(_frame(frame_id), services)


def test_arrival_case1_both_present_100_ticks_not_terminal() -> None:
    cfg = _make_config()
    states = [_state(frame_id=i, nav=True, pin_visible=True) for i in range(100)]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, 100)

    assert processor.terminal_status is None
    assert processor.nav_state is NavigationState.STEERING
    assert processor.both_lost_ticks == 0


def test_arrival_case2_both_lost_arrival_confirm_minus_one_not_terminal() -> None:
    cfg = _make_config()
    states = [_state(frame_id=0, nav=True, pin_visible=True)] + [
        _state(frame_id=i + 1, nav=False, pin_visible=False)
        for i in range(cfg["arrival_confirm_ticks"] - 1)
    ]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, len(states))

    assert processor.terminal_status is None
    assert processor.nav_state is NavigationState.SEARCHING


def test_arrival_case3_both_lost_arrival_confirm_ticks_arrives_primary() -> None:
    cfg = _make_config()
    states = [_state(frame_id=0, nav=True, pin_visible=True)] + [
        _state(frame_id=i + 1, nav=False, pin_visible=False)
        for i in range(cfg["arrival_confirm_ticks"])
    ]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, len(states))

    assert processor.terminal_status == "arrived"
    assert processor.nav_state is NavigationState.ARRIVED
    assert processor.arrival_via_backstop is False


def test_arrival_case4_pin_returns_once_resets_compound_counter() -> None:
    cfg = _make_config()
    pre_reset_lost = [
        _state(frame_id=i + 1, nav=False, pin_visible=False)
        for i in range(cfg["arrival_confirm_ticks"] - 1)
    ]
    pin_return = [
        _state(
            frame_id=1 + (cfg["arrival_confirm_ticks"] - 1),
            nav=False,
            pin_visible=True,
            pin_position=(1700, 100),
        )
    ]
    post_reset_lost = [
        _state(
            frame_id=2 + (cfg["arrival_confirm_ticks"] - 1) + i,
            nav=False,
            pin_visible=False,
        )
        for i in range(cfg["arrival_confirm_ticks"] - 1)
    ]
    states = [_state(frame_id=0, nav=True, pin_visible=True)] + pre_reset_lost + pin_return + post_reset_lost
    processor = _make_processor(states, cfg)

    _run_ticks(processor, len(states))

    assert processor.terminal_status is None
    assert processor.nav_state is NavigationState.SEARCHING


def test_arrival_case5_nav_lost_pin_visible_backstop_ticks_arrives_backstop() -> None:
    cfg = _make_config()
    states = [_state(frame_id=0, nav=True, pin_visible=True)] + [
        _state(frame_id=i + 1, nav=False, pin_visible=True, pin_position=(1700, 100))
        for i in range(cfg["nav_arrow_only_arrival_backstop_ticks"])
    ]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, len(states))

    assert processor.terminal_status == "arrived"
    assert processor.nav_state is NavigationState.ARRIVED
    assert processor.arrival_via_backstop is True


def test_arrival_case6_nav_lost_pin_visible_backstop_minus_one_not_terminal() -> None:
    cfg = _make_config()
    states = [_state(frame_id=0, nav=True, pin_visible=True)] + [
        _state(frame_id=i + 1, nav=False, pin_visible=True, pin_position=(1700, 100))
        for i in range(cfg["nav_arrow_only_arrival_backstop_ticks"] - 1)
    ]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, len(states))

    assert processor.terminal_status is None
    assert processor.nav_state is NavigationState.SEARCHING


def test_arrival_case7_never_acquired_target_terminates_guide_lost() -> None:
    cfg = _make_config()
    tick_count = cfg["search_grace_ticks"] + 5
    states = [_state(frame_id=i, nav=False, pin_visible=False) for i in range(tick_count)]
    processor = _make_processor(states, cfg)

    _run_ticks(processor, tick_count)

    assert processor.terminal_status == "guide_lost"
    assert processor.nav_state is NavigationState.SEARCHING


def test_arrival_case8_backstop_not_greater_than_arrival_raises() -> None:
    cfg = _make_config()
    cfg["nav_arrow_only_arrival_backstop_ticks"] = cfg["arrival_confirm_ticks"]

    with pytest.raises(ValueError):
        _ = _make_processor([_state(frame_id=0, nav=True, pin_visible=True)], cfg)
