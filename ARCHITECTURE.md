# ARCHITECTURE.md — d4_bot

**Status:** Living document. The north star for all design decisions in this repo.
**Audience:** Future-me and GitHub Copilot (via pasted sections and `copilot-instructions.md`).
**Companion documents:** FEATURE_SPECS.md (what to build), BUILD_PLAN.md (in what order), ROADMAP.md (cross-project milestone ordering), COPILOT_PROMPTS.md (how to prompt it), TROUBLESHOOTING.md (how to recover).
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


### ADR-019 — FrameProcessor.process takes a services bundle, not a raw FrameHistory (number assigned retroactively 2026-08-03)

**Date:** 2026-07-18
**Status:** Accepted (retroactive; framework already ships this signature).

**Context.** FEATURE_SPECS §0 documented `FrameProcessor.process(frame, history)` — a two-arg call where the second argument was the FrameHistory ring buffer. The framework has since evolved: processors need more than history to do their job (command-registry access, capture metadata such as latency_frames and fps, and future collaborators we don't want to thread through constructors one at a time). The live signature in `bot_framework/framework/interfaces.py` is `process(frame, services)` where `services` is a bundle object. This drift was discovered while launching Phase 4a and is the second spec-drift incident on a core interface (see QUESTIONS.md).

**Decision.** The framework signature is authoritative: `process(frame: StampedFrame, services: ProcessorServices) -> Action | None`. `services` is the sole channel for per-tick collaborators the framework hands a processor. Processors never reach around it to grab hardware, config, or singleton state.

**Consequences.**
- FEATURE_SPECS §0 corrected same session; F-NAV-1 spec surface updated to match.
- All future processors (Phase 5+ combat, the halo_bot migration in HALO_MIGRATION.md) target this signature. Halo migration notes updated to reflect that gen3's threaded pipeline collapses into a synchronous `process(frame, services)` call, with FrameHistory reached *through* services rather than passed directly.
- Adding a new collaborator to `services` is a framework change and gets its own ADR — we do not silently grow the bundle.
- Copilot phase prompts from B-4b forward include the standing guardrail: *"Read framework/interfaces.py for the ProcessorServices field list before writing code; do not rely on FEATURE_SPECS for this signature."*

**Alternatives considered.** Keep `(frame, history)` and inject other collaborators via processor constructors — rejected because it turns every framework capability addition into a signature change in every consumer. Pass a dict rather than a dataclass — rejected because it defeats type-checking and hides the contract.

### ADR-014 — Steering emission overlaps bursts; PRE_EFFECT gates verdicts, not emissions

**Date:** 2026-07-13
**Status:** Accepted. Amends ADR-006 (navigation-as-processor) and F-CTL-2 / F-NAV-1 in FEATURE_SPECS.md.

**Context.** Phase 4a live acceptance revealed that non-overlapping fixed-duration bursts produce unshippable visible movement quality. Firmware v2.1 `move_duration` commands are self-releasing (protocol.md §3.2): when duration expires, the left stick returns to neutral. In D4, stick-to-neutral triggers an in-game stop animation, and stick-from-neutral triggers a start animation. Both animations are non-zero cost. At the Phase 4a starting config (400 ms burst, 100 ms latency gate ≈ 100 ms pause per boundary), the character was visibly walking roughly 50% of the time — every burst boundary incurred a full stop-then-start animation cycle, and those animations were expensive enough to dominate visible motion.

The original F-CTL-2 design ("emit as short bursts, each burst boundary a decision point") conflated two responsibilities: (a) when the processor emits a movement command, and (b) when the processor is allowed to evaluate whether the previous command's effect landed. It treated these as the same moment. In practice they are not the same requirement — emission wants to be frequent to keep motion continuous; verdicts want to be conservative to respect capture latency.

**Decision.** Bursts overlap. Emission cadence is a new config value (`emission_interval_ms`) decoupled from burst duration (`burst_duration_ms`). Burst duration now functions as a dead-man's-switch safety timer — if the bot dies or hangs, the firmware self-releases within `burst_duration_ms` and the character stops. Emission cadence is set shorter than burst duration so a new `move_duration` packet always arrives before the previous burst's timer expires, superseding it per protocol.md §3.2 special behavior. The character never sees a neutral stick during normal operation; no stop/start animation cycles are triggered.

The PRE_EFFECT concept is retained but its semantics change: it gates **verdicts** (arrival, stuck, correction-against-just-issued-command), not emissions. The processor continues emitting bursts on the emission cadence throughout the PRE_EFFECT window, updating direction based on the freshest available detection. It withholds verdicts until the pre-effect window elapses relative to the most recent *significant direction change*, not relative to the most recent emission (since emissions are now continuous).

Emission also tolerates brief detector dropouts. Under overlapping-burst emission, a new burst fires every `emission_interval_ms` and needs a direction. When the freshest available detection is stale (no arrow detected in the current frame or in a recent frame within the direction-freshness window), the processor continues emitting bursts using the last known good direction for up to `stale_direction_tolerance_ticks` (config, starting value 3 ticks ~= 50 ms at 60fps). Beyond that tolerance, emission is skipped, the character's last burst self-releases via firmware timer, and the processor's normal SEARCHING/ARRIVED verdict logic runs. Rationale: prior versions of this navigation approach used the same "continue last movement for a frame or two while detection reestablishes" pattern successfully. It bridges 1-3 frame detector hiccups without halting motion, which is the dominant Phase 4a failure mode (momentary YOLOv5 dropouts on high-contrast or busy backgrounds). This is a bandaid over detector unreliability, not a fix for it - the retrain remains banked as the correct long-term answer per QUESTIONS.md.

**Starting values (Phase 4a config):**
- `emission_interval_ms: 200` — a new burst is emitted every 200 ms.
- `burst_duration_ms: 400` — safety timer; character walks no more than 400 ms after last packet if the bot crashes.
- `stale_direction_tolerance_ticks: 3` — how many ticks the processor will continue emitting on the last known good direction when detection is stale before skipping emission.
- Pre-effect window (verdicts only): `latency_frames + <significant direction change threshold ticks>`.

**"Significant direction change" definition:** the anchor for verdict gating shifts from "last emission" to "last emission whose steering direction differed from the previous emission by more than N degrees" (config: `significant_direction_change_degrees`, starting value ~15°). Rationale: if two successive bursts point almost the same direction, no meaningful new command was issued, and verdicts don't need to re-gate. Small-angle corrections during continuous motion should not perpetually reset the verdict window.

**Consequences.**
- F-CTL-2 and F-NAV-1 amended same session; new config keys documented in F-NAV-1's runtime config bullet.
- F-NAV-2's rule ("each new burst's direction is computed from detections whose origin frame_id postdates the previous burst's real-world completion") is amended: direction is computed from the freshest detection whose origin frame_id postdates the most recent *significant direction change*, plus latency_frames. Detections older than that are treated as stale for direction purposes.
- Phase 4b stuck detection design impact: F-NAV-3 currently keys stuck evaluation on "movement burst active or just completed" (FEATURE_SPECS.md §7). Under continuous emission, "just completed" is not a meaningful anchor. Phase 4b's spec must define a different anchor — proposed: "movement burst emitted within the last N ticks with non-zero intended magnitude," which is the honest reading of "the bot is trying to move." F-NAV-3 to be updated when Phase 4b lands. Superseded by ADR-023, which anchors stuck evaluation on nav_arrows presence in GameState rather than on emission bookkeeping.
- Copilot phase prompts from B-4b forward include the standing guardrail: *"Bursts overlap. Do not treat burst completion as a state transition or verdict anchor."*
- The stop/start animation cost this ADR addresses is D4-specific in its magnitude, but the general principle (self-releasing bursts trigger game-side start/stop transitions) will apply to Halo migration and any future game.

**Alternatives considered.**
- **Per-frame emission.** Rejected: emitting every tick means every steering decision is made on frames that reflect a command already superseded twice, and the F-NAV-2 latency discipline becomes impossible to honor. The overlap model preserves latency discipline by keeping emission cadence longer than latency_frames.
- **Shorter non-overlapping bursts.** Rejected: the stop/start animation cost is a per-emission fixed cost, not a per-millisecond cost. Halving the burst duration doubles the number of animation cycles and makes the problem worse, not better.
- **Keep the current non-overlapping design and accept 50% visible duty cycle.** Rejected: Phase 4a's acceptance criteria include reaching a marker pinned 20–30 seconds away in real playtime. At effective half-speed, that's a 40–60 second walk with visible stop/start jitter throughout — not shippable as a milestone regardless of whether it terminates in ARRIVED.
- **No stale-direction tolerance (strict skip-on-stale).** Rejected: 1-3 frame detector dropouts happen routinely with the current YOLOv5 checkpoint (QUESTIONS.md banked issue). Under strict skip, every hiccup produces a firmware self-release and the stop/start animation this ADR was supposed to eliminate. Tolerance of a few ticks preserves motion continuity across brief dropouts.

**Correctness argument (why this preserves latency discipline).** The F-NAV-2 concern was: a burst emitted while the previous burst's effect wasn't yet visible would be steering on stale data. Under overlap, this is preserved by keying direction freshness to the last *significant direction change*, not the last emission. Small continuous corrections during steady walking are cheap and correct — the direction is stable, all detections are equally fresh relative to intent. Only when direction meaningfully changes (obstacle, guide reroute) do we reset the freshness clock, and at that point the pre-effect window kicks in and prevents further significant changes until the last one's effect is visible. Verdicts (arrival, stuck) always gate on the pre-effect window relative to the last significant direction change.

### ADR-015 — Minimap-pin detection as second arrival signal; compound-signal arrival heuristic

**Date:** 2026-07-18
**Status:** Accepted. Amends ADR-014's arrival tuning. Opens Phase 4a.1.

**Context.** Phase 4a shipped with `arrival_confirm_ticks: 120` (2 seconds) to survive nav_arrow YOLOv5 detector dropouts on light-colored backgrounds and VFX-heavy moments. That tuning is a tax on real-arrival response time and is vulnerable to detector failures longer than 2 seconds. A prolonged detector dropout mid-transit can still trigger spurious arrival because "recent movement" is always true under overlapping-burst emission (ADR-014).

The minimap displays a destination pin as a small grayish/metallic icon that renders identically whether the destination is at the border of the minimap (far state) or inside the minimap interior (near state). The pin persists on the minimap until the character crosses D4's internal proximity threshold for the destination, at which point the pin disappears entirely. This provides a second, independent arrival signal - one that operates on a fixed UI region rather than the busy gameplay area, and is therefore uncorrelated with the nav_arrow detector's failure modes.

**Decision.** Add a minimap-pin detector using OpenCV template matching on a fixed search ROI. Add `pin_visible: bool` and `pin_position: tuple[int, int] | None` fields to GameState. Amend NavigationProcessor's arrival heuristic to require BOTH signals lost - nav_arrows empty AND pin_visible false - sustained for `arrival_confirm_ticks`.

Because the compound signal is much stronger than either alone (probability of both detectors simultaneously false-negative-ing is far lower than either individually), `arrival_confirm_ticks` drops from 120 back to 24 (400 ms). This restores fast real-arrival response while eliminating spurious mid-transit arrivals from single-detector hiccups.

**Timing model (Interpretation A):** track a single `both_lost_ticks` counter that increments only when both signals are lost on the current tick and resets to zero if either signal is present. Arrival fires when `both_lost_ticks >= arrival_confirm_ticks`. This explicitly requires the two signals to be lost *together* for the duration, not merely both lost at some point in the recent past. Interpretation B (independent counters, arrival fires when both counters exceed threshold) was rejected because it accepts out-of-phase drops as evidence of arrival, which is exactly the failure mode compound-signal design should reject.

**Detector approach.** Classical CV via `cv2.matchTemplate`. The pin template is a single reference image cropped from a real minimap screenshot at native 1920x1080 resolution, stored at `configs/minimap_pin_template.png`. The detector runs template matching over a search ROI that extends slightly beyond the minimap's rendered bounds (pins can render partially outside the minimap frame - 20 px on left/right, 10 px on top/bottom). Match confidence above a configurable threshold reports `pin_visible=True` and returns the best-match location. This choice over training a YOLO model: the minimap is a fixed UI element with consistent rendering, template matching is essentially free at inference time, and no training data is required.

**Consequences.**
- New F-DET-3 spec entry for the pin detector.
- New GameState fields for pin state.
- F-NAV-1 arrival condition amended.
- `arrival_confirm_ticks` tuned from 120 back to 24 in `navigation.yaml`.
- Stale-tolerance and other ADR-014 emission behavior unchanged - pin detection is orthogonal to how movement is emitted.
- If the pin detector fails (returns pin_visible=false when it shouldn't), navigation runs will hang past the point of actual arrival because the compound signal never fires. Mitigation: a backstop timeout on `nav_arrow_lost_ticks` alone. If nav_arrows have been lost for `nav_arrow_only_arrival_backstop_ticks` (config, starting value 300 = 5 seconds), fire arrival regardless of pin state. This is a safety net, not the primary path - under normal operation the compound signal fires within `arrival_confirm_ticks`.
- Phase 4b unblocked: with reliable arrival, Phase 4b's stuck detection can key off "character not moving" without arrival interfering.

**Alternatives considered.**
- **Pin-only arrival.** Replaces nav_arrow-based arrival entirely with pin-based arrival. Simpler ADR, single-signal. Rejected because it puts the entire arrival correctness on one detector; if the pin detector fails, arrival never fires and runs hang indefinitely.
- **Nav_arrow-only arrival with detector retrain.** Fix the underlying reliability of the nav_arrow detector by retraining on more diverse backgrounds. Rejected as the Phase 4a.1 solution because retraining is multi-session work with data-gathering overhead. Retrain remains banked as long-term correct fix in QUESTIONS.md; compound signal makes retrain less urgent.
- **Interpretation B (independent lost counters).** As described above; rejected on correctness grounds.
- **HSV-mask-based pin detection.** Rejected because the pin's grayish/metallic color has no distinctive hue that separates it from environmental content on the minimap. Template matching on the icon's shape is more robust.
---

### ADR-016 — ROADMAP.md added as eighth canonical doc

**Date:** 2026-07-19
**Status:** Accepted.

**Context.** Previous-generation (game_bot) parity features — operator command interface, combat scan/fight, inventory slot reading and grid navigation, two-stage map cursor navigation — needed a documented home; inventory and the map cursor pattern were covered nowhere in the existing deferred list. Roadmap drafted during a model-transition documentation pass.

**Decision.** A cross-project milestone roadmap (ROADMAP.md) is added to the canonical doc set. It governs milestone existence and ordering across bot_framework, d4_bot, and future game bots; BUILD_PLAN.md retains authority over execution detail of active d4_bot phases. The file lives in d4_bot rather than bot_framework, trading strict scope alignment for doc-set cohesion (all eight canonical docs in one repo).

**Consequences.** New milestones require a planning pass producing BUILD_PLAN phases before implementation. Open decisions OD-1 through OD-5 recorded in ROADMAP.md §6.

### ADR-017 — Whisper-farming architecture, scanning resolution, and grow-on-demand detection principle

**Date:** 2026-08-03
**Status:** Accepted.

**Context.** Model-transition documentation pass. Operator ground-truthed the whisper archetype taxonomy and supplied the legacy scanning mechanics from game_bot experience.

**Decision.** FF-1 (autonomous whisper farming) is adopted as the near-term North Star with a three-layer churn-firewall architecture (archetype executors in code, objective definitions in seasonal YAML, a selection layer that skips unexecutable whispers). OD-1 is resolved: enemy detection reads the game's targeting UI (health-bar appearance on facing acquisition) rather than visual monster detection; scan is a latency-gated facing-sweep state inside the combat layer. Detections are grow-on-demand per milestone planning pass, with screen-mode detection named as the one shared-infrastructure exception.

**Consequences.** M2 hardens into a dependency for combat (stick contention between scan and steering). OD-6 and OD-7 added. Seasonal whisper churn is absorbed as YAML data edits by construction.

### ADR-018 — M1 combat scoped defensive-only with gated-rotation architecture

**Date:** 2026-08-03
**Status:** Accepted.

**Context.** Fable-model transition pass. The gate architecture resolves a genuine disagreement — optimistic blind pressing vs. the operator's instinct that pressing is not forgiving (resource whiffs, contextual-interact hijacking, movement-skill repositioning) — by converting it into a per-skill empirical question with a YAML-only escape hatch.

**Decision.** M1 is defensive combat (engage-kill-sweep-report), standalone-testable without navigation; area-clear belongs to FF-1. Enemy detection reads the targeting UI health bar (OD-1 strategy). Attack rotation is a timed YAML sequence with a per-skill optional gate field (none | resource | cooldown); v1 ships all-none per operator ruling that the target build is simple and not resource-starved. Survival scope: threshold potion drinking and death detection; no flee logic. Banked in COMBAT_MILESTONE.md pending M1 activation.

**Consequences.** Stick-contention work moves wholly to M2, which gains "nav + combat concurrently" as its demo. PowerHUDDetector intent is not carried into v1. The M1 loadout must avoid movement skills in rotation.

### ADR-020 — M1 combat: detection strategy, sweep mechanism, and phase split

**Date:** 2026-08-04
**Status:** Accepted.

**Context.** M1 planning pass. The operator supplied game-mechanics ground truth that reshaped the banked COMBAT_MILESTONE.md sketch: character facing follows left-stick direction under D4's fixed overhead camera, and a brief stick input turns the character with negligible displacement; boss and elite health bars appear on proximity regardless of the facing cone; and boss bar appearance churns substantially season to season and is unreliable to detect.

**Decision.**
1. Sweep is continuous stick rotation reusing ADR-014's overlapping-burst emitter with the direction advancing programmatically per emission — not discrete nudge-wait-check cycles. Latency overshoot is bounded by targeting-cone half-width rather than eliminated. New config keys: sweep_angular_step_degrees, sweep_stick_magnitude. A sweep is bounded to one revolution; no open-ended spinning.
2. Enemy detection keys on health-bar PRESENCE, deliberately loosely, on whatever element proves invariant across enemy types and seasons. The detector does not classify enemy type by template. Bar templates live in configs/seasons/sNN/ from day one per F-CFG-5, not in base configs.
3. Boss/normal discrimination is behavioral, via bar continuity across a sweep: a bar persisting independent of facing is a proximity signal (boss/elite); a bar appearing and vanishing as the cone passes is a facing signal (normal).
4. Boss bypass: a bar present on entry to IDLE sends the processor directly to ATTACKING. Sweep runs only when no bar is present.
5. M1 splits into two phases: 5a detection-only and replay-verifiable; 5b the full processor including sweep, rotation, and survival. Sweep is NOT split out separately because it reuses the proven ADR-014 emitter rather than introducing new movement machinery.

**Consequences.**
- The F-DIAG-4 measurement task is reframed: capture normal, elite, and boss bars and identify the stable invariant across all three, rather than identifying distinguishing features. This replaces the "one template or two" question posed in COMBAT_MILESTONE.md §2.
- Sweep and steering share a movement idiom, removing an idiom mismatch M2's composition work would otherwise inherit.
- ENGAGE holds facing by emitting no stick input; ATTACKING emits button presses only.
- Loose detection plus behavioral inference degrades gracefully across seasonal churn. A tight template match would silently stop firing on next season's boss bars, producing false combat_clear with a boss actively engaged — a failure mode with no visible symptom until the bot dies.
- P-2 parity scope ratifies as FULL per OD-5's unchallenged-default rule; M1 delivers the first installment, FF-1 completes area-clear.
- FF-2 (minimap threat awareness) recorded in ROADMAP.md §4.

**Alternatives considered.**
- Discrete nudge-wait-check sweep. Rejected: targeting-cone width absorbs the latency overshoot, and the discrete form introduces a second movement idiom for no gain.
- Classifying enemy type by which template matched. Rejected on operator evidence that boss bars churn seasonally and detect poorly.
- Minimap red-dot reading as the M1 scan mechanism. Deferred to FF-2; it is an optimization over a working sweep, not a substitute for one.

### ADR-021 — Arrival discriminator: target-acquired latch; backstop subsumes guide-lost timeout

**Date:** 2026-08-06
**Status:** Accepted. Amends ADR-015.

**Context.** Implementing ADR-015's compound-signal arrival required removing
`_has_recent_burst_context`, a guard ADR-014 had already rendered vacuous under
continuous emission. Two consequences surfaced that ADR-015 did not anticipate.
First, with the guard gone, a mid-run unpin and a true arrival are
indistinguishable from screen state alone - both present as nav_arrows and
pin_visible vanishing together at an arbitrary location. Second, the guard had
been capping the arrival path at `recent_movement_window_ticks` (30), which meant
ADR-015's `nav_arrow_only_arrival_backstop_ticks` (300) could never fire: with
`search_grace_ticks` at 24, SEARCHING terminated the run 276 ticks before the
backstop was reachable. The backstop was dead code as specified.

**Decision.**
1. A `_target_acquired` latch is set on the first tick either signal is present.
     All arrival evaluation is gated behind it, so a run started with no
     destination pinned still terminates `guide_lost` after `search_grace_ticks`.
2. While the latch is set and nav_arrows have been lost fewer than
     `nav_arrow_only_arrival_backstop_ticks`, SEARCHING does not terminate. The
     backstop becomes the outer timeout for the whole lost-signal path rather than
     a parallel one.
3. Both arrival paths report terminal status `"arrived"`. They are distinguished
     by an `arrival_via_backstop` flag exposed as a read-only property, so
     acceptance scripts matching on the terminal string keep working.
4. Arrival is evaluated before the SEARCHING branch in `process()`, so arrival
     outranks a guide_lost termination.

**Consequences.**
- Mid-run unpin now terminates `"arrived"` via the backstop after ~5 seconds
    rather than `"guide_lost"`. Phase 4a's unpin acceptance bullet is amended
    accordingly in BUILD_PLAN.md.
- `recent_movement_window_ticks` is retained in `navigation.yaml` and in the
    NavigationProcessor constructor but is no longer consumed by arrival logic.
- Arrival counters are updated every non-terminal tick including inside the
    pre-effect window; it is the verdict that is latency-gated, not the
    measurement. No latency arithmetic exists inside the counters themselves.
- A real discriminator remains available and is banked in QUESTIONS.md:
    `pin_position` travels from minimap border to interior as the character
    approaches, so a pin vanishing from the border is an unpin and one vanishing
    near the interior is a true arrival. It requires live measurement before it
    can be specified.

### ADR-022 — Capture sources warm up before first use; black frames at open are expected

**Date:** 2026-08-06
**Status:** Accepted.

**Context.** A live navigation session on 2026-08-06 produced black frames from the GC573 through every open variant tried: no settings at all, resolution and fps only, MJPG before resolution, MJPG after resolution, YUY2, and 1280x720. All returned mean 0.0 with a garbage FOURCC. The card was healthy in Device Manager and enumerated correctly. Opening OBS with the GC573 source active made the identical probe return live frames, which was initially read as OBS performing some stream initialisation the framework did not.

That reading was wrong. Measurement showed the device emits exactly 83 black frames — approximately 1395 ms at 60 fps — after open, then delivers live frames with zero subsequent dropouts. The run length was identical across consecutive opens in the same session. OBS was not initialising anything; it was simply occupying the warm-up window while diagnostics ran. Every probe until then had discarded only 10 frames and given up inside that window.

The OBS workaround carried a second cost: sharing the DirectShow device halved the delivered frame rate to a rock-steady 30 fps against a configured 60. The NavigationProcessor computes emission timing from frame_id deltas multiplied by the *configured* fps, so it believed a 12-tick gap was 200 ms when it was really 400 ms — landing exactly on `burst_duration_ms` expiry and producing a visible stop/start at every burst boundary. `latency_frames` and `arrival_confirm_ticks` were likewise being applied at double their intended wall-clock duration.

**Decision.** Capture warm-up becomes a first-class property of `CaptureSource`, alongside `latency_frames`. After opening the device, `AVerMediaCapture` discards frames until the first frame with a non-trivial mean, bounded by `warmup_timeout_ms`. Control does not return to the caller until warm-up completes or the timeout elapses.

`warmup_timeout_ms` is a framework default (3000) overridable in `hardware.yaml`, not a required key — the value is a property of the capture rig, not a decision each game project should have to make, and requiring it would break every existing config including gen3_bot's.

On timeout the framework logs loudly and proceeds rather than raising. A legitimately black game screen at startup (loading, death, cutscene) is indistinguishable from a warm-up failure by this test, and hard-failing a run on that ambiguity is worse than starting with a warning.

**Consequences.**
- The OBS dependency banked in QUESTIONS.md on 2026-08-06 is withdrawn. It was a misdiagnosis. The QUESTIONS item and the TROUBLESHOOTING runbook entry are corrected rather than deleted, so the reasoning error stays visible.
- The Phase 4a.1 cold-start failure — NavigationProcessor entering SEARCHING at f=1 and terminating `guide_lost` at f=25 while the YOLO model was still loading — is the same window and is expected to resolve with warm-up.
- Black frames at open are not a fault and must not be diagnosed as one. The earlier black-frame incident closed as "a transient card fault resolved by restart" was almost certainly this, misattributed.
- Frame-rate assumptions are now suspect generally. ADR-014's emission model assumes the loop runs at the configured fps; nothing verifies that. Banked in QUESTIONS.md as a separate item.
- Warm-up is a property of the capture source, not of any one game project, so it applies unchanged to the Halo migration.

**Alternatives considered.**
- **Discard a fixed configured frame count.** Simpler and cannot be fooled by a black game screen. Rejected because it hardcodes a rig-specific measurement into a timing-sensitive path, and 83 frames is an observation about this card today rather than a contract.
- **Raise on warm-up timeout.** Rejected: a black startup screen is recoverable and a hard failure on an ambiguous signal costs more than it protects.
- **Leave the OBS workaround in place.** Rejected: it halves the frame rate, which silently invalidates every latency and cadence value in the system.

### ADR-023 — Stuck detection is a proportional motion window, not a consecutive-tick streak

**Date:** 2026-08-06
**Status:** Accepted.

**Context.** Phase 4b planning measured minimap_motion across five live segments on the rig at true 60 fps, logged per-frame via diag_detector_tuner. Findings:

- Standing still reads a changed fraction around 0.00003. Walking reads around 0.37. Four orders of magnitude of separation; threshold placement is not a sensitive parameter (moving changed_fraction from 0.015 to 0.05 changes the wall-segment verdict by 0.2%).
- Enemy icons and boss VFX do not meaningfully lift the floor. Standing amid an active mob pack reads below threshold on 99.8% of frames; standing under an attacking boss on 98.3%, with occasional isolated spikes and nothing sustained. The concern that minimap icon churn would mask stuck is retired.
- Pressing into a wall does NOT produce a clean stop. D4 resolves angled wall collision by sliding, so the segment is bimodal: it alternates frame to frame between roughly 0.40 (translating as fast as a full walk) and roughly 0.008 (pinned). 67% of frames read not-moving, interleaved rather than contiguous.
- The discriminating statistic is the proportion, not the streak. Over the measured segments, walking never produced more than 1 consecutive not-moving frame; the wall segment produced runs up to 139.

The consecutive-tick definition assumes a clean stop. Real stuck on this rig stutters, and any slip frame resets a streak counter to zero. Additionally, the debouncing that makes character_moving useful for steering actively hides stuck: in the wall segment the debounced value reported moving on substantially more frames than the raw reading did.

**Decision.**
1. Stuck is: nav_arrows present in GameState, AND the pre-effect window has elapsed, AND at least `stuck_quiet_fraction` of the last `stuck_window_ticks` ticks read not-moving. Both keys from navigation.yaml.
2. The proportion is computed over the RAW motion reading, not the debounced one. GameState gains an additive field carrying the raw reading alongside the existing debounced character_moving; StuckMonitor consumes the raw field, and no other consumer changes.
3. The anchor for "the bot is trying to move" is nav_arrows presence in GameState, not the processor's own emission bookkeeping. This supersedes the `stuck_movement_window_ticks` anchor proposed in ADR-014's consequences and in F-NAV-3's impact bullet; that key is not created. Rationale: processors key on GameState by ARCHITECTURE §7, the signal is directly observable in a recording, and rung 2 of the recovery ladder re-steers against the guide bearing - with no arrow there is no bearing, so arrow presence is a precondition for the ladder to function at all, not merely a convenient proxy.
4. The recovery ladder resets to rung 1 on confirmed movement as F-NAV-3 already specifies. A per-run `stuck_event_budget` (config) bounds total stuck events across a run; exhausting it terminates `stuck_unrecoverable` regardless of how many resets occurred. This is the termination guarantee: sliding along a wall is sometimes a legitimate escape and cannot be classified as failure, so the budget bounds the loop rather than trying to judge individual recoveries.
5. Verdict ordering in NavigationProcessor.process: arrival, then stuck, then SEARCHING, then emission. Stuck remains live during the nav_arrow_only_arrival_backstop_ticks window - a bot walking into a wall through a nav_arrow outage should recover, not wait out the backstop.

**Consequences.**
- F-NAV-3's stuck definition is rewritten. `stuck_ticks` is replaced by `stuck_window_ticks` and `stuck_quiet_fraction`.
- GameState gains one additive field for the raw motion reading; F-GS-1 is amended. Existing fields and semantics are unchanged.
- The Phase 4b seam call in navigation.py moves to sit after arrival evaluation. This is a reordering of an existing call, not a rework of arrival logic, and B-4b authorizes it explicitly.
- Steady sliding along a long smooth wall remains undetectable by this mechanism, because it is genuine translation. Real geometry catches and releases, which is what makes the proportional window work. The residual case is bounded by the arrival backstop. A true progress signal would require position tracking, out of scope per ADR-009.
- Threshold tuning for minimap_motion is not required by this decision. The measured separation is wide enough that changed_fraction: 0.015 stands.

**Alternatives considered.**
- **Consecutive-tick streak with a longer window.** Rejected: no window length survives frame-to-frame interleaving; a single slip frame zeroes the count.
- **Reading the debounced character_moving.** Rejected on measurement: hysteresis biases toward reporting motion and erases the pinned stretches.
- **Emission-bookkeeping anchor (`stuck_movement_window_ticks`).** Rejected: it required the processor to inspect its own emission history including skipped emissions, added a config key with a derived floor, and violated the GameState-only reading rule for no gain over arrow presence.
- **Sustained-movement ladder reset, to classify slides as failed recoveries.** Rejected: a slide that clears a corner is a successful recovery, and no available signal distinguishes the two. The attempt budget bounds the loop without requiring the classification.
---

*End of ARCHITECTURE.md. Next document: FEATURE_SPECS.md.*

### ADR-024 — Recovery ladder attempts traversal before repositioning

**Date:** 2026-08-06
**Status:** Accepted.

**Context.** Supersedes the ladder section of ADR-023. ADR-023's stuck detection remains in force unchanged; only its ladder is replaced.

The ladder in ADR-023 assumed stuck means blocked, and its rungs reposition the character: reverse out, re-approach at an angle. Operator experience from the prior D4 bot implementation identifies two common stuck causes that are not blockage at all:

- A ladder or similar interactable directly ahead, requiring an interact press to traverse. No amount of repositioning helps, and reversing moves the character away from the thing it needs to climb.
- An overhead or gap crossing, which requires separation and a running start before the crossing prompt will register. The prompt registers at a specific moment during the approach that cannot be predicted from a frame 6 frames stale, so the prior implementation used repeated interact presses across the approach rather than one timed press. This worked.

Repositioning is the right response to genuine geometric blockage, but it is the most disruptive rung and it was first. Traversal attempts are cheap, fast, and non-destructive - in the current defensive-combat-only scope the worst outcome of a stray interact press is initiating an attack, which is acceptable.

**Decision.** The ladder becomes four rungs, attempted in order, one rung per stuck event:

1. Single interact press, character stationary. Resolves ladders and directly-adjacent interactables.
2. Reverse along the inverse of the current nav bearing for `recovery_reverse_ticks`, with `recovery_interact_press_count` interact presses distributed across that movement at `recovery_interact_press_interval_ticks` spacing. Presses overlap the movement rather than following it - the running start is the point. Resolves overhead and gap crossings.
3. Reverse and re-approach at an angular offset to the guide bearing, as specified in ADR-023 and F-NAV-3. Unchanged. Resolves geometric blockage.
4. Terminal: `stuck_unrecoverable`.

Starting values, from operator recall of the prior implementation, pending Phase 4b live acceptance:
    recovery_reverse_ticks: 30
    recovery_interact_press_count: 6
    recovery_interact_press_interval_ticks: 5

These describe roughly half a second of reverse movement with six interact presses spread across it, at true 60 fps.

**Consequences.**
- F-NAV-3's ladder is rewritten; its stuck definition is untouched.
- Three config keys added to navigation.yaml with constructor validation.
- The interact command is referenced by its registry name from buttons.yaml. The implementing block must confirm the binding exists rather than assuming it carried over from the prior bot.
- Rung 2 is the first place in the navigation path that emits a button press rather than stick movement. Emission remains the processor's responsibility; StuckMonitor reports rungs and never emits.
- Per-run `stuck_event_budget` from ADR-023 is unchanged and still bounds the whole ladder including the new rungs. With four rungs and a budget of 6, a run can traverse the full ladder and retry the early rungs once.

**Alternatives considered.**
- Keeping repositioning first and adding traversal later in the ladder. Rejected: traversal is cheaper and less disruptive, and repositioning actively worsens the ladder-climb case by increasing distance.
- A single timed interact press in rung 2. Rejected: the crossing prompt's registration window cannot be targeted from a capture 6 frames behind. Repeated presses are the operator-validated approach.
- Screen-mode or prompt detection to identify traversal opportunities directly. Deferred: that is the screen-mode detection work ADR-020 names as the one shared-infrastructure exception, and it is not scoped.

### ADR-025 — Recovery ladder traversal input is press_b

**Date:** 2026-08-17
**Status:** Accepted.

**Context.** Amends the command identity in ADR-024's rungs 1 and 2. ADR-024's ladder structure, ordering, and rationale remain unchanged.

ADR-024 described the ladder rungs correctly as traversal attempts, but the implementing session resolved the traversal input to `press_a` on the assumption that A is D4's interact button. Operator correction: the input that climbs ladders and triggers gap crossings in D4 is B, not A. The prior bot implementation used B for both. B is not a general interact button; it is the traversal input, and it is additionally bound to dodge.

**Decision.**
1. Rungs 1 and 2 emit `press_b`, not `press_a`.
2. The rungs are described as a traversal press, not an interact press. The distinction is load-bearing: a general interact press would be a different button with different side effects.
3. Config keys keep their existing names - `recovery_interact_press_count` and `recovery_interact_press_interval_ticks` - to avoid a rename touching config, loader, constructor, and tests for no behavioural gain. The `interact` prefix in those key names is historical; the command is `press_b`.

**Consequences.**
- F-NAV-3's rungs 1 and 2 name `press_b`.
- B-4b's guardrails name `press_b`.
- The emitted command name in NavigationProcessor changes from `press_a` to `press_b`. `press_b` is already registered in `buttons.yaml` as `type: button_duration, index: 2, duration_ms: 80` - identical to `press_a` apart from index - and was verified live in Phase 1 acceptance.
- B doubles as dodge, so a stray traversal press during recovery is low-risk: a dodge in place, no dialogue, no looting, no dungeon entry. This is safer than `press_a` would have been.
- Open concern, not decided here: press durations of 80 ms at a 5-tick interval (~83 ms at 60 fps) leave ~3 ms between release and next press. Under the firmware's supersede behaviour this approximates a continuous hold rather than six distinct presses. If a traversal prompt requires a rising edge, this may register as one press. To be evaluated at Phase 4b live acceptance cases C1 and C2.

### ADR-026 — Capture device is selected by name; startup verifies achieved frame rate

**Date:** 2026-11-25
**Status:** Accepted.

**Context.** During the 2026-11-25 HUD census, `hardware.yaml` held `device_index: 0` and the GC573 was at index 0 for the first recording. Minutes later, with no config change, index 0 opened the HD Pro Webcam C920 instead. The run recorded a picture of the workshop. Nothing in the pipeline objected: the webcam also delivers 1920×1080, so the geometry assertion passed. The only symptom was an achieved rate of ~27 fps against a configured 60, which nothing checks.

Enumeration later the same afternoon (`cv2_enumerate_cameras`, DirectShow) listed four video devices: `HD Pro Webcam C920`, `Cam Link 4K`, `AVerMedia HD Capture GC573 1`, `OBS Virtual Camera`. Within one session the GC573 moved from index 0 to index 2, and the webcam took index 0. This is the second documented index drift (the first was 2 → 0, see overview / TROUBLESHOOTING). DirectShow index order is not stable across opens, USB activity, or reboots, so an integer index cannot identify the capture card.

Two further facts make a content-based check insufficient on its own:
- The rig has a second capture device (Cam Link 4K). If it is ever routed the Xbox picture (the HDMI matrix makes that one switch away), a "does this look like the game" test cannot tell the two cards apart, and the 6-frame latency rule was measured on the GC573 only.
- ADR-022 already establishes that a legitimately black or non-HUD startup screen (loading, death, map) is indistinguishable from a fault by content alone.

ADR-022 also banked that nothing verifies the loop actually runs at the configured fps. Both the webcam incident (~27 fps) and the earlier OBS sharing incident (30 fps) would have been caught by measuring it.

**Decision.**
1. `AVerMediaCapture` accepts `device_name: str` as the primary selector. At open, it enumerates video devices for the backend being opened, matches `device_name` as a case-insensitive substring, and opens the matched device's index.
   - Exactly one match is required. Zero or multiple matches raise, and the error lists every enumerated device (index, name, path).
   - There is no fallback to any index. A missing match is a hard failure, because a silent fallback is the failure this ADR exists to prevent.
   - If the existing MSMF → DSHOW backend fallback occurs, the name is re-resolved against the fallback backend's enumeration.
   - `device_index` remains accepted for backward compatibility (gen3_bot, diagnostic scripts). Supplying both or neither raises.
2. The resolved device (name, path, index, backend) is exposed as properties on the capture object and printed in the startup banner on every run.
3. After ADR-022 warm-up completes, `AVerMediaCapture` measures the achieved frame rate over a short window (`fps_check_frames`, framework default 60). If achieved fps is below `min_fps_fraction × fps` (framework default 0.9), it raises. Unlike ADR-022's warm-up timeout, this is a hard failure: no game screen lowers the delivered frame rate, and a wrong rate silently invalidates every latency and cadence value in the system. Both values are framework defaults overridable in `hardware.yaml`, not required keys.
4. d4_bot adds an advisory content check in `build_capture`: after the first live frame, template-match the minimap at its configured ROI and print a loud WARNING on a miss. It does not raise (ADR-022 reasoning: map, death and loading screens are legitimate startup states).
5. Device enumeration uses `cv2_enumerate_cameras` (Windows), installed through bot_framework's `hardware` extra with a `sys_platform == "win32"` marker. Core stays stdlib + numpy.

**Consequences.**
- `hardware.yaml` gains `capture.device_name` (d4_bot value: `GC573`) and loses `capture.device_index` from its required keys.
- The startup banner becomes the first place to look when anything visual is wrong: it states which physical device is open and the measured fps.
- The QUESTIONS item "nothing verifies the loop runs at configured fps" (banked by ADR-022) is closed for capture delivery. Loop processing rate is still measured separately by BotLoop's achieved-FPS measurement.
- A second GC573 on the rig would make `GC573` ambiguous and fail loudly. If that ever happens, extend matching to the device path. Not built now.
- `pip.exe` is blocked by Windows Application Control on this machine. All installs use `python -m pip` (TROUBLESHOOTING entry).
- Applies unchanged to gen3_bot and the Halo migration; the rig is shared.

**Alternatives considered.**
- **Keep `device_index`, add a content check.** Rejected: cannot distinguish the GC573 from the Cam Link carrying the same picture, and ambiguous on legitimate non-HUD startup screens (ADR-022).
- **pygrabber for enumeration.** Pure Python, but returns names only and relies on its list order matching OpenCV's indices. `cv2_enumerate_cameras` returns the OpenCV index directly with name and path. Kept as the fallback if Application Control ever blocks the compiled package.
- **Match on device path instead of name.** Most stable identifier, but unreadable in config and unnecessary with one GC573. Logged, not required.
- **Fall back to index on name miss.** Rejected: reintroduces the silent wrong-device failure.
