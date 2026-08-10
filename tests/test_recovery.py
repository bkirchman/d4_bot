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

from d4_bot.recovery import RecoveryDirective, StuckMonitor
from d4_bot.state import GameState


WINDOW_TICKS = 90
QUIET_FRACTION = 0.5
BUDGET = 6
REVERSE_TICKS = 30
PRESS_COUNT = 6
PRESS_INTERVAL_TICKS = 5


def _make_config() -> dict[str, Any]:
    return {
        "stuck_window_ticks": WINDOW_TICKS,
        "stuck_quiet_fraction": QUIET_FRACTION,
        "stuck_event_budget": BUDGET,
    }


def _make_monitor() -> StuckMonitor:
    return StuckMonitor(
        latency_frames=0,
        config=_make_config(),
        recovery_reverse_ticks=REVERSE_TICKS,
        recovery_interact_press_count=PRESS_COUNT,
        recovery_interact_press_interval_ticks=PRESS_INTERVAL_TICKS,
    )


def _state(*, frame_id: int, raw_moving: bool, nav: bool = True) -> GameState:
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


def _feed_motion(
    monitor: StuckMonitor,
    readings: list[bool],
    *,
    nav: bool = True,
    pre_effect_elapsed: bool = True,
    start_frame_id: int = 0,
) -> list[RecoveryDirective | None]:
    outputs: list[RecoveryDirective | None] = []
    for offset, raw_moving in enumerate(readings):
        outputs.append(
            monitor.update(
                _state(frame_id=start_frame_id + offset, raw_moving=raw_moving, nav=nav),
                pre_effect_elapsed=pre_effect_elapsed,
            )
        )
    return outputs


def _last_directive(outputs: list[RecoveryDirective | None]) -> RecoveryDirective:
    directive = outputs[-1]
    assert directive is not None
    return directive


@pytest.mark.parametrize("reading_count", [1, 45, 89])
def test_partial_window_produces_no_verdict_at_several_fill_levels(reading_count: int) -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * reading_count)

    assert all(output is None for output in outputs)


def test_full_window_exactly_at_stuck_quiet_fraction_produces_stuck() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 45 + [True] * 45)

    directive = _last_directive(outputs)
    assert directive.rung == 1
    assert directive.command_name == "press_a"


def test_full_window_one_reading_below_stuck_quiet_fraction_produces_no_stuck() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 44 + [True] * 46)

    assert outputs[-1] is None


# ADR-023 regression case drawn from the 2026-08-06 rig measurement; a streak counter fails this.
def test_measured_wall_pattern_scattered_not_moving_produces_stuck() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False, False, True] * 30)

    directive = _last_directive(outputs)
    assert directive.rung == 1
    assert directive.command_name == "press_a"


def test_sustained_motion_under_1_percent_not_moving_never_produces_stuck() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [True] * 89 + [False] + [True] * 100)

    assert all(output is None for output in outputs)


def test_nav_arrows_absent_suppresses_verdict_despite_fully_quiet_window() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 90, nav=False)

    assert outputs[-1] is None


def test_pre_effect_false_suppresses_verdict() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 90, pre_effect_elapsed=False)

    assert outputs[-1] is None


def test_rung_one_is_reported_on_first_stuck_event() -> None:
    monitor = _make_monitor()

    directive = _last_directive(_feed_motion(monitor, [False] * 90))

    assert directive.rung == 1
    assert directive.command_name == "press_a"
    assert directive.parameters["stationary"] is True
    assert directive.parameters["press_count"] == 1
    assert directive.parameters["press_schedule_ticks"] == (0,)


def test_rung_two_reports_reverse_duration_and_press_schedule_with_matching_count() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 91)

    first = outputs[-2]
    second = _last_directive(outputs)

    assert first is not None and first.rung == 1
    assert second.rung == 2
    assert second.command_name == "press_a"
    assert second.parameters["reverse_duration_ticks"] == REVERSE_TICKS
    assert second.parameters["press_count"] == PRESS_COUNT
    assert second.parameters["press_interval_ticks"] == PRESS_INTERVAL_TICKS
    assert len(second.parameters["press_schedule_ticks"]) == PRESS_COUNT
    assert second.parameters["press_schedule_ticks"] == (0, 5, 10, 15, 20, 25)


def test_rung_index_cycles_1_2_3_1_2_across_five_stuck_events_without_terminating() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 94)
    directives = outputs[89:94]

    assert [directive.rung for directive in directives if directive is not None] == [1, 2, 3, 1, 2]
    assert all(directive is not None and directive.terminal_status is None for directive in directives)


def test_terminal_fires_on_sixth_stuck_event_with_budget_six_not_fourth() -> None:
    monitor = _make_monitor()

    outputs = _feed_motion(monitor, [False] * 96)
    directives = outputs[89:95]

    assert directives[3] is not None and directives[3].terminal_status is None
    assert directives[5] is not None
    assert directives[5].terminal_status == "stuck_unrecoverable"


def test_confirmed_movement_requires_full_window_before_resetting_rung_index() -> None:
    monitor = _make_monitor()

    first = _last_directive(_feed_motion(monitor, [False] * 90))
    _ = _feed_motion(monitor, [True] * 45, pre_effect_elapsed=False)
    partial_rung = monitor._ladder.current_rung
    _ = _feed_motion(monitor, [True] * 45, pre_effect_elapsed=False)
    reset_rung = monitor._ladder.current_rung

    assert first.rung == 1
    assert partial_rung != 1
    assert reset_rung == 1


def test_budget_does_not_reset_on_ladder_reset_with_interleaved_resets() -> None:
    monitor = _make_monitor()

    first = _last_directive(_feed_motion(monitor, [False] * 90))
    _ = _feed_motion(monitor, [True] * 90, pre_effect_elapsed=False)
    second = _last_directive(_feed_motion(monitor, [False] * 45))
    _ = _feed_motion(monitor, [True] * 90, pre_effect_elapsed=False)
    third = _last_directive(_feed_motion(monitor, [False] * 45))
    _ = _feed_motion(monitor, [True] * 90, pre_effect_elapsed=False)
    fourth = _last_directive(_feed_motion(monitor, [False] * 45))
    _ = _feed_motion(monitor, [True] * 90, pre_effect_elapsed=False)
    fifth = _last_directive(_feed_motion(monitor, [False] * 45))
    _ = _feed_motion(monitor, [True] * 90, pre_effect_elapsed=False)
    sixth = _last_directive(_feed_motion(monitor, [False] * 45))

    assert first.rung == 1
    assert second.rung == 1
    assert third.rung == 1
    assert fourth.rung == 1
    assert fifth.rung == 1
    assert sixth.terminal_status == "stuck_unrecoverable"
    assert monitor.stuck_event_count == 6


def test_terminal_is_sticky_once_terminal_further_updates_stay_terminal() -> None:
    monitor = _make_monitor()

    _ = _feed_motion(monitor, [False] * 96)
    outputs = _feed_motion(monitor, [False, True, False])

    assert all(output is not None and output.terminal_status == "stuck_unrecoverable" for output in outputs)
