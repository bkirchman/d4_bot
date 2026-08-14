from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional

from framework.contrib.content_loops import CommandRegistry
from framework.contrib.ml import Detection
from framework.interfaces import Action, FrameProcessor, StampedFrame

from d4_bot.recovery import RecoveryDirective, StuckMonitor
from d4_bot.state import GameState, GameStateUpdater, StateDiff


# ADR-014: retain a small settling window after latency before verdicts resume.
PRE_EFFECT_SETTLING_TICKS = 2


class NavigationState(str, Enum):
    STEERING = "steering"
    PRE_EFFECT = "pre_effect"
    STUCK_RECOVERY = "stuck_recovery"
    SEARCHING = "searching"
    ARRIVED = "arrived"


@dataclass(frozen=True, slots=True)
class SteeringVector:
    x: float
    y: float


@dataclass(slots=True)
class ActiveRecoveryRung:
    directive: RecoveryDirective
    started_frame_id: int
    duration_ticks: int
    base_bearing: SteeringVector | None
    reapproach_left: bool
    press_schedule_ticks: tuple[int, ...]
    emitted_press_offsets: set[int] = field(default_factory=set)


class NavigationProcessor(FrameProcessor):
    def __init__(
        self,
        updater: GameStateUpdater,
        state_differ: Callable[[GameState | None, GameState], StateDiff],
        commands: CommandRegistry,
        latency_frames: int,
        config: dict[str, Any],
    ) -> None:
        if latency_frames < 0:
            raise ValueError("latency_frames must be non-negative")

        self._updater = updater
        self._state_differ = state_differ
        self._latency_frames = latency_frames

        self._steering_command_name = str(_require_config_key(config, "steering_command"))
        self._stick_magnitude = int(_require_config_key(config, "stick_magnitude"))
        self._character_anchor_x = int(_require_config_key(config, "character_anchor_x"))
        self._character_anchor_y = int(_require_config_key(config, "character_anchor_y"))
        self._search_grace_ticks = int(_require_config_key(config, "search_grace_ticks"))
        self._arrival_confirm_ticks = int(_require_config_key(config, "arrival_confirm_ticks"))
        self._nav_arrow_only_arrival_backstop_ticks = int(
            _require_config_key(config, "nav_arrow_only_arrival_backstop_ticks")
        )
        self._stuck_window_ticks = int(_require_config_key(config, "stuck_window_ticks"))
        self._stuck_quiet_fraction = float(_require_config_key(config, "stuck_quiet_fraction"))
        self._stuck_event_budget = int(_require_config_key(config, "stuck_event_budget"))
        self._recovery_reverse_ticks = int(_require_config_key(config, "recovery_reverse_ticks"))
        self._recovery_interact_press_count = int(_require_config_key(config, "recovery_interact_press_count"))
        self._recovery_interact_press_interval_ticks = int(
            _require_config_key(config, "recovery_interact_press_interval_ticks")
        )
        self._recovery_reapproach_offset_degrees = float(
            _require_config_key(config, "recovery_reapproach_offset_degrees")
        )
        self._recovery_reapproach_ticks = int(_require_config_key(config, "recovery_reapproach_ticks"))
        self._emission_interval_ms = int(_require_config_key(config, "emission_interval_ms"))
        self._burst_duration_ms = int(_require_config_key(config, "burst_duration_ms"))
        self._significant_direction_change_degrees = float(
            _require_config_key(config, "significant_direction_change_degrees")
        )
        self._stale_direction_tolerance_ticks = int(_require_config_key(config, "stale_direction_tolerance_ticks"))
        self._target_class_name = config.get("target_class_name")

        if self._stick_magnitude <= 0:
            raise ValueError("navigation config stick_magnitude must be positive")
        if self._character_anchor_x <= 0:
            raise ValueError("navigation config character_anchor_x must be a positive integer")
        if self._character_anchor_y <= 0:
            raise ValueError("navigation config character_anchor_y must be a positive integer")
        if self._search_grace_ticks <= 0:
            raise ValueError("navigation config search_grace_ticks must be positive")
        if self._arrival_confirm_ticks <= 0:
            raise ValueError("navigation config arrival_confirm_ticks must be positive")
        if self._nav_arrow_only_arrival_backstop_ticks <= 0:
            raise ValueError("navigation config nav_arrow_only_arrival_backstop_ticks must be positive")
        if self._nav_arrow_only_arrival_backstop_ticks <= self._arrival_confirm_ticks:
            raise ValueError(
                "navigation config nav_arrow_only_arrival_backstop_ticks must be greater than "
                "arrival_confirm_ticks "
                f"(nav_arrow_only_arrival_backstop_ticks={self._nav_arrow_only_arrival_backstop_ticks}, "
                f"arrival_confirm_ticks={self._arrival_confirm_ticks})"
            )
        if self._stuck_window_ticks <= 0:
            raise ValueError("navigation config stuck_window_ticks must be a positive integer")
        if self._stuck_quiet_fraction <= 0.0 or self._stuck_quiet_fraction > 1.0:
            raise ValueError("navigation config stuck_quiet_fraction must be greater than 0.0 and at most 1.0")
        if self._stuck_event_budget <= 0:
            raise ValueError("navigation config stuck_event_budget must be a positive integer")
        if self._recovery_reverse_ticks <= 0:
            raise ValueError("navigation config recovery_reverse_ticks must be a positive integer")
        if self._recovery_interact_press_count <= 0:
            raise ValueError("navigation config recovery_interact_press_count must be a positive integer")
        if self._recovery_interact_press_interval_ticks <= 0:
            raise ValueError(
                "navigation config recovery_interact_press_interval_ticks must be a positive integer"
            )
        if self._recovery_reapproach_offset_degrees <= 0.0 or self._recovery_reapproach_offset_degrees >= 90.0:
            raise ValueError(
                "navigation config recovery_reapproach_offset_degrees must be greater than 0 and less than 90"
            )
        if self._recovery_reapproach_ticks <= 0:
            raise ValueError("navigation config recovery_reapproach_ticks must be a positive integer")
        recovery_press_span_ticks = (
            self._recovery_interact_press_count - 1
        ) * self._recovery_interact_press_interval_ticks
        if recovery_press_span_ticks > self._recovery_reverse_ticks:
            raise ValueError(
                "navigation config recovery interact schedule exceeds reverse duration "
                f"(recovery_interact_press_count={self._recovery_interact_press_count}, "
                f"recovery_interact_press_interval_ticks={self._recovery_interact_press_interval_ticks}, "
                f"recovery_reverse_ticks={self._recovery_reverse_ticks})"
            )
        if self._emission_interval_ms <= 0:
            raise ValueError("navigation config emission_interval_ms must be positive")
        if self._burst_duration_ms <= 0:
            raise ValueError("navigation config burst_duration_ms must be positive")
        if self._emission_interval_ms >= self._burst_duration_ms:
            raise ValueError(
                "navigation config emission_interval_ms must be less than burst_duration_ms so bursts overlap"
            )
        if self._significant_direction_change_degrees <= 0.0:
            raise ValueError("navigation config significant_direction_change_degrees must be positive")
        if self._significant_direction_change_degrees > 180.0:
            raise ValueError("navigation config significant_direction_change_degrees must be <= 180.0")
        # At 60 fps, 120 ticks is 2 seconds of dead reckoning; this ceiling guards against typos causing indefinite blind walking.
        if self._stale_direction_tolerance_ticks < 1 or self._stale_direction_tolerance_ticks > 120:
            raise ValueError("navigation config stale_direction_tolerance_ticks must be between 1 and 120")

        self._steering_command_factory = commands.get(self._steering_command_name)
        self._press_a_command_factory = commands.get("press_a")
        steering_payload = dict(self._steering_command_factory())
        if "move_duration" not in steering_payload:
            raise ValueError(
                f"steering command '{self._steering_command_name}' must include move_duration in payload"
            )
        steering_duration_ms = int(steering_payload["move_duration"])
        if steering_duration_ms <= 0:
            raise ValueError("steering move_duration must be positive")
        if steering_duration_ms != self._burst_duration_ms:
            raise ValueError(
                "navigation config burst_duration_ms must match steering command move_duration "
                f"(burst_duration_ms={self._burst_duration_ms}, move_duration={steering_duration_ms})"
            )
        press_a_payload = dict(self._press_a_command_factory())
        if not any(key.startswith("button_") for key in press_a_payload):
            raise ValueError("press_a command payload must include a button_* field")
        if not any(key.startswith("button_") and key.endswith("_duration") for key in press_a_payload):
            raise ValueError("press_a command payload must include a button_*_duration field")

        self._stuck_monitor = StuckMonitor(
            latency_frames=latency_frames,
            config=config,
            recovery_reverse_ticks=self._recovery_reverse_ticks,
            recovery_interact_press_count=self._recovery_interact_press_count,
            recovery_interact_press_interval_ticks=self._recovery_interact_press_interval_ticks,
        )

        self._state = NavigationState.STEERING
        self._terminal_status: str | None = None
        self._prev_state: GameState | None = None

        self._last_significant_change_frame_id: int | None = None

        self._search_started_frame_id: int | None = None
        self._nav_lost_started_frame_id: int | None = None
        self._last_burst_emitted_frame_id: int | None = None
        self._last_emission_attempt_frame_id: int | None = None

        self._last_known_good_direction: SteeringVector | None = None
        self._last_known_good_direction_frame_id: int | None = None
        self._previous_burst_direction: SteeringVector | None = None
        self._last_non_stale_detection_observed_frame_id: int | None = None

        self._stale_ticks_since_non_stale_detection = 0
        self._last_emission_sig_change = False
        self._last_emission_stale_reuse = False
        self._last_skip_emission_frame_id: int | None = None
        self._last_skip_emission_stale_ticks: int | None = None
        self._both_lost_ticks: int = 0
        self._nav_arrow_lost_ticks: int = 0
        self._target_acquired: bool = False
        self._arrival_via_backstop: bool = False
        self._active_recovery: ActiveRecoveryRung | None = None
        self._last_recovery_rung_frame_id: int | None = None
        self._reapproach_left_next = True

    @property
    def nav_state(self) -> NavigationState:
        return self._state

    @property
    def terminal_status(self) -> str | None:
        return self._terminal_status

    @property
    def last_burst_frame_id(self) -> int | None:
        return self._last_burst_emitted_frame_id

    @property
    def nav_guide_lost_frame_id(self) -> int | None:
        return self._nav_lost_started_frame_id

    @property
    def last_significant_change_frame_id(self) -> int | None:
        return self._last_significant_change_frame_id

    @property
    def stale_ticks_since_non_stale_detection(self) -> int:
        return self._stale_ticks_since_non_stale_detection

    @property
    def last_emission_sig_change(self) -> bool:
        return self._last_emission_sig_change

    @property
    def last_emission_stale_reuse(self) -> bool:
        return self._last_emission_stale_reuse

    @property
    def last_skip_emission_frame_id(self) -> int | None:
        return self._last_skip_emission_frame_id

    @property
    def last_skip_emission_stale_ticks(self) -> int | None:
        return self._last_skip_emission_stale_ticks

    @property
    def both_lost_ticks(self) -> int:
        return self._both_lost_ticks

    @property
    def nav_arrow_lost_ticks(self) -> int:
        return self._nav_arrow_lost_ticks

    @property
    def target_acquired(self) -> bool:
        return self._target_acquired

    @property
    def arrival_via_backstop(self) -> bool:
        return self._arrival_via_backstop

    @property
    def active_recovery_rung(self) -> int | None:
        if self._active_recovery is None:
            return None
        return self._active_recovery.directive.rung

    @property
    def stuck_event_count(self) -> int:
        return self._stuck_monitor.stuck_event_count

    @property
    def last_recovery_rung_frame_id(self) -> int | None:
        return self._last_recovery_rung_frame_id

    @property
    def latest_state(self) -> GameState | None:
        return self._prev_state

    @property
    def status(self) -> str:
        return self._terminal_status or "running"

    @property
    def is_terminal(self) -> bool:
        return self._terminal_status is not None

    def process(
        self,
        frame: StampedFrame,
        services: Mapping[str, Any],
    ) -> Optional[Action]:
        if self.is_terminal:
            return None

        state = self._updater.update(frame)
        state_diff = self._state_differ(self._prev_state, state)
        self._prev_state = state
        self._update_stale_ticks_metric(frame.frame_id, state)

        # F-NAV-1 arrival requires consecutive lost-guide ticks; any visible guide clears streak.
        if state.nav_arrows:
            self._nav_lost_started_frame_id = None

        self._update_arrival_counters(state)

        if self._state is NavigationState.ARRIVED:
            return None

        if (not self._in_pre_effect_window(frame.frame_id)) and self._target_acquired:
            if self._try_arrival():
                return None

        recovery_action = self._phase4b_stuck_recovery_seam(frame, state, state_diff)
        if recovery_action is not None:
            return recovery_action
        if self.is_terminal:
            return None
        if self._active_recovery is not None:
            return None

        if self._state is NavigationState.SEARCHING:
            return self._tick_searching(frame, state)

        action = self._maybe_emit_on_cadence(frame, state, services)

        if self._in_pre_effect_window(frame.frame_id):
            self._state = NavigationState.PRE_EFFECT
            return action

        if self._state is NavigationState.PRE_EFFECT:
            self._state = NavigationState.STEERING

        # STEERING no-arrows decision (outside PRE_EFFECT): arrival path vs searching path.
        if not state.nav_arrows and self._stale_tolerance_exhausted(frame.frame_id):
            return self._handle_missing_nav_guide(frame)

        return action

    def _tick_searching(self, frame: StampedFrame, state: GameState) -> Optional[Action]:
        if state.nav_arrows:
            self._state = NavigationState.STEERING
            self._search_started_frame_id = None
            self._nav_lost_started_frame_id = None
            self._both_lost_ticks = 0
            self._nav_arrow_lost_ticks = 0
            return None

        if self._search_started_frame_id is None:
            self._search_started_frame_id = frame.frame_id
            return None

        # Keep searching alive after target acquisition so the nav-arrow-only backstop
        # can fire. With search_grace_ticks=24 and backstop=300, unsuppressed guide_lost
        # would terminate 276 ticks before the backstop and make it dead code.
        if (
            self._target_acquired
            and self._nav_arrow_lost_ticks < self._nav_arrow_only_arrival_backstop_ticks
        ):
            return None

        if (frame.frame_id - self._search_started_frame_id) >= self._search_grace_ticks:
            self._terminal_status = "guide_lost"

        return None

    def _handle_missing_nav_guide(self, frame: StampedFrame) -> Optional[Action]:
        if self._nav_lost_started_frame_id is None:
            self._nav_lost_started_frame_id = frame.frame_id

        self._state = NavigationState.SEARCHING
        self._search_started_frame_id = frame.frame_id
        return None

    def _emit_steering_action(
        self,
        frame: StampedFrame,
        steering: SteeringVector,
        stale_reuse: bool,
    ) -> Action | None:
        payload = dict(self._steering_command_factory())
        if "move_duration" not in payload:
            raise ValueError(
                f"steering command '{self._steering_command_name}' must include move_duration in payload"
            )

        duration_ms = int(payload["move_duration"])
        if duration_ms <= 0:
            raise ValueError("steering move_duration must be positive")

        move_x = int(round(steering.x * self._stick_magnitude))
        move_y = int(round(steering.y * self._stick_magnitude))
        payload["move_x"] = _clamp(move_x, -self._stick_magnitude, self._stick_magnitude)
        payload["move_y"] = _clamp(move_y, -self._stick_magnitude, self._stick_magnitude)

        sig_change = self._is_significant_direction_change(steering)

        action = Action(frame_id=frame.frame_id, timestamp=frame.timestamp, payload=payload)
        self._last_burst_emitted_frame_id = frame.frame_id
        self._last_emission_sig_change = sig_change
        self._last_emission_stale_reuse = stale_reuse
        self._last_skip_emission_frame_id = None
        self._last_skip_emission_stale_ticks = None
        self._previous_burst_direction = steering

        if sig_change:
            self._last_significant_change_frame_id = frame.frame_id
            self._state = NavigationState.PRE_EFFECT

        return action

    def _in_pre_effect_window(self, frame_id: int) -> bool:
        if self._last_significant_change_frame_id is None:
            return False
        return frame_id < (
            self._last_significant_change_frame_id + self._latency_frames + PRE_EFFECT_SETTLING_TICKS
        )

    def _update_arrival_counters(self, state: GameState) -> None:
        nav_lost = not state.nav_arrows
        pin_lost = not state.pin_visible
        if not nav_lost or not pin_lost:
            self._target_acquired = True
        self._nav_arrow_lost_ticks = self._nav_arrow_lost_ticks + 1 if nav_lost else 0
        self._both_lost_ticks = self._both_lost_ticks + 1 if (nav_lost and pin_lost) else 0

    def _try_arrival(self) -> bool:
        if self._both_lost_ticks >= self._arrival_confirm_ticks:
            self._state = NavigationState.ARRIVED
            self._terminal_status = "arrived"
            return True
        if self._nav_arrow_lost_ticks >= self._nav_arrow_only_arrival_backstop_ticks:
            self._state = NavigationState.ARRIVED
            self._terminal_status = "arrived"
            self._arrival_via_backstop = True
            return True
        return False

    def _maybe_emit_on_cadence(
        self,
        frame: StampedFrame,
        state: GameState,
        services: Mapping[str, Any],
    ) -> Action | None:
        self._last_emission_sig_change = False
        self._last_emission_stale_reuse = False

        if not self._emission_due(frame.frame_id, services):
            return None

        self._last_emission_attempt_frame_id = frame.frame_id
        steering, stale_reuse, stale_ticks, stale_exhausted = self._select_direction_for_emission(frame, state)
        if steering is None:
            if stale_exhausted:
                self._last_skip_emission_frame_id = frame.frame_id
                self._last_skip_emission_stale_ticks = stale_ticks
            return None

        return self._emit_steering_action(
            frame=frame,
            steering=steering,
            stale_reuse=stale_reuse,
        )

    def _emission_due(self, frame_id: int, services: Mapping[str, Any]) -> bool:
        if self._last_emission_attempt_frame_id is None:
            return True
        fps = _capture_fps_from_services(services)
        elapsed_ms = (frame_id - self._last_emission_attempt_frame_id) * (1000.0 / fps)
        return elapsed_ms >= float(self._emission_interval_ms)

    def _select_direction_for_emission(
        self,
        frame: StampedFrame,
        state: GameState,
    ) -> tuple[SteeringVector | None, bool, int, bool]:
        target_detection = _select_freshest_non_stale_detection(
            detections=state.nav_arrows,
            target_class_name=self._target_class_name,
            stale_after_frame_id=self._direction_stale_after_frame_id(),
            fallback_frame_id=state.nav_arrows_frame_id,
        )

        if target_detection is not None:
            steering = self._steering_from_detection(frame, target_detection)
            if steering is None:
                return None, False, self._stale_ticks_since_non_stale_detection, False

            self._last_known_good_direction = steering
            self._last_known_good_direction_frame_id = frame.frame_id
            return steering, False, 0, False

        if self._last_known_good_direction is None or self._last_known_good_direction_frame_id is None:
            return None, False, self._stale_ticks_since_non_stale_detection, False

        stale_ticks = frame.frame_id - self._last_known_good_direction_frame_id
        if stale_ticks <= self._stale_direction_tolerance_ticks:
            return self._last_known_good_direction, True, stale_ticks, False

        return None, False, stale_ticks, True

    def _stale_tolerance_exhausted(self, frame_id: int) -> bool:
        if self._last_known_good_direction_frame_id is None:
            return True
        return (frame_id - self._last_known_good_direction_frame_id) > self._stale_direction_tolerance_ticks

    def _direction_stale_after_frame_id(self) -> int | None:
        if self._last_significant_change_frame_id is None:
            return None
        return self._last_significant_change_frame_id + self._latency_frames

    def _update_stale_ticks_metric(self, frame_id: int, state: GameState) -> None:
        target_detection = _select_freshest_non_stale_detection(
            detections=state.nav_arrows,
            target_class_name=self._target_class_name,
            stale_after_frame_id=self._direction_stale_after_frame_id(),
            fallback_frame_id=state.nav_arrows_frame_id,
        )
        if target_detection is not None:
            self._last_non_stale_detection_observed_frame_id = frame_id
            self._stale_ticks_since_non_stale_detection = 0
            return

        if self._last_non_stale_detection_observed_frame_id is None:
            self._stale_ticks_since_non_stale_detection = 0
            return

        self._stale_ticks_since_non_stale_detection = frame_id - self._last_non_stale_detection_observed_frame_id

    def _is_significant_direction_change(self, new_direction: SteeringVector) -> bool:
        if self._previous_burst_direction is None:
            return True
        angle_delta = _angle_difference_degrees(self._previous_burst_direction, new_direction)
        return angle_delta > self._significant_direction_change_degrees

    def _phase4b_stuck_recovery_seam(
        self,
        frame: StampedFrame,
        state: GameState,
        state_diff: StateDiff,
    ) -> Action | None:
        _ = state_diff

        if self._active_recovery is not None:
            return self._tick_active_recovery(frame)

        directive = self._stuck_monitor.update(
            state,
            pre_effect_elapsed=not self._in_pre_effect_window(frame.frame_id),
        )
        if directive is None:
            return None
        if directive.terminal_status is not None:
            self._terminal_status = directive.terminal_status
            return None

        execution = self._build_recovery_execution(frame, state, directive)
        if execution is None:
            return None

        self._last_recovery_rung_frame_id = frame.frame_id
        self._active_recovery = execution
        self._state = NavigationState.STUCK_RECOVERY
        return self._tick_active_recovery(frame)

    def _build_recovery_execution(
        self,
        frame: StampedFrame,
        state: GameState,
        directive: RecoveryDirective,
    ) -> ActiveRecoveryRung | None:
        press_schedule = tuple(int(value) for value in directive.parameters.get("press_schedule_ticks", ()))
        if directive.rung == 1:
            return ActiveRecoveryRung(
                directive=directive,
                started_frame_id=frame.frame_id,
                duration_ticks=1,
                base_bearing=None,
                reapproach_left=True,
                press_schedule_ticks=press_schedule,
            )

        bearing = self._resolve_recovery_bearing(frame, state)
        if bearing is None:
            return None

        if directive.rung == 2:
            return ActiveRecoveryRung(
                directive=directive,
                started_frame_id=frame.frame_id,
                duration_ticks=self._recovery_reverse_ticks,
                base_bearing=bearing,
                reapproach_left=True,
                press_schedule_ticks=press_schedule,
            )

        if directive.rung == 3:
            reapproach_left = self._reapproach_left_next
            self._reapproach_left_next = not self._reapproach_left_next
            return ActiveRecoveryRung(
                directive=directive,
                started_frame_id=frame.frame_id,
                duration_ticks=self._recovery_reverse_ticks + self._recovery_reapproach_ticks,
                base_bearing=bearing,
                reapproach_left=reapproach_left,
                press_schedule_ticks=(),
            )

        return None

    def _resolve_recovery_bearing(self, frame: StampedFrame, state: GameState) -> SteeringVector | None:
        steering, _, _, _ = self._select_direction_for_emission(frame, state)
        if steering is not None:
            return steering
        return self._last_known_good_direction

    def _tick_active_recovery(self, frame: StampedFrame) -> Action | None:
        active = self._active_recovery
        if active is None:
            return None

        elapsed_ticks = frame.frame_id - active.started_frame_id
        if elapsed_ticks >= active.duration_ticks:
            self._active_recovery = None
            if not self.is_terminal:
                self._state = NavigationState.STEERING
            return None

        press_now = elapsed_ticks in active.press_schedule_ticks and elapsed_ticks not in active.emitted_press_offsets
        movement_vector = self._recovery_movement_vector(active, elapsed_ticks)
        action = self._emit_recovery_action(frame, movement_vector, emit_press_a=press_now)
        if press_now:
            active.emitted_press_offsets.add(elapsed_ticks)
        return action

    def _recovery_movement_vector(self, active: ActiveRecoveryRung, elapsed_ticks: int) -> SteeringVector | None:
        if active.directive.rung == 1:
            return None
        if active.base_bearing is None:
            return None
        if active.directive.rung == 2:
            return SteeringVector(x=-active.base_bearing.x, y=-active.base_bearing.y)
        if active.directive.rung == 3:
            if elapsed_ticks < self._recovery_reverse_ticks:
                return SteeringVector(x=-active.base_bearing.x, y=-active.base_bearing.y)
            signed_offset = self._recovery_reapproach_offset_degrees if active.reapproach_left else -self._recovery_reapproach_offset_degrees
            return _rotate_vector(active.base_bearing, signed_offset)
        return None

    def _emit_recovery_action(
        self,
        frame: StampedFrame,
        movement_vector: SteeringVector | None,
        *,
        emit_press_a: bool,
    ) -> Action | None:
        payload: dict[str, Any] = {}
        if movement_vector is not None:
            steering_payload = dict(self._steering_command_factory())
            steering_payload["move_x"] = _clamp(
                int(round(movement_vector.x * self._stick_magnitude)),
                -self._stick_magnitude,
                self._stick_magnitude,
            )
            steering_payload["move_y"] = _clamp(
                int(round(movement_vector.y * self._stick_magnitude)),
                -self._stick_magnitude,
                self._stick_magnitude,
            )
            payload.update(steering_payload)
            self._last_burst_emitted_frame_id = frame.frame_id

        if emit_press_a:
            payload.update(dict(self._press_a_command_factory()))

        if not payload:
            return None

        return Action(frame_id=frame.frame_id, timestamp=frame.timestamp, payload=payload)

    def _steering_from_detection(self, frame: StampedFrame, detection: Detection) -> SteeringVector | None:
        x, y, w, h = detection.bbox
        arrow_center_x = x + (w / 2.0)
        arrow_center_y = y + (h / 2.0)

        frame_height, frame_width = frame.frame.shape[:2]
        if self._character_anchor_x >= frame_width:
            raise ValueError(
                "navigation config character_anchor_x is out of bounds for captured frame: "
                f"character_anchor_x={self._character_anchor_x}, frame_dimensions={frame_width}x{frame_height}"
            )
        if self._character_anchor_y >= frame_height:
            raise ValueError(
                "navigation config character_anchor_y is out of bounds for captured frame: "
                f"character_anchor_y={self._character_anchor_y}, frame_dimensions={frame_width}x{frame_height}"
            )

        anchor_x = float(self._character_anchor_x)
        anchor_y = float(self._character_anchor_y)

        delta_x = arrow_center_x - anchor_x
        delta_y = arrow_center_y - anchor_y
        magnitude = math.hypot(delta_x, delta_y)
        if magnitude <= 0.0:
            return None

        return SteeringVector(x=(delta_x / magnitude), y=(delta_y / magnitude))


def _require_config_key(config: dict[str, Any], key: str) -> Any:
    if key not in config:
        raise ValueError(f"navigation config missing required key '{key}'")
    return config[key]


def _select_target_detection(
    detections: list[Detection],
    target_class_name: object,
) -> Detection | None:
    filtered = detections
    if isinstance(target_class_name, str) and target_class_name:
        filtered = [det for det in detections if det.class_name == target_class_name]

    if not filtered:
        return None

    return max(filtered, key=lambda det: det.confidence)


def _select_freshest_non_stale_detection(
    detections: list[Detection],
    target_class_name: object,
    stale_after_frame_id: int | None,
    fallback_frame_id: int | None,
) -> Detection | None:
    filtered = detections
    if isinstance(target_class_name, str) and target_class_name:
        filtered = [det for det in detections if det.class_name == target_class_name]

    if not filtered:
        return None

    eligible: list[Detection] = []
    for detection in filtered:
        origin_frame_id = _detection_origin_frame_id(detection, fallback_frame_id)
        if stale_after_frame_id is None or origin_frame_id > stale_after_frame_id:
            eligible.append(detection)

    if not eligible:
        return None

    return max(
        eligible,
        key=lambda det: (_detection_origin_frame_id(det, fallback_frame_id), det.confidence),
    )


def _detection_origin_frame_id(detection: Detection, fallback_frame_id: int | None) -> int:
    detection_frame_id = getattr(detection, "frame_id", None)
    if isinstance(detection_frame_id, int):
        return detection_frame_id
    if fallback_frame_id is not None:
        return fallback_frame_id
    return -1


def _duration_ms_to_ticks(duration_ms: int, fps: float) -> int:
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    if fps <= 0:
        raise ValueError("capture fps must be positive")
    return max(1, int(math.ceil((duration_ms / 1000.0) * fps)))


def _capture_fps_from_services(services: Mapping[str, Any]) -> float:
    capture = services.get("capture")
    fps = getattr(capture, "fps", None)
    if fps is None:
        raise ValueError("services['capture'].fps is required for steering duration tick conversion")
    return float(fps)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _angle_difference_degrees(previous: SteeringVector, current: SteeringVector) -> float:
    dot = (previous.x * current.x) + (previous.y * current.y)
    det = (previous.x * current.y) - (previous.y * current.x)
    angle = math.degrees(math.atan2(det, dot))
    return abs(angle)


def _rotate_vector(vector: SteeringVector, offset_degrees: float) -> SteeringVector:
    radians = math.radians(offset_degrees)
    cos_v = math.cos(radians)
    sin_v = math.sin(radians)
    rotated_x = (vector.x * cos_v) - (vector.y * sin_v)
    rotated_y = (vector.x * sin_v) + (vector.y * cos_v)
    magnitude = math.hypot(rotated_x, rotated_y)
    if magnitude <= 0.0:
        return vector
    return SteeringVector(x=rotated_x / magnitude, y=rotated_y / magnitude)
