from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from framework.contrib.ml import Detection

from d4_bot.recovery import RecoveryDirective, RecoveryLadder, StuckMonitor
from d4_bot.state import GameState


def _stuck_state(*, frame_id: int = 0, nav: bool = True, raw_moving: bool = False) -> GameState:
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
        character_moving=raw_moving,
        character_moving_frame_id=frame_id,
        character_moving_raw=raw_moving,
        nav_arrows=nav_arrows,
        nav_arrows_frame_id=nav_frame_id,
    )


def _make_config() -> dict[str, Any]:
    return {
        "stuck_window_ticks": 1,
        "stuck_quiet_fraction": 1.0,
        "stuck_event_budget": 6,
    }


def _make_monitor() -> StuckMonitor:
    return StuckMonitor(
        latency_frames=0,
        config=_make_config(),
        recovery_reverse_ticks=30,
        recovery_interact_press_count=6,
        recovery_interact_press_interval_ticks=5,
    )


def test_rung_one_is_reported_on_first_stuck_event_before_repositioning() -> None:
    monitor = _make_monitor()

    directive = monitor.update(_stuck_state(frame_id=0))

    assert isinstance(directive, RecoveryDirective)
    assert directive.rung == 1
    assert directive.command_name == "press_a"
    assert directive.parameters["stationary"] is True
    assert directive.parameters["press_count"] == 1
    assert directive.parameters["press_schedule_ticks"] == (0,)
    assert directive.terminal_status is None


def test_rung_two_reports_reverse_duration_and_press_schedule() -> None:
    monitor = _make_monitor()

    first = monitor.update(_stuck_state(frame_id=0))
    second = monitor.update(_stuck_state(frame_id=1))

    assert first is not None and first.rung == 1
    assert isinstance(second, RecoveryDirective)
    assert second.rung == 2
    assert second.command_name == "press_a"
    assert second.parameters["reverse_duration_ticks"] == 30
    assert second.parameters["press_count"] == 6
    assert second.parameters["press_interval_ticks"] == 5
    assert second.parameters["press_schedule_ticks"] == (0, 5, 10, 15, 20, 25)


def test_ladder_order_is_1_2_3_terminal_across_four_stuck_events() -> None:
    monitor = _make_monitor()

    directives = [monitor.update(_stuck_state(frame_id=i)) for i in range(4)]

    assert [directive.rung if directive is not None else None for directive in directives] == [1, 2, 3, 4]
    assert directives[-1] is not None
    assert directives[-1].terminal_status == "stuck_unrecoverable"


def test_movement_resets_the_ladder_back_to_rung_one() -> None:
    monitor = _make_monitor()

    assert monitor.update(_stuck_state(frame_id=0)) is not None
    assert monitor.update(_stuck_state(frame_id=1)) is not None
    monitor.update(_stuck_state(frame_id=2, raw_moving=True))
    directive = monitor.update(_stuck_state(frame_id=3))

    assert directive is not None
    assert directive.rung == 1


def test_ladder_validates_positive_constructor_values() -> None:
    with pytest.raises(ValueError):
        _ = RecoveryLadder(
            recovery_reverse_ticks=0,
            recovery_interact_press_count=6,
            recovery_interact_press_interval_ticks=5,
        )
