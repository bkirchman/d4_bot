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

from d4_bot.recovery import RecoveryDirective
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
        "stuck_window_ticks": 90,
        "stuck_quiet_fraction": 0.5,
        "stuck_event_budget": 6,
        "recovery_reverse_ticks": 30,
        "recovery_interact_press_count": 6,
        "recovery_interact_press_interval_ticks": 5,
        "recovery_reapproach_offset_degrees": 45,
        "recovery_reapproach_ticks": 30,
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
    commands.register("press_a", lambda: {"button_1": 1, "button_1_duration": 80})
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


def _run_ticks_collect_actions(processor: NavigationProcessor, tick_count: int) -> list[Action]:
    from framework.interfaces import Action

    actions: list[Action] = []
    services = {"capture": _FakeCapture(fps=60.0)}
    for frame_id in range(tick_count):
        action = processor.process(_frame(frame_id), services)
        if action is not None:
            actions.append(action)
    return actions


def _state_with_raw(
    *,
    frame_id: int,
    nav: bool,
    pin_visible: bool,
    raw_moving: bool,
) -> GameState:
    nav_arrows = []
    nav_frame_id = None
    if nav:
        from framework.contrib.ml import Detection

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
        pin_visible=pin_visible,
        pin_position=(1700, 100) if pin_visible else None,
    )


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


def test_recovery_config_keys_validate_and_schedule_must_fit_reverse_duration() -> None:
    cfg = _make_config()

    invalid_offset = dict(cfg)
    invalid_offset["recovery_reapproach_offset_degrees"] = 90
    with pytest.raises(ValueError):
        _ = _make_processor([_state(frame_id=0, nav=True, pin_visible=True)], invalid_offset)

    invalid_ticks = dict(cfg)
    invalid_ticks["recovery_reapproach_ticks"] = 0
    with pytest.raises(ValueError):
        _ = _make_processor([_state(frame_id=0, nav=True, pin_visible=True)], invalid_ticks)

    invalid_schedule = dict(cfg)
    invalid_schedule["recovery_reverse_ticks"] = 20
    invalid_schedule["recovery_interact_press_count"] = 6
    invalid_schedule["recovery_interact_press_interval_ticks"] = 5
    with pytest.raises(ValueError) as exc:
        _ = _make_processor([_state(frame_id=0, nav=True, pin_visible=True)], invalid_schedule)
    assert "recovery_interact_press_count" in str(exc.value)
    assert "recovery_reverse_ticks" in str(exc.value)


def test_verdict_ordering_arrival_outranks_stuck() -> None:
    cfg = _make_config()
    states = [_state_with_raw(frame_id=0, nav=True, pin_visible=True, raw_moving=False)] + [
        _state_with_raw(frame_id=i + 1, nav=False, pin_visible=False, raw_moving=False)
        for i in range(cfg["arrival_confirm_ticks"])
    ]
    processor = _make_processor(states, cfg)

    call_count = 0

    def _fake_update(state: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        nonlocal call_count
        call_count += 1
        if state.frame_id == cfg["arrival_confirm_ticks"]:
            return RecoveryDirective(rung=1, command_name="press_a", parameters={"press_schedule_ticks": (0,)})
        return None

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    actions = _run_ticks_collect_actions(processor, len(states))

    assert processor.terminal_status == "arrived"
    assert processor.nav_state is NavigationState.ARRIVED
    assert call_count == len(states) - 1
    assert all("button_1" not in action.payload for action in actions)


def test_stuck_remains_live_during_backstop_window() -> None:
    cfg = _make_config()
    states = [
        _state_with_raw(frame_id=0, nav=True, pin_visible=True, raw_moving=False),
        _state_with_raw(frame_id=1, nav=False, pin_visible=True, raw_moving=False),
    ]
    processor = _make_processor(states, cfg)

    def _fake_update(_state_arg: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        _ = pre_effect_elapsed
        return RecoveryDirective(rung=1, command_name="press_a", parameters={"press_schedule_ticks": (0,)})

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    actions = _run_ticks_collect_actions(processor, 2)

    assert any("button_1" in action.payload for action in actions)
    assert processor.terminal_status is None


def test_normal_steering_suspended_during_recovery_and_resumes_after() -> None:
    cfg = _make_config()
    states = [_state_with_raw(frame_id=i, nav=True, pin_visible=True, raw_moving=False) for i in range(40)]
    processor = _make_processor(states, cfg)

    directives = [
        RecoveryDirective(
            rung=2,
            command_name="press_a",
            parameters={
                "press_schedule_ticks": (0, 5, 10, 15, 20, 25),
                "reverse_duration_ticks": cfg["recovery_reverse_ticks"],
            },
        )
    ]

    def _fake_update(_state_arg: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        _ = pre_effect_elapsed
        if directives:
            return directives.pop(0)
        return None

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    actions = _run_ticks_collect_actions(processor, 40)

    recovery_actions = [a for a in actions if a.frame_id < cfg["recovery_reverse_ticks"]]
    post_recovery_actions = [a for a in actions if a.frame_id >= cfg["recovery_reverse_ticks"]]

    assert recovery_actions
    assert post_recovery_actions
    assert processor.nav_state in {NavigationState.STEERING, NavigationState.PRE_EFFECT}


def test_second_rung_cannot_start_while_one_is_in_progress() -> None:
    cfg = _make_config()
    states = [_state_with_raw(frame_id=i, nav=True, pin_visible=True, raw_moving=False) for i in range(12)]
    processor = _make_processor(states, cfg)

    call_count = 0

    def _fake_update(_state_arg: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        nonlocal call_count
        _ = pre_effect_elapsed
        call_count += 1
        return RecoveryDirective(
            rung=2,
            command_name="press_a",
            parameters={"press_schedule_ticks": (0, 5, 10, 15, 20, 25)},
        )

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    _run_ticks(processor, 12)

    assert call_count == 1


def test_rung_two_emits_press_a_at_scheduled_offsets_during_reverse() -> None:
    cfg = _make_config()
    states = [_state_with_raw(frame_id=i, nav=True, pin_visible=True, raw_moving=False) for i in range(40)]
    processor = _make_processor(states, cfg)

    def _fake_update(_state_arg: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        _ = pre_effect_elapsed
        if _state_arg.frame_id == 0:
            return RecoveryDirective(
                rung=2,
                command_name="press_a",
                parameters={"press_schedule_ticks": (0, 5, 10, 15, 20, 25)},
            )
        return None

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    actions = _run_ticks_collect_actions(processor, 40)
    press_frames = [action.frame_id for action in actions if "button_1" in action.payload]

    assert press_frames == [0, 5, 10, 15, 20, 25]
    assert all(frame_id < cfg["recovery_reverse_ticks"] for frame_id in press_frames)


def test_terminal_reports_stuck_unrecoverable_through_existing_path() -> None:
    cfg = _make_config()
    states = [_state_with_raw(frame_id=i, nav=True, pin_visible=True, raw_moving=False) for i in range(3)]
    processor = _make_processor(states, cfg)

    def _fake_update(_state_arg: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        _ = _state_arg
        _ = pre_effect_elapsed
        return RecoveryDirective(rung=4, command_name=None, parameters={}, terminal_status="stuck_unrecoverable")

    processor._stuck_monitor.update = _fake_update  # type: ignore[method-assign]

    actions = _run_ticks_collect_actions(processor, 1)

    assert actions == []
    assert processor.terminal_status == "stuck_unrecoverable"
