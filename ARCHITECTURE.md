# ARCHITECTURE.md — d4_bot

**Status:** Living document. The north star for all design decisions in this repo.
**Audience:** Future-me and GitHub Copilot (via pasted sections and `copilot-instructions.md`).
**Companion documents:** FEATURE_SPECS.md (what to build), BUILD_PLAN.md (in what order), COPILOT_PROMPTS.md (how to prompt it), TROUBLESHOOTING.md (how to recover).
**Rule zero:** When generated code contradicts this document, the code is wrong.

---

## 1. Purpose and Repo Ecosystem

`d4_bot` is a full-featured Diablo 4 automation bot built as a pure consumer of `bot_framework`. It is the permanent home for all Diablo 4 automation going forward.

### 1.1 The repos and their roles

| Repo | Role | Rule |
|---|---|---|
| `bot_framework/` | Game-agnostic substrate. Capture, output, timing, content loops, detection mechanisms. | Import it. Never reimplement it. Missing mechanisms get **added to it**, never worked around in the game repo. |
| `d4_bot/` | **This repo.** All Diablo 4 game knowledge: ROIs, thresholds, YOLO models, button maps, YAML loops, navigation logic. | No framework mechanism code lives here. If a class would work for another game, it belongs in `bot_framework/contrib/`. |
| `diablo_bot/` | Legacy fishing farm v1. Reference example of clean framework consumption. | Read-only reference. Will be absorbed into `d4_bot` as a YAML activity in a later phase, then archived. |
| `game_bot/` | Previous-generation D4 bot. Feature reference only. | Never port code. Port *feature intent*, re-architected onto the framework. Its YOLO nav-arrow model and icon assets are reusable **data**. |

### 1.2 Repo naming convention (standing convention for all future bots)

- One long-lived repo per game: `<game>_bot` — `d4_bot`, `halo_bot`, etc.
- Activities (fishing, navigation, dungeon farming) are content *inside* the game repo, not new repos.
- Generations live in git history and tags, not in repo names.
- Every game repo is a sibling of `bot_framework/` on disk and installs it editable: `pip install -e ../bot_framework`.

### 1.3 Environment

- Python ≥ 3.10, Windows.
- Both packages installed editable into the same venv: `pip install -e ../bot_framework[ml]` then `pip install -e .` from the `d4_bot` root.
- `bot_framework` is tracked on **main**, not a pinned tag (see ADR-003). Every completed build phase records the framework commit hash it was validated against in the phase's entry in BUILD_PLAN.md. The framework gets a version tag at each bot milestone.

---

## 2. Repo Structure

```
d4_bot/
├── .github/
│   └── copilot-instructions.md   # Standing preamble; Copilot agent mode reads this automatically
├── ARCHITECTURE.md                # This file
├── FEATURE_SPECS.md
├── BUILD_PLAN.md
├── COPILOT_PROMPTS.md
├── TROUBLESHOOTING.md
├── README.md
├── pyproject.toml                 # Package metadata; depends on bot_framework[ml]
│
├── configs/                       # ALL game knowledge as data. YAML only. No JSON.
│   ├── hardware.yaml              # Capture device index/backend/resolution, UDP IP/port. Rig facts, zero game knowledge.
│   ├── buttons.yaml               # Semantic name → firmware command mapping (see §5, §10)
│   ├── rois.yaml                  # Named screen regions. The ONLY place pixel coordinates may appear.
│   ├── detectors/                 # One YAML per detector: thresholds, ROI name refs, cadence
│   │   ├── nav_arrow.yaml
│   │   ├── minimap_motion.yaml
│   │   └── ...
│   ├── loops/                     # YAML content loops for scripted sequences (framework interpreter)
│   │   └── ...
│   └── seasons/                   # Season-specific assets and overrides (see §9.3)
│       └── s09/                   # D4 season number, zero-padded
│           ├── icons/             # Template images captured this season
│           └── overrides.yaml     # Keys that override base configs for this season
│
├── models/                        # YOLO weights and class maps. Game DATA, not code.
│   └── nav_arrow/
│       ├── best.pt                # Carried forward from game_bot (no retraining needed)
│       └── classes.yaml           # Class index → name map, confidence thresholds
│
├── src/d4_bot/
│   ├── __init__.py
│   ├── state.py                   # GameState snapshot dataclass + snapshot differ (§7)
│   ├── commands.py                # build_command_registry(): buttons.yaml → CommandRegistry
│   ├── detectors.py               # build_detector_registry(): detector YAMLs → DetectorRegistry
│   ├── processors/
│   │   ├── navigation.py          # NavigationProcessor (FrameProcessor) — the continuous milestone behavior
│   │   └── ...                    # Future continuous behaviors (combat, etc.)
│   └── recovery.py                # Stuck-recovery escalation ladder (§8.4)
│
├── scripts/
│   ├── run_nav.py                 # Live entry point for the navigation milestone
│   ├── diag_roi_viewer.py         # Diagnostic: overlay named ROIs on live capture
│   ├── diag_detector_tuner.py     # Diagnostic: live-tune one detector's thresholds
│   ├── diag_udp_echo.py           # Diagnostic: fire one named command, confirm firmware receipt
│   ├── record_dataset.py          # Capture-only recording harness (FrameRecorder wrapper; §11.3)
│   ├── capture_icons.py           # Seasonal asset refresh helper (§9.3)
│   └── verify_phase_N.py          # One executable acceptance check per build phase (§11.2)
│
├── frames/                        # Recorded frame datasets (gitignored; produced by FrameRecorder)
└── tests/                         # Offline unit tests (state differ, config loaders, steering math)
```

### 2.1 Additions to bot_framework (built as part of this project)

```
bot_framework/
└── framework/contrib/
    ├── ml/                        # NEW optional tier, installed via bot_framework[ml] extra
    │   └── (YOLO detector wrapper — game-agnostic inference mechanism, §8.2)
    └── recording/                 # NEW
        └── (FrameRecorder — dumps frames + action log during live runs, §11.3)
```

The framework core keeps its stdlib + numpy dependency boundary. Everything with heavier dependencies (ultralytics/torch, OpenCV beyond what contrib already uses) lives behind the `[ml]` extra. FEATURE_SPECS.md carries the full framework-gaps registry.

---

## 3. Framework Consumption Rules

1. **Import, never reimplement.** The allowed import surface (as of framework main, 2026-07):
   - `framework.interfaces` — `CaptureSource`, `OutputDevice`, `FrameProcessor`, `StampedFrame`, `Action`
   - `framework.loop` — `BotLoop`
   - `framework.temporal` — `FrameHistory`, `TemporalAligner`
   - `framework.contrib.hardware` — `AVerMediaCapture`, `UDPXboxOutput`, `ReplayCapture`
   - `framework.contrib.detection` — `ColorMatchDetector`, `TemplateMatchDetector`
   - `framework.contrib.content_loops` — `ContentLoopProcessor`, `CommandRegistry`, `DetectorRegistry`, `load_loops_from_file`
   - `framework.contrib.ml` — (once built) the YOLO detection wrapper
   - `framework.contrib.recording` — (once built) `FrameRecorder`
2. **If a mechanism is missing, it goes into the framework.** The test: "would this class work unchanged for Halo?" Yes → `bot_framework/contrib/`. No → `d4_bot/src/`.
3. **Game knowledge never leaks into the framework.** No D4 ROIs, icon paths, button semantics, or thresholds in `bot_framework` — not even as defaults.
4. **The latency gate is inviolable.** `wait_visual` and `branch` refuse to evaluate visual conditions within `latency_frames` ticks of any `command` step. Never work around it; the same discipline applies to custom processors (§4.3).
5. **Copilot is permitted to modify `bot_framework`** — but only in phases explicitly scoped as framework phases in BUILD_PLAN.md, with their own acceptance scripts.

---

## 4. Timing Rules (the most violated constraint — read twice)

### 4.1 The capture latency fact

OpenCV capture on this rig is **6 frames behind real time** (measured empirically with `LatencyCalibrator`; at 60 fps that is ~100 ms). Any action's visible effect takes that many frames to appear in captured frames.

### 4.2 The three binding rules

1. **Never hardcode the value.** All code pulls `capture.latency_frames` at runtime from the `CaptureSource`. The number 6 may appear in exactly two places: `hardware.yaml` (as the declared value passed to `AVerMediaCapture`) and this document (as documentation). If Copilot writes a literal 3 or 6 into logic, the code is wrong. (A stale "3 frames" exists in old context files — it is wrong; the measured value is 6, and it doesn't matter anyway because code never uses the literal.)
2. **No visual conclusion about an action within `latency_frames` ticks of issuing it.** This is what the framework's latency gate enforces for YAML loops.
3. **Duration commands shift the window.** A `move_duration` of 500 ms ends in the real world at t+500 ms, but its visible *end* appears at t+500 ms+`latency_frames`. Post-action evaluation windows start from command *completion*, not command *issue*.

### 4.3 Latency discipline in custom processors

Continuous processors (e.g., `NavigationProcessor`) don't run inside the YAML interpreter, so they don't get the latency gate for free. They must implement the same invariant themselves:

- After emitting any action expected to change the scene, the processor enters a **pre-effect window** of `latency_frames` ticks (plus the command's duration, converted to ticks, for duration commands).
- Within the pre-effect window: no steering corrections in reaction to the emitted command, no stuck-detection verdicts, no arrival verdicts. Detectors may still *run* and update state; the processor just may not *conclude* from state that the command failed or succeeded.
- `FrameHistory` is the tool for asking "what did I command N frames ago?" — use it rather than ad-hoc local buffers.

### 4.4 Quick reference

| You want to... | Rule |
|---|---|
| Check whether a button press had a visible effect | Wait ≥ `latency_frames` ticks after the command's real-world completion |
| Steer continuously while moving | Corrections react to detections; detections lag reality by `latency_frames` — bake this into gain/damping choices |
| Detect "stuck" | Only evaluate minimap motion over windows that exclude the pre-effect window of the most recent movement command |
| Debug "detector never fires" | First suspect: evaluating during the latency-gated window. See TROUBLESHOOTING.md |

---

## 5. Firmware v2.1 Command Contract

- Transport: JSON packets over UDP to the Arduino at the IP/port in `hardware.yaml` (currently `192.168.1.196:5005`), sent via `UDPXboxOutput`. Response port 5006.
- **All commands are single-packet and self-releasing** via duration parameters: `button_N_duration`, `hat_duration`, `move_duration`, `trigger_duration`. The firmware handles release timing internally.
- **Never emit two-packet press/release pairs from the game side.** If generated code contains separate press and release actions, it is wrong — full stop.
- Button index map (firmware truth): `button_0` = X, `button_1` = A, `button_2` = B, `button_3` = Y. `hat_y` positive = up.
- **Button indices never appear in game logic.** Logic refers to semantic names (`press_a`, `dpad_up`, `mount`); `buttons.yaml` owns the name → index/parameter mapping, loaded by `build_command_registry()`.
- The authoritative field-level packet reference is `bot_framework/firmware/xbox_controller/protocol.md`. When Copilot writes or debugs controller code, paste the relevant section of protocol.md alongside the prompt. This document intentionally does not duplicate field names — protocol.md wins.

---

## 6. Threading and Execution Model

### 6.1 The model: synchronous-first

Everything runs inside the single-threaded `BotLoop` tick: capture → record → process → execute → re-record. No background threads. No event loops. No callbacks.

"Navigate while watching for enemies and branching" is achieved single-threaded via **detector cadence scheduling** (§6.2), not concurrency. Rationale: determinism, `FrameHistory` integrity, trivially reproducible bugs, and — bluntly — threads are where Copilot-generated code fails worst and is hardest to review.

### 6.2 Detector cadence scheduling

Every detector declares a `cadence` in its YAML config: run every Nth tick.

| Tier | Detectors | Cadence | Budget rationale |
|---|---|---|---|
| 0 | ROI color/template detectors, minimap motion differencing | Every tick | Sub-millisecond each on small ROIs |
| 1 | YOLO nav-arrow inference | Every 2nd–3rd tick (tuned empirically) | RTX 4070 Ti comfortably sustains this at 1280 input; steering does not need 60 Hz updates |

On ticks where a detector doesn't run, its last-known result persists in the `GameState` snapshot with its `frame_id` of origin, so consumers always know how stale a reading is.

### 6.3 The escalation trigger (the only sanctioned thread)

If sustained loop FPS drops below **45 fps averaged over 5 seconds** (with 60 fps capture), the one permitted structural change is: move capture into a background thread with a latest-frame mailbox, keeping process/execute synchronous. This requires a new ADR entry before implementation. Nothing else in the system is ever threaded without a dedicated design session.

---

## 7. Game State Model — Polled Snapshot, No Event Bus

`game_bot`'s event bus (GameStateManager + pub/sub events) is **not** carried forward. Replaced by:

- **`GameState`**: a plain dataclass snapshot produced once per tick. Typed fields only — e.g., character-moving boolean from minimap motion, latest nav-arrow detections with origin `frame_id`, enemy-present boolean (future), screen-mode enum (future). Every field that comes from a detector carries the `frame_id` it was computed from.
- **Writers**: detectors, via a thin per-tick update step. **Readers**: decision logic (processors). One direction of flow.
- **Edge detection instead of events**: anything `game_bot` modeled as an event (`mount_change`, `enemy_detected_change`, ...) becomes a comparison between the current and previous snapshot, computed by a `StateDiff` helper in `state.py`. "Enemy appeared" = `prev.enemy_present is False and curr.enemy_present is True`.

Why: fewer moving parts, no callback ordering bugs, deterministic replay, and the pattern is copy-paste portable to every future game — only the field list changes. The event *names* from game_bot survive as diff-field names, preserving the feature intent without the machinery.

---

## 8. Detection and Navigation Architecture

### 8.1 Mechanism vs. data (the reusability line)

| Lives in `bot_framework` (mechanism) | Lives in `d4_bot` (data/wiring) |
|---|---|
| ColorMatchDetector, TemplateMatchDetector | HSV thresholds, template image paths, ROI values |
| YOLO wrapper: load weights, run inference at cadence, return typed detections | Weights file, class map, confidence thresholds, which classes mean what |
| FrameRecorder | When to record, where datasets live |

YOLO *models* are unapologetically game-specific and are treated exactly like ROIs: data files in the game repo. Only the inference machinery is shared.

### 8.2 `framework/contrib/ml` boundary

- Installed via extra: `bot_framework[ml]`. Core framework stays stdlib + numpy.
- The wrapper's contract: given a weights path, a class map, and a cadence, consume `StampedFrame`s and produce a list of typed detections (class name, confidence, bounding box) stamped with the source `frame_id`. Nothing D4-specific.
- Exact signatures are specified in FEATURE_SPECS.md; Copilot builds from that spec, not from ultralytics tutorials.

### 8.3 Navigation milestone architecture

- **Target**: a map marker the human pins before starting the bot. The game then renders an on-screen navigation guide.
- **Steering**: the YOLO nav-arrow detector (model carried forward from `game_bot`; it worked well and needs no retraining) yields arrow position/direction → steering vector → `move_duration` commands. Steering gain and damping account for the `latency_frames` sensor lag (§4.3).
- **Stuck detection**: **minimap motion differencing**. The world view is too noisy for motion detection (the game is visually chaotic even when standing still); the minimap ROI is HUD-locked and only scrolls with actual character translation, making it the stable "am I moving?" signal. This is a *motion sensor*, deliberately distinct from `game_bot`'s discarded MinimapTracker (*position* tracking/route planning), which stays out of scope until a later phase.
- **Arrival**: detected via disappearance/state-change of the pinned-marker guide. Exact condition specified in FEATURE_SPECS.md.
- **Recovery ladder** (§8.4) fires when stuck is confirmed.

### 8.4 Stuck-recovery escalation ladder

Carried forward as feature intent from `game_bot`, re-specified: an ordered list of recovery patterns, each tried with a cooldown and a re-check before escalating — reverse movement → offset-angle re-approach (movement-direction rotation; D4's camera is fixed, so "rotate" never means camera) → B-button escape → clean terminal stop (`stuck_unrecoverable`; the operator restarts the run — re-pin fallback deferred per session decision). Each rung's post-recovery check respects the pre-effect window. Details and tuning values in FEATURE_SPECS.md; the *ladder* structure (ordered, cooldown-gated, escalating) is the architectural commitment.

---

## 9. Configuration Layout

### 9.1 Principles

1. **YAML for all data. Python for wiring only.** No JSON anywhere in this repo (game_bot's JSON libraries are not carried; their contents are hand-translated where still useful).
2. **Pixel coordinates appear only in `rois.yaml`.** Detector configs reference ROIs by name. Code never contains a coordinate literal.
3. **Semantic indirection everywhere**: button names in `buttons.yaml`, ROI names in `rois.yaml`, detector names in `configs/detectors/`, command names in the registry. Copilot writes against names; humans tune values in one place.
4. **1920×1080 @ 60p is the assumed and asserted capture geometry.** Loaders validate frame dimensions at startup and fail loudly on mismatch.

### 9.2 File responsibilities

| File | Owns | Never contains |
|---|---|---|
| `hardware.yaml` | Device index, backend, resolution, fps, declared `latency_frames`, UDP endpoints | Game knowledge |
| `buttons.yaml` | Semantic command name → firmware command form + parameters + default durations | Firmware packet field names (protocol.md's job) |
| `rois.yaml` | Named regions: minimap, HUD slots, detector windows | Thresholds |
| `configs/detectors/*.yaml` | Per-detector: type, ROI name, thresholds, cadence, model path (for YOLO) | Coordinates |
| `configs/loops/*.yaml` | Content-loop programs (framework interpreter schema) | Detector tuning |
| `configs/seasons/sNN/` | Season icon images + `overrides.yaml` | Anything that isn't season-churn |

### 9.3 Seasonal asset refresh (recurring workflow, every ~12 weeks)

Class, build, and some HUD iconography change each D4 season. The standing workflow:

1. Create `configs/seasons/sNN/` for the new season.
2. Run `scripts/capture_icons.py` to grab fresh template crops from live capture into `sNN/icons/`.
3. Add changed thresholds/paths to `sNN/overrides.yaml`. **Precedence: season overrides > base configs**, merged by the config loader at startup (active season set in `hardware.yaml` or CLI flag).
4. Run the detector verification script against fresh captures.
5. Old season folders are kept — they're the regression record and the video-series artifact.

COPILOT_PROMPTS.md carries a paste-ready recurring prompt for this workflow.

---

## 10. Naming Conventions

| Thing | Convention | Examples |
|---|---|---|
| Repos | `<game>_bot` | `d4_bot`, `halo_bot` |
| Files/modules | `snake_case`; diagnostics `diag_*`, phase checks `verify_phase_N.py` | `navigation.py`, `diag_roi_viewer.py` |
| Classes | `PascalCase` with role suffix | `NavigationProcessor`, `RoiMotionDetector`, `FrameRecorder` |
| Functions | `snake_case` verbs; registry builders `build_*` | `build_command_registry()` |
| YAML keys | `snake_case` | `pixel_threshold`, `latency_frames` |
| Detector names (registry) | `snake_case` noun phrase = its config filename | `nav_arrow`, `minimap_motion`, `fishing_indicator` |
| Command names (registry) | `snake_case`, verb-first, semantic not physical | `press_a`, `dpad_up`, `move_forward_short`, `mount` — never `button_1` |
| ROI names | `snake_case` region nouns | `minimap`, `nav_arrow_window`, `hud_health` |
| Season folders | `sNN` (zero-padded D4 season number) | `s09` |
| GameState fields | `snake_case`; booleans as predicates | `character_moving`, `enemy_present` |

---

## 11. Copilot Workflow Integration

### 11.1 Agent mode + committed instructions

Development uses **Copilot agent mode in VS Code** (Pro+), not paste-chat. Consequences:

- The standing preamble lives at `.github/copilot-instructions.md`, which agent mode reads automatically on every task — the 6-frame rule, import surface, firmware contract, and no-reimplementation rules are therefore always in context without pasting.
- Per-phase prompts (COPILOT_PROMPTS.md) become short task briefs that *point at* committed files (FEATURE_SPECS.md sections, this document) rather than embedding everything.
- The five project documents are committed to the repo so the agent can read them directly.

### 11.2 Executable acceptance instead of code review

You've said you don't closely review generated code, and the series benefits from visible LLM mistakes. So correctness enforcement is structural, not eyeball-based:

- **Every build phase ships `scripts/verify_phase_N.py`** — a runnable check that proves the phase's acceptance criterion. A phase is done when its script passes, not when the code looks done.
- **Diagnostic tools are first-class early deliverables**: `diag_roi_viewer.py`, `diag_detector_tuner.py`, `diag_udp_echo.py`. They convert "Copilot made a silent mistake" into "a tool shows the mistake on screen" — which is also better footage.

### 11.3 Recording as a byproduct

Live replay capture is awkward on this rig, so datasets are produced **as a side effect of live runs**: `FrameRecorder` (framework contrib addition) dumps frames + an action log when enabled by flag. Recorded datasets feed `ReplayCapture` for detector tuning and regression. BUILD_PLAN.md tags every acceptance criterion as **replay-testable** or **live-only**; navigation behavior is accepted live.

---

## 12. Decisions Log

Format: dated ADR-style entries, one paragraph each, appended chronologically. Never delete — supersede with a new entry that references the old one.

**ADR-001 (2026-07-07) — Permanent per-game repos, `<game>_bot`.** One long-lived repo per game; activities are content inside it; generations are git history. `d4_bot` is the permanent D4 home; `diablo_bot` (fishing v1) will be absorbed as a YAML activity and archived. Avoids repo sprawl as the series adds games and rebuilds.

**ADR-002 (2026-07-07) — Capture latency is 6 frames, pulled at runtime.** Measured empirically via LatencyCalibrator on this rig. A stale "3 frames" persists in older context documents and is wrong. Binding rule: all logic reads `capture.latency_frames`; the literal appears only in `hardware.yaml` and documentation, so the code stays correct even if remeasurement changes the number.

**ADR-003 (2026-07-07) — Track framework main, not a pinned tag.** This project adds contrib modules to `bot_framework` continuously; tag-pinning would fight that. Mitigation: each completed phase records the framework commit hash it was validated against; the framework is tagged at each bot milestone.

**ADR-004 (2026-07-07) — Synchronous-first execution; cadence scheduling instead of threads.** Concurrent concerns (steer + watch for enemies + branch) are handled by running detectors at per-detector cadences inside the single BotLoop tick. Threads are Copilot's worst failure surface and destroy determinism. Sole sanctioned escalation: capture thread with latest-frame mailbox, triggered only by sustained FPS < 45, and only after a new ADR.

**ADR-005 (2026-07-07) — Polled GameState snapshot; no event bus.** game_bot's pub/sub is replaced by a per-tick typed snapshot plus a StateDiff helper; former events become snapshot-to-snapshot edges. Simpler, deterministic, replay-friendly, and portable to future games by changing only the field list.

**ADR-006 (2026-07-07) — Hybrid processors.** Continuous behaviors (navigation, recovery, future combat) are custom `FrameProcessor`s in the game repo; scripted sequences remain YAML content loops. We do not invent YAML step types to force steering into the interpreter. Composing a continuous processor with a running YAML loop is a known framework gap, deferred past the nav milestone.

**ADR-007 (2026-07-07) — YAML-only configuration; coordinates quarantined in rois.yaml; semantic names everywhere.** game_bot's JSON command libraries are not carried. Button indices, coordinates, and thresholds never appear in logic — only named lookups. Chosen for longevity and portability across future game repos.

**ADR-008 (2026-07-07) — YOLO machinery in `framework/contrib/ml` behind an `[ml]` extra; models are game data.** Preserves the stdlib+numpy core boundary while making inference reusable for the Halo migration. Models, class maps, and thresholds live in the game repo exactly like ROIs. If the wrapper proves game-specific in practice, demote it to the game repo (cheap reversal).

**ADR-009 (2026-07-07) — Minimap is a motion sensor, not a position tracker.** game_bot's MinimapTracker (position/route planning) was unreliable and is out of scope. But minimap-ROI motion differencing is the *stable* stuck-detection signal — the world view is too visually noisy. Stuck detection uses minimap motion; steering uses YOLO nav arrows; position tracking returns in a later phase, if ever.

**ADR-010 (2026-07-07) — Navigation milestone: pin-marker steering via on-screen nav guide.** The human pins a map marker; YOLO detects the rendered nav guide arrows; the processor steers by them. The game_bot nav-arrow model is carried forward as-is (proven, no retraining). Stuck recovery is an ordered escalation ladder with cooldowns.

**ADR-011 (2026-07-07) — Copilot agent mode + committed instructions + executable acceptance.** Standing constraints live in `.github/copilot-instructions.md` (auto-read). Every phase has a `verify_phase_N.py` acceptance script; diagnostics tools are first-class early phases. Correctness is enforced by runnable checks, not code review — matching both the workflow reality and the series format.

**ADR-012 (2026-07-07) — Datasets as a byproduct: FrameRecorder in contrib.** Live replay capture is impractical here, so recording happens during normal live runs behind a flag. Replays serve detector tuning and regression; navigation acceptance is live. Every acceptance criterion is tagged replay-testable or live-only.

**ADR-013 (2026-07-07) — Seasonal churn is a designed-for workflow, not an emergency.** Season folders under `configs/seasons/sNN/` hold fresh icon captures and an overrides.yaml that takes precedence over base configs. `capture_icons.py` plus a detector verification script make the ~12-week refresh a documented, repeatable procedure with a recurring Copilot prompt.

### ADR-<NNN> — FrameProcessor.process takes a services bundle, not a raw FrameHistory

**Date:** <YYYY-MM-DD>
**Status:** Accepted (retroactive; framework already ships this signature).

**Context.** FEATURE_SPECS §0 documented `FrameProcessor.process(frame, history)` — a two-arg call where the second argument was the FrameHistory ring buffer. The framework has since evolved: processors need more than history to do their job (command-registry access, capture metadata such as latency_frames and fps, and future collaborators we don't want to thread through constructors one at a time). The live signature in `bot_framework/framework/interfaces.py` is `process(frame, services)` where `services` is a bundle object. This drift was discovered while launching Phase 4a and is the second spec-drift incident on a core interface (see QUESTIONS.md).

**Decision.** The framework signature is authoritative: `process(frame: StampedFrame, services: ProcessorServices) -> Action | None`. `services` is the sole channel for per-tick collaborators the framework hands a processor. Processors never reach around it to grab hardware, config, or singleton state.

**Consequences.**
- FEATURE_SPECS §0 corrected same session; F-NAV-1 spec surface updated to match.
- All future processors (Phase 5+ combat, the halo_bot migration in HALO_MIGRATION.md) target this signature. Halo migration notes updated to reflect that gen3's threaded pipeline collapses into a synchronous `process(frame, services)` call, with FrameHistory reached *through* services rather than passed directly.
- Adding a new collaborator to `services` is a framework change and gets its own ADR — we do not silently grow the bundle.
- Copilot phase prompts from B-4b forward include the standing guardrail: *"Read framework/interfaces.py for the ProcessorServices field list before writing code; do not rely on FEATURE_SPECS for this signature."*

**Alternatives considered.** Keep `(frame, history)` and inject other collaborators via processor constructors — rejected because it turns every framework capability addition into a signature change in every consumer. Pass a dict rather than a dataclass — rejected because it defeats type-checking and hides the contract.
---

*End of ARCHITECTURE.md. Next document: FEATURE_SPECS.md.*
