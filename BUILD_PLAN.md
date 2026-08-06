# BUILD_PLAN.md — d4_bot

**Status:** Execution order authority. Phases run in sequence; a phase is *done* only when its Definition of Done is met.
**Session sizing:** Estimates are in Copilot work sessions (~3–4 hours of your split-up working time). Phases are sized so one phase ≈ one to three sessions.
**Acceptance tags:** every criterion is **[replay]** (runs against recorded frames / offline) or **[live]** (requires the game running). Live checks are executed via that phase's `verify_phase_N.py`, which prompts y/n for observed behavior.

### Definition of Done (every phase)

1. `scripts/verify_phase_N.py` passes end-to-end — the verify script is itself a deliverable of every phase, whether or not the phase's file list names it.
2. The `bot_framework` commit hash the phase was validated against is recorded in this file (fill the blank in the phase header).
3. Any drift from FEATURE_SPECS.md discovered during the build is corrected **in the spec doc**, not silently absorbed.
4. Work is committed; framework changes (if any) are committed in `bot_framework` separately.

---

## Phase 0 — Repo Setup and Framework Wiring

**Prerequisites:** none. **Sessions:** 1. **Validated against bot_framework commit:** ________

**Features:** FG-4, F-CFG-1 (file + loader/validator), repo scaffolding, Copilot standing instructions.

**Files to create:**
- `d4_bot/` full skeleton per ARCHITECTURE §2 (empty packages, gitignore for `frames/`)
- `d4_bot/pyproject.toml` (depends on `bot_framework[ml]`; Python ≥3.10)
- `d4_bot/.github/copilot-instructions.md` (content supplied in COPILOT_PROMPTS.md Section A — paste verbatim)
- Commit all five project documents to the repo root
- `bot_framework/framework/contrib/config/__init__.py` + module implementing `load_layered_config` (FG-4)
- `bot_framework/pyproject.toml` **modified**: add `[ml]` extra (ultralytics; declared now, consumed in Phase 2)
- `d4_bot/configs/hardware.yaml` with this rig's values (FEATURE_SPECS F-CFG-1 table)
- `d4_bot/tests/test_config_loading.py`

**Acceptance — `verify_phase_0.py` [replay/offline]:**
- Fresh venv: `pip install -e "../bot_framework[ml]"` then `pip install -e .` succeed — the `[ml]` extra is declared this phase and must resolve now, not surprise us in Phase 2.
- Every import in FEATURE_SPECS §0 that exists as of this phase resolves.
- FG-4 pytest passes (scalar override, nested merge, list replacement, no-overrides path).
- Loading `hardware.yaml` with a deliberately deleted key exits with an error naming the key.

---

## Phase 1 — Hardware Path End-to-End (capture + controller + recording)

**Prerequisites:** Phase 0. **Sessions:** 1–2. **Validated against bot_framework commit:** ________

Capture + UDP are already proven on this rig via diablo_bot, so this phase is wiring and tooling, not hardware risk. It ends with the project's first recorded dataset, which Phases 2–3 consume.

**Features:** F-CAP-1, F-CFG-2 (initial), F-CFG-3, F-CTL-1, F-DIAG-1, F-DIAG-3, FG-3 (FrameRecorder).

**Files to create:**
- `bot_framework/framework/contrib/recording/__init__.py` + FrameRecorder module (FG-3)
- `d4_bot/configs/rois.yaml` — initial `minimap` and `nav_arrow_window` entries (placed/adjusted live with F-DIAG-1)
- `d4_bot/configs/buttons.yaml` — the two nav-milestone command atoms, `press_a` and `press_b`, per F-CFG-3's grow-on-demand policy (no full controller map); built with `protocol.md` pasted alongside
- `d4_bot/src/d4_bot/commands.py` — `build_command_registry` (F-CTL-1)
- `d4_bot/scripts/diag_roi_viewer.py` (F-DIAG-1)
- `d4_bot/scripts/diag_udp_echo.py` (F-DIAG-3)
- `d4_bot/scripts/record_dataset.py` — capture-only recording harness wrapping FrameRecorder; this is what records the Phase 1 deliverable dataset (`run_nav.py --record` doesn't exist until Phase 4a)
- Small shared capture builder in `src/d4_bot/` (F-CAP-1)

**Acceptance — `verify_phase_1.py` [live]:**
- Startup banner prints resolution 1920×1080, fps 60, `latency_frames=6` **read from the capture object**.
- Geometry assertion trips correctly when configured resolution is falsified.
- `diag_udp_echo.py` for every command in buttons.yaml (two at this phase) → operator confirms the correct visible in-game act (y/n each). Two-packet payloads = automatic FAIL (the script inspects the payload form).
- `diag_roi_viewer.py` shows `minimap` snug around the minimap and `nav_arrow_window` covering the guide-render area (y/n).
- 30-second recorded walk (`FrameRecorder` behind a flag) sustains ≥45 loop FPS and the output directory replays via `ReplayCapture` without error.
- **Deliverable dataset:** `frames/walk_stand_01/` — ~60 s containing: walking, standing still, walking with a marker pinned (nav guide visible), and standing in front of a wall while pushing into it.

---

## Phase 2 — Visual Detection Foundation

**Prerequisites:** Phase 1 (needs the recorded dataset and live tuning). **Sessions:** 2. **Validated against bot_framework commit:** c66dce2

**Features:** FG-1, FG-2, F-DET-2, F-CFG-4, F-DET-1, F-DIAG-2, F-DIAG-4, F-CFG-5 (season folder skeleton).

**Files to create:**
- `bot_framework/framework/contrib/ml/__init__.py` + YoloDetector module (FG-1)
- `bot_framework/framework/contrib/detection/` **modified**: add RoiMotionDetector (FG-2) — additive; do not touch existing detectors
- `d4_bot/models/nav_arrow/best.pt` (copied from game_bot assets) + `classes.yaml` (F-DET-2)
- `d4_bot/configs/detectors/nav_arrow.yaml`, `d4_bot/configs/detectors/minimap_motion.yaml` (F-CFG-4)
- `d4_bot/src/d4_bot/detectors.py` — `build_detectors` / `build_detector_registry` (F-DET-1)
- `d4_bot/scripts/diag_detector_tuner.py` (F-DIAG-2)
- `d4_bot/scripts/capture_icons.py` (F-DIAG-4)
- `d4_bot/configs/seasons/s09/overrides.yaml` (can be empty-but-valid; F-CFG-5)

**Acceptance — `verify_phase_2.py`:**
- **[replay]** FG-1 harness on `frames/walk_stand_01/`: ≥1 nav-arrow detection on guide-visible frames, 0 on guide-absent frames; inference count demonstrates cadence honored.
- **[replay]** FG-2 on the same dataset: debounced walking→standing transition within `hysteresis_ticks` + margin; zero flicker in steady states.
- **[replay]** `build_detectors` constructs every shipped config; unknown `type` and unknown ROI name each fail loudly naming the offending file.
- **[live]** `diag_detector_tuner.py --detector minimap_motion`: standing shows False, walking shows True in real time (y/n).
- **[live]** `diag_detector_tuner.py --detector nav_arrow`: boxes track the pinned-marker guide on screen (y/n).
- **[live]** `capture_icons.py` produces a crop immediately usable by TemplateMatchDetector (smoke: match it against the frame it came from).
- Season override smoke: changing a threshold in `s09/overrides.yaml` changes the constructed detector's value with no Python edits.

---

## Phase 3 — Game State Model

**Prerequisites:** Phase 2. **Sessions:** 1. **Validated against bot_framework commit:** 690dbcc

**Features:** F-GS-1, F-GS-2, F-GS-3.

**Files to create:**
- `d4_bot/src/d4_bot/state.py` — GameState, StateDiff/diff, GameStateUpdater
- `d4_bot/tests/test_state.py` — construction, immutability, staleness math, table-driven diff edges

**Acceptance — `verify_phase_3.py`:**
- **[replay]** pytest suite passes.
- **[replay]** Replaying `frames/walk_stand_01/` through GameStateUpdater: snapshots show `movement_started` / `movement_stopped` edges at the expected points; `nav_arrows` staleness never exceeds the configured cadence; `nav_guide_appeared` fires when the marker-pinned segment begins.

---

## Phase 4 — Navigation Milestone

**Prerequisites:** Phase 3. **Sessions:** 2–3 total. Split into two stages with separate acceptance so steering is proven before recovery complexity lands on top of it.

### Phase 4a — Steering walk (open ground)

**d4_bot completion commit:** a627341
**Validated against bot_framework commit:** 1b1aed0
**Completion date:** 2026-07-18
**Acceptance status:** Passed. See ADR-014 and ADR-019 for scope-shaping decisions during this phase. Phase 4a.1 (minimap-pin detection + tighter arrival) is banked as immediate follow-up before Phase 4b to address the detector-reliability tuning tax accepted during 4a acceptance.

**Features:** F-CTL-2, F-NAV-1 (states `STEERING`, `PRE_EFFECT`, `SEARCHING`, `ARRIVED` — **no** `STUCK_RECOVERY` yet), F-NAV-2, F-FLOW-1.

**Files to create:**
- `d4_bot/src/d4_bot/processors/navigation.py` — NavigationProcessor + steering emission helper
- `d4_bot/scripts/run_nav.py` (with `--record`, `--season`, `--config-dir`)
- `d4_bot/configs/navigation.yaml` — runtime config for NavigationProcessor per F-NAV-1's runtime-config bullet. Includes overlapping-burst emission keys per ADR-014 (`emission_interval_ms`, `burst_duration_ms`, `significant_direction_change_degrees`). Season overrides via `configs/seasons/sNN/overrides.yaml` (F-CFG-5), no Python literals.
- `d4_bot/configs/buttons.yaml` — **modified**: add `move_duration` command atom per F-CFG-3 grow-on-demand policy. Validate via F-DIAG-3 (`diag_udp_echo.py --command move_duration`) before the first live run.

**Acceptance — `verify_phase_4a.py` [live]:**
- Marker pinned across open ground (no obstacles), ~20–30 s of travel: character follows the guide and stops in `ARRIVED` when the guide vanishes at the destination; script exits cleanly reporting the terminal status. Three consecutive successes.
- Guide-lost handling: unpin the marker mid-run → processor enters `SEARCHING`, holds its grace period, then terminates with `guide_lost` rather than wandering (y/n).
- Guide-lost handling: unpin the marker mid-run → processor enters `SEARCHING`, holds its grace period, then terminates `arrived` with `via_backstop=True` after `nav_arrow_only_arrival_backstop_ticks` rather than `guide_lost` (y/n). See ADR-021.
- Latency discipline spot-check: run with `--record`; the verify script inspects the action log + frames to confirm no steering action was emitted within `latency_frames` + burst-duration ticks of the previous action. **[replay-checkable from the recording]**
- **Pre-run gates:** `configs/navigation.yaml` populated with concrete tuned values (no factory defaults); `move_duration` in `buttons.yaml` verified via `diag_udp_echo.py` — the character visibly moves in the intended direction for the intended duration.

### Phase 4a.1 — Reliability pass: minimap-pin detection and compound-signal arrival

**Status record:**
- **Part 1 (minimap-pin detector, F-DET-3):** Complete. Commits `6e4def0` and
	`4620c75`. Date: 2026-07-18.
- **Part 2 (compound-signal arrival amendment):** Complete. Date: 2026-08-06.
	Commits: `0e8a585` (config tuning), `5bdfb1e` (processor amendment),
	`f5cc93c` (test coverage), `e4cb93d` and `57cf194` (telemetry).
	See ADR-021 for the arrival-discriminator decisions taken during
	implementation. Live acceptance not yet run.

Scope: implement a minimap-pin detector using OpenCV template matching. Wire pin_visible / pin_position into GameState. Amend NavigationProcessor's arrival heuristic to require both nav_arrows AND pin lost per Interpretation A (single both_lost counter). Tune arrival_confirm_ticks from 120 back to 24. See ADR-015.

Rationale: Phase 4a's wide arrival timeout (2 seconds) is a tax on real-arrival response and vulnerable to detector failures longer than 2 seconds. Compound signal eliminates the tax while being strictly safer against single-detector hiccups.

Files expected to change:
- `configs/minimap_pin_template.png` — new binary asset, single reference image cropped from a real minimap screenshot.
- `configs/navigation.yaml` — new pin-detector config keys, new backstop timeout key, arrival_confirm_ticks retuned.
- `src/d4_bot/detectors/minimap_pin.py` — new detector.
- `src/d4_bot/state.py` — pin_visible, pin_position fields added to GameState.
- `src/d4_bot/processors/navigation.py` — arrival heuristic amended.
- `scripts/diag_minimap_pin_tuner.py` — new diagnostic script.
- `scripts/run_nav.py` — verbose output extended for pin state.
- `scripts/verify_phase_4a.py` — audit updated if it references arrival timing.
- `FEATURE_SPECS.md` — F-DET-3 added, F-NAV-1 amended (both handled in ADR-015's docs commit).
- `ARCHITECTURE.md` — ADR-015 added.

Implementation sequence (three commits):
1. Docs commit: this ADR + F-DET-3 + F-NAV-1 amendments. (This block.)
2. Detector + GameState wiring + tuner diagnostic. Navigation arrival unchanged from Phase 4a. Purpose: prove detector reliability in isolation before it affects live runs.
3. Arrival heuristic amendment consuming the new signal. Tune arrival_confirm_ticks. Update verbose output.

Acceptance:
- Diagnostic run: `diag_minimap_pin_tuner.py` on a recorded navigation run shows correct pin_visible transitions from arrival start (pin at border) through mid-transit (pin visible in interior) through arrival (pin disappears).
- Live: three consecutive `--verbose` runs where character reaches a pinned destination and terminates `arrived` with arrival_confirm_ticks set to 24.
- Live: one run where nav_arrow detector is deliberately degraded (e.g., min_confidence set to 0.9) but pin detector remains healthy - the character still reaches destination and terminates arrived via backstop or via pin becoming lost simultaneously with the degraded arrow.
- Live: one run started with no pin (no destination set). Expected: `terminal=guide_lost` after search_grace_ticks, not false arrived.

### Phase 4b — Stuck detection, recovery, the full milestone

**Validated against bot_framework commit:** ________

**Features:** F-NAV-3 (StuckMonitor + RecoveryLadder), F-NAV-1 completed (`STUCK_RECOVERY` state), F-FLOW-2 finalized.

**Files to create:**
- `d4_bot/src/d4_bot/recovery.py`
- `d4_bot/src/d4_bot/processors/navigation.py` **modified** (add recovery state wiring only — no steering rework)

**Acceptance — `verify_phase_4b.py` [live] — this is the milestone gate:**
- Wall test: deliberately steer into a wall → rung 1 triggers within ~1.5 s of visible stop; repeated blockage escalates rungs in order; ladder resets after confirmed movement (y/n per behavior).
- **Milestone run:** marker pinned ≥30 s away across at least one obstacle; one stuck event induced mid-run (corner); character recovers, resumes steering, reaches the marker, processor reaches `ARRIVED`, clean exit. **Three consecutive successful runs.**
- Unrecoverable path: physically trap the character (or exhaust rungs against an unpassable corner) → clean `stuck_unrecoverable` exit, no flailing loop. Operator restarts the run manually — that's the accepted recovery-of-last-resort (per session decision; a self-restarting wrapper is deferred).

**Milestone completion ritual:** tag `bot_framework` (e.g., `v0.2.0-nav-milestone`), record both repos' hashes here, and re-upload the updated CLAUDE.md/context per your dual-maintenance habit.

---

## Phase 5 — Combat Milestone (M1)

**Prerequisites:** Phase 4b.

### Phase 5a — Combat detection

**Validated against bot_framework commit:** ________

**Prerequisites:** Phase 4b.

**Features:** F-DET-4, F-DET-5, F-DET-6, F-DIAG-5, GameState extension.

**Files to create:**
- `d4_bot/configs/detectors/enemy_health_bar.yaml`
- `d4_bot/configs/detectors/health_globe.yaml`
- `d4_bot/configs/detectors/revive_screen.yaml`
- `d4_bot/scripts/diag_combat_tuner.py`
- `d4_bot/scripts/verify_phase_5a.py`
- `d4_bot/configs/rois.yaml` **modified**
- `d4_bot/src/d4_bot/state.py` **modified**

**Operator measurement task (verbatim):** The F-DIAG-4 measurement task is reframed: capture normal, elite, and boss bars and identify the stable invariant across all three, rather than identifying distinguishing features.

**Acceptance — `verify_phase_5a.py`:**

### Phase 5b — Combat processor (M1 milestone gate)

**Validated against bot_framework commit:** ________

**Prerequisites:** Phase 5a.

**Features:** F-CBT-1, F-CBT-2, F-CBT-3.

**Files to create:**
- `d4_bot/src/d4_bot/processors/combat.py`
- `d4_bot/src/d4_bot/combat/loadout.py`
- `d4_bot/scripts/run_combat.py`
- `d4_bot/scripts/verify_phase_5b.py`

**Acceptance — `verify_phase_5b.py` [live] — this is the M1 milestone gate.**
Character parked in a spawn-active area with the M1 loadout, away from
dense interactables, no navigation running. Across three consecutive
sessions:
- Every spawned normal enemy is engaged and killed.
- Sweep locates off-cone enemies and re-engages.
- `combat_clear` is reached when the area is genuinely clear.
- A boss or elite in range routes via the ADR-020 boss bypass straight
	to ATTACKING without a preceding sweep.
- A potion fires when health drops below `potion_threshold`.
- An induced unkillable or obstructed target exits cleanly with
	`combat_timeout`.
- A death exits cleanly with `character_dead`.
- Latency discipline spot-check via `--record`: no verdict is reached
	within `latency_frames` of the emission or press it evaluates.

Milestone completion ritual: tag `bot_framework`, record both repos'
hashes here, refresh CLAUDE.md.

---

## Phase 5+ — Deferred (listed only; each needs its own planning pass)

Milestone-level ordering and parity scope for these items now governed by ROADMAP.md; this table remains the d4_bot execution ledger.

| # | Item | One-liner |
|---|---|---|
| 5 | Processor + YAML-loop composition | The named framework gap from ADR-006; unlocks "navigate, then run a scripted sequence" activities |
| 6 | Self-restarting run wrapper | Restart-on-terminal-status (game_bot FlowRestartException intent) |
| 7 | Fishing absorption | Port diablo_bot's farm_v1 YAML + detector configs into d4_bot; archive diablo_bot |
| 8 | Minimap position tracking | Only if a concrete activity demands routes; re-scoped from scratch, not revived from game_bot |
| 9 | Town/menuing scripted loops | YAML content loops using template detectors + season icons |
| 10 | Halo migration | Gen-3 stack as FrameProcessors on the framework; first external test of contrib/ml |

---

## Sequencing Rationale (one paragraph, for future-you)

The order follows FEATURE_SPECS §11's dependency graph and front-loads the two highest-risk integrations: firmware command correctness (Phase 1, where button-index bugs die in `diag_udp_echo` instead of inside navigation) and YOLO-on-this-rig (Phase 2, proven against recorded frames before any decision logic depends on it). The Phase 1 recorded dataset makes Phases 2–3 mostly replay-testable, so the only phases requiring the game live and you at the controls are 1, 2's tuning steps, and 4. Phase 4 splits so that when the milestone run fails, you know whether steering or recovery broke — they never land untested in the same change.

*End of BUILD_PLAN.md. Next document: COPILOT_PROMPTS.md.*
