# FEATURE_SPECS.md — d4_bot

**Status:** Implementation authority. Copilot builds from these specs — not from tutorials, not from memory, not from game_bot source.
**Scope:** Everything needed through the navigation milestone (BUILD_PLAN.md Phases 0–4), plus the framework gaps that must land in `bot_framework` first. Combat and later features are listed as deferred stubs only.
**Reading rule:** Where this document cites a framework class signature, that citation is the spec. If framework source on main disagrees at implementation time, framework source wins and this document gets corrected — never silently adapted around.

**Feature ID scheme:** `FG-*` framework gaps (built in `bot_framework`), `F-CFG-*` configuration, `F-CAP-*` capture, `F-CTL-*` controller, `F-DET-*` detection, `F-GS-*` game state, `F-NAV-*` navigation, `F-FLOW-*` flow/entry points, `F-DIAG-*` diagnostics. Complexity: **L**ow / **M**edium / **H**igh (Copilot risk, not lines of code).

---

## 0. Framework Surface Reference (import contract)

All `d4_bot` code imports from exactly this surface. Anything else is a violation.

| Import | Provides |
|---|---|
| `from framework.interfaces import CaptureSource, OutputDevice, FrameProcessor, StampedFrame, Action` | Core ABCs and data types. `StampedFrame(frame_id: int, timestamp: float, frame: np.ndarray, metadata: dict)`. `Action(frame_id: int, timestamp: float, payload: Any)`. `FrameProcessor.process(frame: StampedFrame, services: ProcessorServices) -> Action | None` — `services` bundles the per-tick collaborators the processor needs (frame history, <fill from framework/interfaces.py: e.g. command registry access, capture metadata, whatever else the dataclass carries>). Read the dataclass in framework/interfaces.py for the exact field list; that source is the spec of record for this signature. |
| `from framework.loop import BotLoop` | `BotLoop(capture, output, processor, history)`; methods `start()`, `step()`, `stop()`. Synchronous: capture → record → process → execute → re-record. |
| `from framework.temporal import FrameHistory, TemporalAligner` | `FrameHistory(capacity: int)`; rolling `(StampedFrame, Action | None)` pairs, queryable by `frame_id` and timestamp. |
| `from framework.contrib.hardware import AVerMediaCapture, UDPXboxOutput, ReplayCapture` | Capture sources and controller output. `AVerMediaCapture(device_index, width, height, fps, latency_frames, backend)`. `UDPXboxOutput(udp_ip, udp_port, response_port, response_mode, debug_mode)`. |
| `from framework.contrib.detection import ColorMatchDetector, TemplateMatchDetector` | Existing detectors. |
| `from framework.contrib.content_loops import ContentLoopProcessor, CommandRegistry, DetectorRegistry, load_loops_from_file` | YAML loop machinery. |
| `from framework.contrib.ml import YoloDetector, Detection` | **New — FG-1.** |
| `from framework.contrib.detection import RoiMotionDetector` | **New — FG-2.** |
| `from framework.contrib.recording import FrameRecorder` | **New — FG-3.** |
| `from framework.contrib.config import load_layered_config` | **New — FG-4.** |

---
**Signature history:** `process(frame, history)` → `process(frame, services)` per ADR-<NNN>. Any older doc reference to a `history` parameter is stale and must be corrected in place when found.

## 1. Framework Gaps (build these in `bot_framework` first)

These are mechanisms, not game knowledge. Litmus test passed for each: "works unchanged for Halo."

### FG-1 — YoloDetector (`framework/contrib/ml/`)

- **Purpose:** Game-agnostic YOLO inference wrapper that consumes StampedFrames at a declared cadence and returns typed detections.
- **Layer:** framework contrib, behind the `[ml]` optional extra (adds `ultralytics` + torch deps; core stays stdlib+numpy).
- **Origin:** New (replaces game_bot's NavIconDetector *mechanism*; the model itself is carried data).
- **Surface (spec):**
  - `Detection` dataclass: `class_name: str`, `confidence: float`, `bbox: tuple[int, int, int, int]` (x, y, w, h in source-frame pixels), `frame_id: int`.
  - `YoloDetector(weights_path: str | Path, class_map: dict[int, str], confidence_threshold: float, cadence: int = 1, roi: tuple[int, int, int, int] | None = None, device: str = "cuda")`.
  - `update(frame: StampedFrame) -> list[Detection]` — runs inference only when `frame.frame_id % cadence == 0`; on off-ticks returns the cached last result unchanged (whose `frame_id` fields still carry the *origin* frame, which is how consumers measure staleness).
  - `last_result: list[Detection]` and `last_inference_frame_id: int | None` properties.
- **Inputs:** StampedFrame (1920×1080 BGR ndarray); optional ROI crops before inference; bbox output is mapped back to full-frame coordinates when an ROI is used.
- **Outputs:** `list[Detection]`. No side effects beyond internal cache.
- **Dependencies:** ultralytics YOLO load/predict; numpy. No framework-core changes.
- **Do-NOT guardrails:** No D4 class names, paths, or thresholds as defaults. No threading. No drawing/visualization inside the class. No per-call model reload.
- **Complexity:** M.
- **Acceptance (replay-testable):** Given a directory of recorded frames containing the nav guide and the carried-forward weights, a harness script prints ≥1 detection with correct class name on frames where the guide is visible, 0 on frames where it isn't, and demonstrates cadence (inference count = frame count / cadence).

### FG-2 — RoiMotionDetector (`framework/contrib/detection/`)

- **Purpose:** Answers "is this region of the screen changing?" via frame differencing on a named ROI, with hysteresis — the generic mechanism behind minimap-based stuck detection (ADR-009).
- **Layer:** framework contrib (sibling of ColorMatchDetector).
- **Origin:** Redesigned from game_bot's frame-freshness/differencing ideas; hot-path-safe this time (the old freshness check throttled the loop to 7 fps and was removed — see Key Learnings; this detector must be O(ROI size) with no full-frame work).
- **Surface (spec):**
  - `RoiMotionDetector(roi: tuple[int, int, int, int], diff_threshold: int, changed_fraction: float, hysteresis_ticks: int)`.
  - `update(frame: StampedFrame) -> bool` — grayscale absdiff of the ROI vs. the previous ROI crop; "raw motion" when the fraction of pixels with diff > `diff_threshold` exceeds `changed_fraction`; the returned boolean only flips state after `hysteresis_ticks` consecutive raw readings agree (debounce both directions).
  - `raw_motion: bool` property (undebounced, for the tuner diagnostic).
- **Inputs:** consecutive StampedFrames; ROI in full-frame pixel coords.
- **Outputs:** debounced boolean; stores previous ROI crop internally (ROI-sized copy only — never the full frame).
- **Dependencies:** numpy only (absdiff and thresholding in numpy; no OpenCV needed).
- **Do-NOT guardrails:** No full-frame differencing. No storing full frames. No adaptive/learned thresholds. First call (no previous crop) returns False.
- **Complexity:** L.
- **Acceptance (replay-testable):** Against a recorded sequence of walking-then-standing, the detector's debounced output transitions True→False within `hysteresis_ticks` + a small margin of the visible stop, with zero flicker during either steady state.

### FG-3 — FrameRecorder (`framework/contrib/recording/`)

- **Purpose:** Dump frames and an action log to disk during live runs so datasets are a byproduct of normal sessions (ADR-012).
- **Layer:** framework contrib.
- **Origin:** New.
- **Surface (spec):**
  - `FrameRecorder(output_dir: str | Path, every_n: int = 1, jpeg_quality: int = 90)`.
  - `record(frame: StampedFrame, action: Action | None) -> None` — writes `frame_{frame_id:08d}.jpg` for every `every_n`-th frame and appends one line per call to `actions.jsonl` (`frame_id`, `timestamp`, action payload or null).
  - `close() -> None` — flushes the log.
  - Output layout must be directly consumable by `ReplayCapture` (same directory convention it already reads).
- **Inputs:** every tick's (frame, action) pair. Two sanctioned call sites: a capture-only harness loop (`scripts/record_dataset.py`, Phase 1 — no BotLoop involved), or an entry script that steps `BotLoop` manually and records the newest (frame, action) pair from `FrameHistory` after each step (`run_nav.py --record`, Phase 4a). `BotLoop` itself is never modified to know about recording.
- **Outputs:** JPEG files + `actions.jsonl` on disk.
- **Do-NOT guardrails:** No threading, no video encoding, no compression queues — if JPEG writes are too slow at 60 fps, the knob is `every_n`, not architecture. Never enabled by default.
- **Complexity:** L.
- **Acceptance (live-only):** A 30-second live run with recording enabled sustains ≥ 45 loop FPS and produces a directory that `ReplayCapture` can replay end-to-end without error.

### FG-4 — load_layered_config (`framework/contrib/config/`)

- **Purpose:** Load a base YAML config directory with a season/variant overrides file merged on top (overrides win), so seasonal churn is data, not code (ADR-013).
- **Layer:** framework contrib (generic: any game with content patches needs this).
- **Origin:** New.
- **Surface (spec):**
  - `load_layered_config(base_path: str | Path, overrides_path: str | Path | None = None) -> dict` — deep-merge: override scalars replace, override dicts merge recursively, override lists replace wholesale.
  - Raises on missing base file; missing overrides file is not an error (returns base).
- **Do-NOT guardrails:** No schema validation here (loaders in d4_bot validate their own schemas). No environment-variable magic. No caching.
- **Complexity:** L.
- **Acceptance (offline unit test):** A pytest covering scalar override, nested-dict merge, list replacement, and the no-overrides path.

---

## 2. Configuration Layer (`d4_bot/configs/`)

Schemas are specified as key tables. All files are YAML. All keys snake_case. The config loader for each file lives beside its consumer (`commands.py`, `detectors.py`, etc.) and **validates required keys at startup, failing loudly with the missing key name.**

### F-CFG-1 — `hardware.yaml`

- **Purpose:** Rig facts. Zero game knowledge.
- **Origin:** Redesigned from diablo_bot's CLI-args approach (flags move to config; CLI may override).

| Key | Type | Value on this rig | Notes |
|---|---|---|---|
| `capture.device_index` | int | 1 | |
| `capture.backend` | str | `dshow` | |
| `capture.width` / `capture.height` | int | 1920 / 1080 | Asserted at startup (ADR/§9.1 of ARCHITECTURE) |
| `capture.fps` | float | 60.0 | |
| `capture.latency_frames` | int | 6 | The ONLY place this literal lives. Passed to `AVerMediaCapture`; all logic reads `capture.latency_frames` off the object at runtime. |
| `controller.udp_ip` / `controller.udp_port` | str / int | 192.168.1.196 / 5005 | |
| `controller.response_port` / `controller.response_mode` | int | 5006 / 0 | |
| `active_season` | str | e.g. `s09` | Selects `configs/seasons/<active_season>/overrides.yaml`; CLI flag may override |

- **Complexity:** L. **Acceptance:** startup with a wrong resolution or a missing key exits with a clear one-line error naming the key.

### F-CFG-2 — `rois.yaml`

- **Purpose:** The only file in the repo where pixel coordinates may appear. Named regions at 1920×1080.
- **Origin:** New (game_bot scattered ROIs across settings and JSON; that pattern is dead).
- **Schema:** flat map of `roi_name: [x, y, w, h]`. Initial names: `minimap`, `nav_arrow_window` (region where the pin guide renders — likely full playfield minus HUD; tuned via F-DIAG-1), plus future HUD slots.
- **Complexity:** L. **Acceptance:** F-DIAG-1 renders every named ROI in the right place on live capture.

### F-CFG-3 — `buttons.yaml`

- **Purpose:** Semantic command names → firmware v2.1 single-packet duration commands. The quarantine for button indices (they appear here and nowhere else).
- **Origin:** Redesigned from diablo_bot `registries.py` constants + game_bot's JSON command libraries (contents hand-translated where useful; JSON files not carried).
- **Schema:** map of `command_name:` → `{ type: <button_duration | hat_duration | move_duration | trigger_duration>, index: <int, for buttons>, direction/axis parameters per type, duration_ms: <int> }`. Exact parameter names per command type mirror `protocol.md` — Copilot must be given the relevant protocol.md section when touching this file or `commands.py`.
- **Command policy: grow-on-demand, starting at two.** Initial contents: `press_a` (button_1_duration) and `press_b` (button_2_duration) — the only named commands the nav milestone consumes (popup dismissal; B-escape in recovery). All movement is parametric via the steering helper (F-CTL-2) and never appears here. New commands are added one at a time via prompt C-1 when a consumer (a loop, a processor) actually needs them — never pre-populated as a full controller map. The per-game tunable in each entry is `duration_ms`: what registers as a "click" varies per game, which is why atoms live in the game repo.
- **Heritage note (why this file is small):** game_bot's `basic_commands.json` press/release pairs are absorbed by the v2.1 firmware (the duration packet *is* the click; release is the Arduino's job); its `commands.json` multi-step sequences are replaced by YAML content loops. buttons.yaml is only the thin atom layer between a referenceable name and a firmware packet. Situational button semantics (B = dodge in combat, cancel in menus) belong to processors reading `GameState.screen_mode`, not to this file. (Deliberately no camera-rotation command: Diablo 4's camera is fixed isometric.)
- **Firmware truth restated:** button_0=X, button_1=A, button_2=B, button_3=Y; hat_y positive = up. Single-packet self-releasing only; two-packet press/release is forbidden.
- **Complexity:** L (schema) but **H-risk for Copilot** (index confusion is a repeat offender — see TROUBLESHOOTING). **Acceptance:** F-DIAG-3 fires each named command and the character visibly performs it.

### F-CFG-4 — `configs/detectors/*.yaml` (one file per detector; filename = registry name)

- **Purpose:** Per-detector tuning, referencing ROIs and models by name/path — never inline coordinates.
- **Origin:** New.
- **Common keys:** `type` (`yolo` | `roi_motion` | `color_match` | `template_match`), `roi` (name from rois.yaml), `cadence` (int, default 1).
- **`nav_arrow.yaml`:** `type: yolo`, `weights: models/nav_arrow/best.pt`, `classes: models/nav_arrow/classes.yaml`, `confidence_threshold`, `cadence: 2` (starting value; tuned live), `roi: nav_arrow_window`.
- **`minimap_motion.yaml`:** `type: roi_motion`, `roi: minimap`, `diff_threshold`, `changed_fraction`, `hysteresis_ticks` (starting value: 6 — coincidentally near latency_frames but unrelated; it's a debounce).
- **Complexity:** L. **Acceptance:** `build_detector_registry()` constructs every detector in the directory without error; F-DIAG-2 can live-tune each.

### F-CFG-5 — Season assets & refresh workflow

- **Purpose:** Make the ~12-week churn a procedure: `configs/seasons/sNN/{icons/, overrides.yaml}` layered via FG-4; captured with F-DIAG-4.
- **Origin:** New (game_bot had no seasonal story; this was tribal knowledge).
- **Complexity:** L. **Acceptance:** switching `active_season` between two season folders changes a detector threshold without touching any Python file.

---

## 3. Capture Layer

### F-CAP-1 — Capture wiring

- **Purpose:** Construct `AVerMediaCapture` from `hardware.yaml`, assert geometry, expose `latency_frames` to everything downstream.
- **Layer:** d4_bot (`scripts/run_nav.py` + a small shared builder in `src/d4_bot/`).
- **Origin:** Carried from diablo_bot's `run_farm_v1.py` pattern, minus CLI-flag sprawl.
- **Consumes:** `AVerMediaCapture` (signature in §0).
- **Behavior:** first frame's ndarray shape is checked against configured width/height; mismatch = exit with error. Prints `latency_frames` at startup (as run_farm_v1.py does).
- **Complexity:** L. **Acceptance (live):** startup banner shows resolution, fps, and `latency_frames=6` sourced from the object.

---

## 4. Controller Layer

### F-CTL-1 — build_command_registry (`src/d4_bot/commands.py`)

- **Purpose:** Read `buttons.yaml`, produce the framework `CommandRegistry` mapping semantic names → `Action` payloads in firmware v2.1 form.
- **Layer:** d4_bot wiring.
- **Origin:** Redesigned from diablo_bot's `build_command_registry()` (hardcoded constants → YAML-driven).
- **Surface (spec):** `build_command_registry(buttons_config: dict) -> CommandRegistry`.
- **Do-NOT guardrails:** no button-index literals in the function body; no press/release pairs; no direct socket use (payloads only — `UDPXboxOutput` does transport).
- **Complexity:** M. **Acceptance (live):** F-DIAG-3 passes for every command in buttons.yaml.

### F-CTL-2 — Steering emission helper (`src/d4_bot/processors/navigation.py`, internal)

- **Purpose:** Convert a steering vector (screen-space direction toward the nav guide) into a left-stick `move_duration` payload: angle → stick x/y, fixed magnitude, short duration bursts.
- **Layer:** d4_bot (stick semantics are camera-relative and game-specific; candidate for framework promotion later, not now).
- **Origin:** New. Explicitly does **not** use game_bot's axis-calibration CSVs — per intake, diagonal calibration was only needed for map-cursor work and is a non-issue for world movement; stored timing values suffice.
- **Behavior:** emits movement as overlapping `move_duration` bursts. Emission cadence (`emission_interval_ms`, config) is shorter than burst duration (`burst_duration_ms`, config) so a new packet always supersedes the running firmware timer before it expires, per protocol.md §3.2. The character never sees a neutral stick during normal operation. Burst duration functions as a dead-man's-switch safety timer — if the processor stops emitting (crash, hang), the firmware self-releases within `burst_duration_ms`. Direction is recomputed on every emission from the freshest available detection, subject to the direction-freshness rule in F-NAV-2. Neither `emission_interval_ms` nor `burst_duration_ms` is a literal — both are `navigation.yaml` values. See ADR-014.
- **Stale-direction tolerance:** when the freshest available detection is stale for direction purposes (per F-NAV-2), the processor continues emitting bursts using the last known good direction for up to `stale_direction_tolerance_ticks` (config). Beyond that, the processor skips emission and the firmware self-releases within `burst_duration_ms`. See ADR-014.
- **Emission is decoupled from verdict gating.** The processor emits bursts on the emission cadence continuously. Verdicts (arrival, stuck, correction against just-issued command) gate on the pre-effect window relative to the most recent *significant direction change*, not the most recent emission. Small continuous corrections during steady walking do not reset the verdict window.
- **Complexity:** M. **Acceptance:** covered by F-NAV-1's acceptance.

---

## 5. Detection Layer (d4_bot side)

### F-DET-1 — build_detector_registry (`src/d4_bot/detectors.py`)

- **Purpose:** Read every YAML in `configs/detectors/`, construct the corresponding framework detector (`YoloDetector`, `RoiMotionDetector`, `ColorMatchDetector`, `TemplateMatchDetector`), resolve ROI names via `rois.yaml`, return a `DetectorRegistry` plus a plain dict for GameState use.
- **Layer:** d4_bot wiring.
- **Origin:** Redesigned from diablo_bot's hardcoded `build_detector_registry(config)`.
- **Surface (spec):** `build_detectors(detector_dir: str | Path, rois: dict, season_overrides: dict) -> dict[str, object]` and `build_detector_registry(...) -> DetectorRegistry` (the latter for YAML-loop compatibility).
- **Do-NOT guardrails:** no detector construction outside this module; no coordinate literals; unknown `type` = loud failure listing valid types.
- **Complexity:** M. **Acceptance:** constructs all shipped detector configs; unknown type and unknown ROI name each produce a clear error naming the file.

### F-DET-2 — Nav-arrow model as data (`models/nav_arrow/`)

- **Purpose:** House the carried-forward game_bot YOLO nav model (proven; no retraining) + `classes.yaml` (class index → name, per-class confidence overrides).
- **Origin:** Carried (data only).
- **Complexity:** L. **Acceptance:** FG-1's acceptance harness passes using these exact files.

### F-DET-3 — Minimap-pin detector (`src/d4_bot/detectors/minimap_pin.py`)

- **Purpose:** detect the destination pin on the minimap as a second arrival signal, independent of the nav_arrow detector. See ADR-015.
- **Surface:** `MinimapPinDetector(config: dict, template_path: str)` implementing the framework detector interface. Consumes `StampedFrame`, produces `pin_visible: bool` and `pin_position: tuple[int, int] | None` (position in full-frame pixel coordinates, or None if not visible).
- **Method:** `cv2.matchTemplate` with `TM_CCOEFF_NORMED` correlation and an alpha-derived mask when the template PNG has transparency. Templates are loaded with `IMREAD_UNCHANGED` to preserve alpha. If alpha exists, opaque pixels form the match mask; transparent pixels are ignored during correlation. Crops the search ROI from the frame, matches against the loaded template, thresholds the max correlation. Above threshold: `pin_visible=True`, `pin_position` is the match location's center in full-frame coordinates. Below threshold: `pin_visible=False`, `pin_position=None`.
- **Runtime config (from `navigation.yaml`):**
  - `minimap_pin_template_path: str` — path relative to config directory. Default: `minimap_pin_template.png`.
  - `minimap_pin_search_roi_x1: int` — left edge of search ROI (pixel column).
  - `minimap_pin_search_roi_y1: int` — top edge of search ROI (pixel row).
  - `minimap_pin_search_roi_x2: int` — right edge of search ROI.
  - `minimap_pin_search_roi_y2: int` — bottom edge of search ROI.
  - `minimap_pin_match_threshold: float` — correlation floor for pin_visible=True. Starting value: 0.7.
  - `minimap_pin_detector_cadence: int` — run detector every N frames. Starting value: 1 (every frame; UI element is cheap to detect and freshness matters).
- **Starting ROI values (Phase 4a.1 baseline, from real minimap measurement):**
  - `minimap_pin_search_roi_x1: 1590`
  - `minimap_pin_search_roi_y1: 41`
  - `minimap_pin_search_roi_x2: 1922`
  - `minimap_pin_search_roi_y2: 271`
- **Do-NOT guardrails:** no literals for ROI or threshold; no OpenCV drawing; do not consume from GameState (produces state, doesn't consume); do not modify the frame in place.
- **Complexity:** L. Straightforward template match with configurable ROI and threshold.
- **Acceptance:** offline diagnostic (`scripts/diag_minimap_pin_tuner.py`) runs the detector across a recorded run and reports per-frame `pin_visible` and max correlation. Manual review confirms the detector correctly identifies pin-visible vs pin-absent frames throughout a Phase 4a-style navigation to a pinned destination.

---

## 6. Game State Layer

### F-GS-1 — GameState snapshot (`src/d4_bot/state.py`)

- **Purpose:** The single typed truth-per-tick that decision logic reads (ADR-005).
- **Origin:** Redesigned from game_bot's GameStateManager (bus removed).
- **Surface (spec):** frozen dataclass `GameState`:
  - `frame_id: int`, `timestamp: float`
  - `character_moving: bool`, `character_moving_frame_id: int` (origin of the reading)
  - `nav_arrows: list[Detection]`, `nav_arrows_frame_id: int | None` (origin; None until first inference)
  - Future stubs (declared now, always default/False until their detectors exist): `enemy_present: bool = False`, `screen_mode: str = "hud"`.
  - Helper: `staleness(self, field_frame_id: int) -> int` returning `self.frame_id - field_frame_id`.
- **Complexity:** L. **Acceptance (unit test):** construction, immutability, staleness math.

### F-GS-2 — StateDiff (`src/d4_bot/state.py`)

- **Purpose:** Edge detection between consecutive snapshots — the replacement for game_bot's events.
- **Surface (spec):** `diff(prev: GameState | None, curr: GameState) -> StateDiff` with boolean fields named after the old events where meaningful: `movement_started`, `movement_stopped`, `nav_guide_appeared`, `nav_guide_lost`, `enemy_appeared` (future-live). `prev=None` yields all-False.
- **Complexity:** L. **Acceptance (unit test):** table-driven edges.

### F-GS-3 — GameStateUpdater (`src/d4_bot/state.py`)

- **Purpose:** The per-tick step that feeds the frame to every detector (each honoring its own cadence internally) and assembles the snapshot.
- **Surface (spec):** `GameStateUpdater(detectors: dict[str, object])` with `update(frame: StampedFrame) -> GameState`.
- **Do-NOT guardrails:** no decision logic here; no action emission; no detector construction.
- **Complexity:** L–M. **Acceptance (replay-testable):** on a recorded walk sequence, snapshots show `character_moving` transitions and nav_arrow staleness never exceeding the configured cadence.

---

## 7. Navigation Layer (the milestone)

### F-NAV-1 — NavigationProcessor (`src/d4_bot/processors/navigation.py`)

- **Purpose:** The continuous `FrameProcessor` that walks the character to a human-pinned map marker by steering toward the on-screen nav guide, detecting stuckness, recovering, and stopping on arrival (ADR-006, ADR-010).
- **Layer:** d4_bot.
- **Origin:** Redesigned from game_bot's NavigationManager (threaded → synchronous; minimap planning → arrow steering).
- **Consumes:** `FrameProcessor` ABC; `GameStateUpdater`; `StateDiff`; command registry payloads; `FrameHistory`; `capture.latency_frames` (injected at construction — the processor never sees a literal).
- **Runtime config (`configs/navigation.yaml`, layered per season via load_layered_config):**
  - `arrival_confirm_ticks: int` — sustained `both_lost` ticks required for ARRIVED under compound-signal arrival (see ADR-015). Starting value: 24 (400 ms). Previously 120 under nav_arrow-only heuristic; dropped because compound-signal false-positive risk is much lower.
  - `burst_duration_ms: int` — length of each steering move_duration burst (F-CTL-2).
  - `character_anchor_x: int` — pixel column of the character's on-screen render position at the configured capture resolution.
  - `character_anchor_y: int` — pixel row of the character's on-screen render position at the configured capture resolution.
  - `emission_interval_ms: int` — how often a new steering burst is emitted (F-CTL-2 continuous emission per ADR-014). Must be less than `burst_duration_ms` so bursts overlap and firmware never self-releases during normal operation. Starting value: 200.
  - `nav_arrow_only_arrival_backstop_ticks: int` — safety-net timeout: if nav_arrows have been lost this long, fire arrival regardless of pin state (protects against pin detector failure). Starting value: 300 (5 seconds at 60fps). Per ADR-015.
  - `nav_arrow_min_confidence: float` — floor applied on top of the detector's own threshold; defense against the known nav_arrow false-positive shelf (QUESTIONS.md, pending retrain). Detections below the floor are treated as absent for steering purposes.
  - `search_grace_ticks: int` — SEARCHING hold before terminal `guide_lost`.
  - `stale_direction_tolerance_ticks: int` — number of ticks the processor will continue emitting bursts using the last known good direction when detection is stale (F-CTL-2 / ADR-014). Beyond this tolerance, emission is skipped and the firmware self-releases the stick. Starting value: 3.
  - `significant_direction_change_degrees: float` — angle threshold below which a new burst's direction is considered a "small correction" rather than a "significant direction change." Verdict gating anchors on the last significant change, not every emission. Starting value: 15.0.
  - `<any additional keys you actually injected — list them all; the spec is the schema>`
  No literal for any of these anywhere in Python.
- **Surface (spec):** `NavigationProcessor(updater, state_differ, commands, latency_frames: int, config: dict)` implementing `process(frame: StampedFrame, services: ProcessorServices) -> Action | None`. FrameHistory is reached via `services`, not passed directly (ADR-019).
- **State machine (explicit, an enum):**
  - `STEERING` — nav arrows fresh → compute steering vector → emit movement burst → enter pre-effect window.
  - `PRE_EFFECT` — verdict-gating window relative to the most recent significant direction change (see F-NAV-2). During PRE_EFFECT, the processor continues emitting steering bursts on the emission cadence (this is where the character keeps walking; emission is not gated). No verdicts (no stuck, no arrival, no correction against the just-issued significant change) are evaluated within `latency_frames + <resolution TBD by implementation, likely bounded to a small integer of ticks>` of the change. Detectors keep updating state throughout. The pre-effect window ends when the freshest state reflects post-change reality, per F-NAV-2's frame_id arithmetic. See ADR-014.
  - `SEARCHING` — nav arrows stale/absent outside the pre-effect window and *without* recent-movement context: hold position for `search_grace_ticks` (config). Guide reappears → `STEERING`; still lost after the grace period → terminal status `guide_lost`. (No scan maneuver: the camera is fixed, so waiting is the only honest search; the recent-movement case belongs to the arrival condition below.)
  - `STUCK_RECOVERY` — delegated to F-NAV-3's ladder; returns to `STEERING` on success.
  - `ARRIVED` — terminal; emits nothing; sets a done flag the entry script polls (mirroring `interpreter.status` in the diablo_bot scripts).
- **Arrival condition (spec):** `nav_guide_lost` AND `pin_lost` sustained simultaneously for `arrival_confirm_ticks` (config; starting value 24 = 400 ms under compound-signal design). Distinguished from `SEARCHING`'s lost-guide case by recent-movement context. See ADR-015 for compound-signal rationale and Interpretation A timing model. Backstop: if `nav_arrows` alone have been lost for `nav_arrow_only_arrival_backstop_ticks` (config; starting value 300 = 5 seconds), arrival fires regardless of pin state to prevent hangs if the pin detector itself fails.
- **Do-NOT guardrails:** no threads; no sleeps (BotLoop owns time); no direct UDP; no OpenCV drawing; no literals for latency/durations/thresholds (all injected config); never query detectors directly (GameState only).
- **Complexity:** **H** — this is the phase where Copilot most needs the spec pasted whole.
- **Acceptance (live):** with a marker pinned ≥ 30 seconds of travel away across at least one obstacle: the character reaches the marker; ≥ 1 stuck-recovery is induced (walk it into a wall corner mid-run) and survived; the processor reaches `ARRIVED` and the script exits cleanly. Three consecutive successful runs.

### F-NAV-2 — Steering law (internal to F-NAV-1)

- **Purpose:** arrows → direction. Take the highest-confidence fresh detection, compute bearing of its bbox center relative to screen center / character anchor, map to stick angle.
- **Latency handling (spec):** detections lag reality by `latency_frames`; under overlapping-burst emission (ADR-014), direction is computed from the freshest detection whose origin frame_id postdates the *most recent significant direction change*, plus latency_frames. Detections older than that are treated as stale for direction purposes. Correction gain: full re-aim on every emission (no incremental gain tuning; emission cadence is short enough that oscillation is not a risk). Additionally, if all available detections are stale, the last known good direction is reused for up to `stale_direction_tolerance_ticks` before emission is skipped, per F-CTL-2's stale-direction tolerance.
- **Complexity:** M. **Acceptance:** folded into F-NAV-1.

### F-NAV-3 — StuckMonitor + RecoveryLadder (`src/d4_bot/recovery.py`)

- **Purpose:** Decide "stuck" from minimap motion and execute the ordered escalation ladder (ADR-009, §8.4 of ARCHITECTURE).
- **Origin:** Feature intent carried from game_bot (its recovery patterns worked; its axis-variance stuck signal is replaced by minimap motion, which was the stable signal per intake).
- **Stuck definition (spec):** `stuck_ticks` consecutive ticks (config; start ~45 ≈ 0.75 s) where a movement burst is active or just completed, the pre-effect window has passed, and `character_moving` is False.
- **Impact from ADR-014:** the "movement burst active or just completed" anchor in the stuck definition needs revision under the overlapping-emission model (bursts are continuous; "just completed" is not meaningful). Proposed replacement anchor: "a steering burst was emitted with non-zero intended stick magnitude within the last N ticks (config: `stuck_movement_window_ticks`)." Final wording deferred to Phase 4b implementation session; this bullet flags the change so Phase 4b's spec review catches it.
- **Ladder (spec):** ordered rungs, each = (named command sequence from buttons.yaml, post-check delay respecting pre-effect, max attempts before escalating): 1) reverse burst — parametric movement opposite the last steering vector, emitted via the steering helper (no named command involved), then re-steer; 2) offset-angle re-approach — re-steer with a configured angular offset applied to the guide bearing (alternating ±, offset value from config; this is movement-direction rotation via the steering helper — D4's camera is fixed); 3) `press_b` escape + re-steer; 4) terminal fail → processor stops with status `stuck_unrecoverable` (re-pin fallback deferred — it needs map interaction we haven't built). Ladder resets to rung 1 after any post-recovery window with confirmed movement.
- **Surface (spec):** `StuckMonitor(latency_frames: int, config: dict)` with `update(state: GameState, movement_active: bool) -> bool`; `RecoveryLadder(commands, config)` with `next_action() -> Action | None` and `report_outcome(moved: bool) -> None`.
- **Complexity:** M–H. **Acceptance (live):** walking deliberately into a wall triggers rung 1 within ~1.5 s of visible stop; ladder escalates on repeated failure; recovers and resumes steering in the corner-obstacle test.

---

## 8. Combat Layer

M1 scope is defensive combat only (not area-clear): detect target acquisition from the game's targeting HUD, run a loadout rotation, verify kills with latency-aware gating, sweep for off-cone targets, and report terminal outcomes (`combat_clear`, `combat_timeout`, `character_dead`).

### F-DET-4 — Enemy health-bar presence detector

- **Purpose:** Detect whether the game's targeting UI health bar is present, providing the canonical combat engagement signal for `GameState.enemy_present`.
- **Layer:** d4_bot detector wiring (`src/d4_bot/detectors/`) using framework detector primitives.
- **Origin:** New detector policy chosen for M1 combat: rely on stable HUD targeting UI rather than visual monster detection.
- **Surface (spec):** `EnemyHealthBarDetector(config: dict)` implementing the framework detector interface.
- **Method:** ROI-constrained template/color detection over the enemy-target health-bar UI region. The detector returns a boolean presence verdict and a confidence-like score used for diagnostics.
- **Runtime config (combat detector YAML):**
  - `enemy_health_bar_roi: [x, y, w, h]` — named via `rois.yaml` indirection at build time; no coordinates in Python.
  - `enemy_health_bar_threshold: float` — minimum match/confidence to classify as present.
  - `enemy_health_bar_hysteresis_ticks: int` — debounce to prevent one-frame flicker.
  - `enemy_health_bar_cadence: int` — detector cadence in frames.
  - `enemy_health_bar_variant: str` — selector for measured variant set (`normal`, `elite`) when separate templates are needed.
- **Outputs:**
  - `enemy_present: bool` — debounced verdict.
  - `enemy_health_bar_score: float` — raw detector score for tuning and logs.
  - `enemy_health_bar_frame_id: int` — origin frame of the current reading for staleness checks.
- **Do-NOT guardrails:** no monster-body/YOLO logic, no direct GameState mutation, no coordinate literals in code, no drawing side effects.
- **Complexity:** M.
- **Acceptance (live and replay):** with captured targeted/non-targeted sequences, detector cleanly separates bar-present vs bar-absent states; with intentional one-frame noise, debounced output does not flicker; elite/normal variants are both detected according to measured configuration.

### F-DET-5 — Health globe fill detector

- **Purpose:** Estimate player survivability by reading the health globe fill level and exposing `health_fill_fraction` for potion policy.
- **Layer:** d4_bot detector wiring (`src/d4_bot/detectors/`) over framework color/ROI mechanisms.
- **Origin:** New for unattended-farming survivability in M1.
- **Surface (spec):** `HealthGlobeFillDetector(config: dict)` implementing the framework detector interface.
- **Method:** ROI crop of the health globe plus color-mask sampling to estimate filled pixels as a fraction in `[0.0, 1.0]`; boolean low-health verdict is computed from configured threshold.
- **Runtime config (combat detector YAML):**
  - `health_globe_roi: [x, y, w, h]` — ROI name resolved through `rois.yaml`.
  - `health_globe_color_lower` / `health_globe_color_upper` — HSV/BGR bounds used by the mask pipeline.
  - `health_globe_fill_threshold: float` — potion trigger threshold (for example, drink when fill <= threshold).
  - `health_globe_hysteresis_ticks: int` — debounce around the threshold crossing.
  - `health_globe_cadence: int` — detector cadence.
- **Outputs:**
  - `health_fill_fraction: float` — normalized fill estimate.
  - `health_low: bool` — debounced threshold verdict consumed by combat policy.
  - `health_globe_frame_id: int` — origin frame for latency-aware decision gating.
- **Do-NOT guardrails:** no potion emission in detector code, no hardcoded thresholds in Python, no full-screen processing.
- **Complexity:** L–M.
- **Acceptance (live):** during controlled damage intake and healing, `health_fill_fraction` tracks visible globe depletion/refill and `health_low` toggles only after configured hysteresis, with no chatter around boundary values.

### F-DET-6 — Revive-screen detector

- **Purpose:** Detect player-death revive UI and provide an immediate terminal condition for combat (`character_dead`).
- **Layer:** d4_bot detector wiring (`src/d4_bot/detectors/`) using framework template detection.
- **Origin:** New for M1 failure-mode handling.
- **Surface (spec):** `ReviveScreenDetector(config: dict)` implementing the framework detector interface.
- **Method:** template match on a stable revive-screen element within configured ROI; optional multi-template support for localized or seasonal UI variants.
- **Runtime config (combat detector YAML):**
  - `revive_screen_roi: [x, y, w, h]` — named ROI resolved via `rois.yaml`.
  - `revive_screen_templates: list[str]` — one or more template asset paths.
  - `revive_screen_threshold: float` — minimum match score.
  - `revive_screen_hysteresis_ticks: int` — debounce so transient overlays do not false-trigger death.
  - `revive_screen_cadence: int` — detector cadence.
- **Outputs:**
  - `revive_visible: bool` — debounced death-screen presence.
  - `revive_score: float` — best raw score over active templates.
  - `revive_frame_id: int` — origin frame for state staleness checks.
- **Do-NOT guardrails:** no auto-revive behavior in detector; detector only reports state.
- **Complexity:** L.
- **Acceptance (live and replay):** revive UI is reliably detected when dead, absent during normal HUD operation, and remains stable under transient combat overlays.

### F-CBT-1 — CombatProcessor state machine

- **Purpose:** Synchronous combat control loop that consumes detector-driven `GameState` and emits combat actions until a terminal outcome (`combat_clear`, `combat_timeout`, `character_dead`).
- **Layer:** d4_bot processor (`src/d4_bot/processors/combat.py`) implementing `FrameProcessor`.
- **Origin:** New M1 processor design, aligned with defensive-combat scope and honest-failure terminal statuses.
- **Consumes:** `GameStateUpdater`, `StateDiff`, command registry payloads, and `capture.latency_frames` (or injected `latency_frames`) for all verdict-gating windows.
- **Surface (spec):** `CombatProcessor(updater, state_differ, commands, latency_frames: int, config: dict, loadout: dict)` implementing `process(frame: StampedFrame, services: ProcessorServices) -> Action | None`.
- **State machine (explicit enum):**
  - `IDLE` — watch for `enemy_appeared` edge from F-DET-4.
  - `ENGAGE` — preserve/acquire facing that produced targeting; initialize attack rotation context.
  - `ATTACKING` — execute F-CBT-2 loadout steps while enemy health-bar remains present.
  - `KILL_VERIFY_PRE_EFFECT` — after a candidate kill/loss signal, hold verdicts until the latency gate expires.
  - `SWEEP` — short facing sweeps to reacquire off-cone targets; reacquire returns to `ENGAGE`, completed sweep with no target returns `combat_clear`.
  - `TERMINAL` — no emission; exposes terminal status to the entry script.
- **Latency-gating contract (hard rule):**
  - No kill, stuck, or arrival-style verdict may evaluate inside the post-action pre-effect window.
  - The gate duration is computed from runtime `latency_frames` plus action duration where applicable; no literal frame counts in processor logic.
  - Mid-fight health-bar loss shorter than the gate is treated as transient loss/reposition, not kill confirmation.
- **Failure outcomes:**
  - `combat_timeout` when target presence persists beyond configured engage timeout.
  - `character_dead` when F-DET-6 reports revive-screen presence beyond hysteresis.
- **Runtime config (`configs/navigation.yaml` or dedicated combat config):**
  - `combat_engage_timeout_ticks: int`
  - `combat_sweep_step_duration_ms: int`
  - `combat_sweep_steps: int`
  - `combat_post_action_verify_ticks: int` (additional guard beyond `latency_frames` where needed)
  - `combat_tick_cadence_divisor: int` (optional cadence for costly checks)
- **Do-NOT guardrails:** no threads/async/sleeps, no direct UDP calls, no detector bypasses, no latency literals.
- **Complexity:** H.
- **Acceptance (live):** three consecutive combat-only sessions: all spawned normals are engaged and killed; off-cone enemies are reacquired by sweep; clear state exits as `combat_clear`; induced obstruction exits cleanly as `combat_timeout`; forced death exits as `character_dead`.

### F-CBT-2 — Loadout rotation with gate fields

- **Purpose:** Define and execute an ordered per-build combat rotation where each step may be conditionally gated by resource/cooldown predicates.
- **Layer:** d4_bot combat policy data + runner (`src/d4_bot/combat/loadout.py` and config YAML under `configs/`).
- **Origin:** New, with gate architecture intentionally present even though v1 defaults to ungated presses.
- **Surface (spec):**
  - `CombatLoadout` schema loaded from YAML.
  - `LoadoutRunner(loadout: dict, commands: CommandRegistry, config: dict)` with `next_action(state: GameState) -> Action | None`.
- **YAML schema (ordered `rotation` list):** each entry includes
  - `command: str` — semantic command name from `buttons.yaml`.
  - `delay_ticks: int` — delay before this step may fire again.
  - `gate: str` — one of `none`, `resource`, `cooldown`.
  - `gate_field: str | null` — state field the gate evaluates (required when gate != `none`).
  - `gate_threshold: float | null` — threshold comparator value for numeric gates.
  - `gate_polarity: str | null` — `gte` or `lte` for threshold semantics.
- **Gate semantics:**
  - `none`: always eligible when timing allows.
  - `resource`: eligible only if the bound resource field satisfies threshold/polarity.
  - `cooldown`: eligible only if the bound cooldown-ready field indicates ready state.
- **v1 operating policy:** all shipped M1 entries use `gate: none` by default; gate fields are mandatory schema support for evidence-driven upgrades without redesign.
- **Execution rules:**
  - Preserve list order cyclically.
  - Skip (do not block) ineligible gated entries and evaluate the next step.
  - Never emit multiple button actions in one tick.
  - All press durations live in `buttons.yaml`; loadout never hardcodes firmware timings.
- **Do-NOT guardrails:** no implicit command name remapping, no hardcoded build assumptions, no direct detector reads outside `GameState`.
- **Complexity:** M.
- **Acceptance:** with an M1 loadout configured to `gate: none`, combat runs stable timed rotation; with synthetic state fixtures, `resource` and `cooldown` gates correctly suppress/allow only the targeted steps.

### F-CBT-3 — Combat entry script (`scripts/run_combat.py`)

- **Purpose:** Dedicated live harness for M1 combat verification with navigation disabled, so combat behavior is testable in isolation.
- **Layer:** d4_bot flow script.
- **Origin:** New entry-point parallel to `run_nav.py`.
- **Behavior:**
  - Loads layered config and season overrides.
  - Builds capture, controller output, command registry, detectors, `GameStateUpdater`, loadout, and `CombatProcessor`.
  - Runs synchronous `BotLoop` stepping until processor reaches terminal status.
  - Prints terminal status and key counters (`kills`, `sweeps`, `potions_used`, timeout/death reason).
  - Optional `--record` path uses `FrameRecorder` exactly like navigation flow, without modifying `BotLoop` internals.
- **CLI flags (minimum):**
  - `--season <name>`
  - `--config-dir <path>`
  - `--loadout <name-or-path>`
  - `--record` and recording output options consistent with existing flow conventions
- **Do-NOT guardrails:** no concurrent NavigationProcessor in M1 script, no background threads, no hidden fallback configs.
- **Complexity:** M.
- **Acceptance (live):** combat-only run exits with one of the declared terminal statuses and prints enough structured output for `verify_phase_*` style pass/fail checks.

---

## 9. Flow Layer / Entry Points

### F-FLOW-1 — `scripts/run_nav.py`

- **Purpose:** Live entry point: load layered config → build capture/output/commands/detectors/updater → construct NavigationProcessor → BotLoop start/step until processor reports terminal status → clean stop. Flags: `--record` (enables FrameRecorder), `--season`, `--config-dir`.
- **Origin:** Carried pattern from `run_farm_v1.py` (including the printed `latency_frames` banner and the step-until-status loop).
- **Complexity:** M. **Acceptance:** is itself the harness for F-NAV-1's acceptance.

### F-FLOW-2 — `verify_phase_N.py` convention

- **Purpose:** One executable acceptance check per BUILD_PLAN phase (ADR-011). Each prints PASS/FAIL lines per criterion and exits nonzero on any FAIL; live-only checks prompt the operator to confirm observed behavior (y/n) rather than pretending to automate the unautomatable.
- **Complexity:** L each. **Acceptance:** self-evident.

---

## 10. Diagnostics (first-class deliverables, built early)

| ID | Script | Purpose | Acceptance |
|---|---|---|---|
| F-DIAG-1 | `diag_roi_viewer.py` | Live capture window with every `rois.yaml` region outlined + named. The tool for placing `minimap` and `nav_arrow_window`, and for seasonal re-checks. | Every named ROI visibly matches its region on the live HUD. **Complexity L.** |
| F-DIAG-2 | `diag_detector_tuner.py --detector <name>` | Live view of one detector: raw + debounced output for `roi_motion`, drawn boxes + confidences for `yolo`, pixel counts for `color_match`. Prints current YAML values so tuned numbers can be copied back into config (the tool never writes config). | For `minimap_motion`: standing still shows False, walking shows True, on screen in real time. **Complexity M.** |
| F-DIAG-3 | `diag_udp_echo.py --command <name>` | Loads buttons.yaml + command registry, fires one named command through `UDPXboxOutput`, prints the payload sent. The button-mapping truth test. | Each nav-milestone command produces the correct visible in-game act. **Complexity L.** |
| F-DIAG-4 | `capture_icons.py --roi <name> --out <season_dir>` | Grabs cropped template images from live capture on keypress into a season icons folder — the seasonal refresh capture tool (F-CFG-5). | A captured crop is immediately usable by TemplateMatchDetector. **Complexity L.** |

Shared guardrail for all diagnostics: read-only with respect to configs; no controller output except F-DIAG-3's single explicit command; safe to run while the game sits idle.

---

## 11. Dependency Graph (build-order truth)

- FG-4 → F-CFG-* loaders → everything.
- FG-1 + F-DET-2 → nav_arrow detection → F-GS-3 → F-NAV-1/2.
- FG-2 → minimap_motion → F-NAV-3.
- F-CTL-1 → F-DIAG-3 → F-CTL-2 → F-NAV-1.
- FG-3 → recorded datasets → replay-testable acceptances (FG-1, FG-2, F-GS-3).
- F-DIAG-1 → F-CFG-2 values → every ROI-consuming detector.

BUILD_PLAN.md sequences phases along this graph.

---

*End of FEATURE_SPECS.md. Next document: BUILD_PLAN.md.*
