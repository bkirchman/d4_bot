from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from d4_bot.state import GameState


@dataclass(frozen=True, slots=True)
class RecoveryDirective:
    rung: int
    command_name: str | None
    parameters: dict[str, Any]
    terminal_status: str | None = None


class RecoveryLadder:
    def __init__(
        self,
        *,
        recovery_reverse_ticks: int,
        recovery_interact_press_count: int,
        recovery_interact_press_interval_ticks: int,
    ) -> None:
        if recovery_reverse_ticks <= 0:
            raise ValueError("recovery_reverse_ticks must be positive")
        if recovery_interact_press_count <= 0:
            raise ValueError("recovery_interact_press_count must be positive")
        if recovery_interact_press_interval_ticks <= 0:
            raise ValueError("recovery_interact_press_interval_ticks must be positive")

        self._recovery_reverse_ticks = recovery_reverse_ticks
        self._recovery_interact_press_count = recovery_interact_press_count
        self._recovery_interact_press_interval_ticks = recovery_interact_press_interval_ticks
        self._stuck_event_count = 0
        self._terminal = False

    @property
    def stuck_event_count(self) -> int:
        return self._stuck_event_count

    def reset(self) -> None:
        self._stuck_event_count = 0
        self._terminal = False

    def report_moved(self) -> None:
        self.reset()

    def next_directive(self) -> RecoveryDirective:
        if self._terminal:
            return RecoveryDirective(
                rung=4,
                command_name=None,
                parameters={},
                terminal_status="stuck_unrecoverable",
            )

        rung = min(self._stuck_event_count + 1, 4)
        if rung == 1:
            return RecoveryDirective(
                rung=1,
                command_name="press_a",
                parameters={
                    "stationary": True,
                    "press_count": 1,
                    "press_schedule_ticks": (0,),
                },
            )
        if rung == 2:
            press_schedule_ticks = tuple(
                tick * self._recovery_interact_press_interval_ticks
                for tick in range(self._recovery_interact_press_count)
            )
            return RecoveryDirective(
                rung=2,
                command_name="press_a",
                parameters={
                    "stationary": False,
                    "reverse_duration_ticks": self._recovery_reverse_ticks,
                    "press_count": self._recovery_interact_press_count,
                    "press_interval_ticks": self._recovery_interact_press_interval_ticks,
                    "press_schedule_ticks": press_schedule_ticks,
                },
            )
        if rung == 3:
            return RecoveryDirective(
                rung=3,
                command_name=None,
                parameters={
                    "stationary": False,
                    "mode": "angular_reapproach",
                },
            )

        self._terminal = True
        return RecoveryDirective(
            rung=4,
            command_name=None,
            parameters={},
            terminal_status="stuck_unrecoverable",
        )

    def advance(self) -> None:
        if not self._terminal:
            self._stuck_event_count += 1
            if self._stuck_event_count >= 4:
                self._terminal = True


class StuckMonitor:
    def __init__(
        self,
        latency_frames: int,
        config: Mapping[str, Any],
        *,
        recovery_reverse_ticks: int,
        recovery_interact_press_count: int,
        recovery_interact_press_interval_ticks: int,
    ) -> None:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")

        self._latency_frames = latency_frames
        self._stuck_window_ticks = int(_require_config_key(config, "stuck_window_ticks"))
        self._stuck_quiet_fraction = float(_require_config_key(config, "stuck_quiet_fraction"))
        self._stuck_event_budget = int(_require_config_key(config, "stuck_event_budget"))
        if self._stuck_window_ticks <= 0:
            raise ValueError("stuck_window_ticks must be positive")
        if self._stuck_quiet_fraction <= 0.0 or self._stuck_quiet_fraction > 1.0:
            raise ValueError("stuck_quiet_fraction must be greater than 0.0 and at most 1.0")
        if self._stuck_event_budget <= 0:
            raise ValueError("stuck_event_budget must be positive")

        self._ladder = RecoveryLadder(
            recovery_reverse_ticks=recovery_reverse_ticks,
            recovery_interact_press_count=recovery_interact_press_count,
            recovery_interact_press_interval_ticks=recovery_interact_press_interval_ticks,
        )
        self._raw_motion_history: deque[bool] = deque(maxlen=self._stuck_window_ticks)
        self._terminal_directive = RecoveryDirective(
            rung=4,
            command_name=None,
            parameters={},
            terminal_status="stuck_unrecoverable",
        )

    @property
    def stuck_event_count(self) -> int:
        return self._ladder.stuck_event_count

    def update(self, state: GameState, *, pre_effect_elapsed: bool = True) -> RecoveryDirective | None:
        if self._ladder.stuck_event_count >= self._stuck_event_budget:
            return self._terminal_directive

        if state.character_moving_raw:
            self._raw_motion_history.clear()
            self._ladder.report_moved()
            return None

        self._raw_motion_history.append(not state.character_moving_raw)
        if not pre_effect_elapsed:
            return None
        if len(self._raw_motion_history) < self._stuck_window_ticks:
            return None
        quiet_fraction = sum(self._raw_motion_history) / len(self._raw_motion_history)
        if not state.nav_arrows:
            return None
        if quiet_fraction < self._stuck_quiet_fraction:
            return None

        directive = self._ladder.next_directive()
        self._ladder.advance()
        return directive


def _require_config_key(config: Mapping[str, Any], key: str) -> Any:
    if key not in config:
        raise ValueError(f"missing required config key '{key}'")
    return config[key]
