from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Optional

from framework.contrib.content_loops import CommandRegistry
from framework.contrib.ml import Detection
from framework.interfaces import Action, FrameProcessor, StampedFrame

from d4_bot.state import GameState, GameStateUpdater, StateDiff


class NavigationState(str, Enum):
    STEERING = "steering"
    PRE_EFFECT = "pre_effect"
    SEARCHING = "searching"
    ARRIVED = "arrived"


@dataclass(frozen=True, slots=True)
class SteeringVector:
    x: float
    y: float


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
        self._recent_movement_window_ticks = int(_require_config_key(config, "recent_movement_window_ticks"))
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
        if self._recent_movement_window_ticks <= 0:
            raise ValueError("navigation config recent_movement_window_ticks must be positive")

        self._steering_command_factory = commands.get(self._steering_command_name)

        self._state = NavigationState.STEERING
        self._terminal_status: str | None = None
        self._prev_state: GameState | None = None

        self._pre_effect_until_frame_exclusive: int | None = None
        self._last_burst_real_completion_frame_id: int | None = None

        self._search_started_frame_id: int | None = None
        self._arrival_lost_ticks = 0
        self._recent_movement: deque[bool] = deque(maxlen=self._recent_movement_window_ticks)

    @property
    def nav_state(self) -> NavigationState:
        return self._state

    @property
    def terminal_status(self) -> str | None:
        return self._terminal_status

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
        self._recent_movement.append(state.character_moving)

        # Phase 4b seam: stuck-recovery integration is intentionally omitted in Phase 4a.
        self._phase4b_stuck_recovery_seam(state, state_diff)

        if self._state is NavigationState.PRE_EFFECT:
            if self._in_pre_effect_window(frame.frame_id):
                return None
            self._state = NavigationState.STEERING

        nav_is_lost = self._is_nav_lost(state)
        if nav_is_lost and self._has_recent_movement_context():
            self._arrival_lost_ticks += 1
            if self._arrival_lost_ticks >= self._arrival_confirm_ticks:
                self._state = NavigationState.ARRIVED
                self._terminal_status = "arrived"
                return None
        else:
            self._arrival_lost_ticks = 0

        if self._state is NavigationState.SEARCHING:
            return self._tick_searching(frame, state)

        if nav_is_lost and not self._has_recent_movement_context():
            self._state = NavigationState.SEARCHING
            self._search_started_frame_id = frame.frame_id
            return None

        if self._state is NavigationState.ARRIVED:
            return None

        if not state.nav_arrows:
            return None

        if not self._detections_postdate_previous_completion(state):
            return None

        action = self._emit_steering_action(frame, state, services)
        if action is None:
            return None

        return action

    def _tick_searching(self, frame: StampedFrame, state: GameState) -> Optional[Action]:
        if state.nav_arrows:
            self._state = NavigationState.STEERING
            self._search_started_frame_id = None
            self._arrival_lost_ticks = 0
            return None

        if self._search_started_frame_id is None:
            self._search_started_frame_id = frame.frame_id
            return None

        if (frame.frame_id - self._search_started_frame_id) >= self._search_grace_ticks:
            self._terminal_status = "guide_lost"

        return None

    def _emit_steering_action(
        self,
        frame: StampedFrame,
        state: GameState,
        services: Mapping[str, Any],
    ) -> Action | None:
        detection = _select_target_detection(state.nav_arrows, self._target_class_name)
        if detection is None:
            return None

        steering = self._steering_from_detection(frame, detection)
        if steering is None:
            return None

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

        action = Action(frame_id=frame.frame_id, timestamp=frame.timestamp, payload=payload)

        fps = _capture_fps_from_services(services)
        duration_ticks = _duration_ms_to_ticks(duration_ms=duration_ms, fps=fps)
        self._last_burst_real_completion_frame_id = frame.frame_id + duration_ticks
        self._pre_effect_until_frame_exclusive = frame.frame_id + self._latency_frames + duration_ticks
        self._state = NavigationState.PRE_EFFECT

        return action

    def _in_pre_effect_window(self, frame_id: int) -> bool:
        if self._pre_effect_until_frame_exclusive is None:
            return False
        return frame_id < self._pre_effect_until_frame_exclusive

    def _detections_postdate_previous_completion(self, state: GameState) -> bool:
        if self._last_burst_real_completion_frame_id is None:
            return True
        if state.nav_arrows_frame_id is None:
            return False
        return state.nav_arrows_frame_id > self._last_burst_real_completion_frame_id

    def _is_nav_lost(self, state: GameState) -> bool:
        if state.nav_arrows:
            return False
        if state.nav_arrows_frame_id is None:
            return False
        return state.staleness(state.nav_arrows_frame_id) > self._search_grace_ticks

    def _has_recent_movement_context(self) -> bool:
        return any(self._recent_movement)

    def _phase4b_stuck_recovery_seam(self, state: GameState, state_diff: StateDiff) -> None:
        _ = state
        _ = state_diff

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

