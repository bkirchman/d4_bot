# COPILOT_PROMPTS.md — d4_bot

**Status:** The conversion layer between the design docs and Copilot output. Highest-leverage document in the set.
**Workflow model (ADR-011):** Copilot **agent mode** in VS Code, working inside the `d4_bot` repo (with `bot_framework` open as a sibling folder in the workspace so the agent can read framework source). Section A is committed at `.github/copilot-instructions.md` and is therefore *always* in the agent's context — but every task prompt still restates the guardrails that matter for that task, because defense in depth is free and Copilot's attention is not.

**How to use this document:**
1. Phase work → paste the matching Section B prompt into agent chat, verbatim, filling any `<angle-bracket>` slots.
2. Recurring chores → Section C. Refactors → Section D.
3. If output violates a guardrail → don't argue in-thread; use the matching correction prompt from TROUBLESHOOTING.md, or start a fresh agent session with the phase prompt again. Fresh sessions beat long arguments.
4. After any accepted output → run the phase's `verify_phase_N.py`. The script's verdict is the review.

---

## Section A — Standing Preamble

Commit the block below verbatim as `d4_bot/.github/copilot-instructions.md` (Phase 0). It is written to Copilot in the second person.

```
You are implementing d4_bot, a Diablo 4 automation bot built on the bot_framework
package (sibling repo, installed editable). ARCHITECTURE.md, FEATURE_SPECS.md and
BUILD_PLAN.md at the repo root are the design authority. When your plan and those
documents disagree, the documents win. When these instructions and the task prompt
disagree, ask before proceeding.

HARD RULES — violating any of these makes the output wrong regardless of whether
it runs:

1. CAPTURE LATENCY. OpenCV capture on this rig is 6 frames behind real time. Any
   action's visible effect takes that many frames to appear in captured frames.
   All timing logic must read capture.latency_frames (or an injected
   latency_frames parameter) at runtime. NEVER write the literal 3 or 6 into
   logic. The literal exists only in configs/hardware.yaml. Never evaluate a
   visual condition, stuck verdict, or arrival verdict within latency_frames
   ticks of an emitted action (plus the action's duration, for duration
   commands).

2. FRAMEWORK IMPORTS ONLY. Import framework mechanisms; never reimplement them.
   The complete allowed surface is FEATURE_SPECS.md Section 0. If you believe a
   needed class or function is missing, STOP and say so — do not invent an API
   and do not write a local substitute. Before calling any framework class,
   read its actual source in the bot_framework folder to confirm the signature;
   do not rely on memory.

3. FIRMWARE v2.1. All controller commands are single-packet and self-releasing:
   button_N_duration, hat_duration, move_duration, trigger_duration. NEVER emit
   separate press and release actions. Button indices (button_1 = A, etc.)
   appear ONLY in configs/buttons.yaml — game logic uses semantic command names
   from the command registry. The packet field reference is
   bot_framework/firmware/xbox_controller/protocol.md.

4. NO THREADS. Everything runs inside the synchronous BotLoop tick. No
   threading, asyncio, timers, callbacks, or sleeps inside processors (BotLoop
   owns time). Concurrency of concerns is achieved by detector cadence, not
   parallelism.

5. CONFIGURATION DISCIPLINE. YAML only; no JSON. Pixel coordinates appear only
   in configs/rois.yaml. Thresholds, durations, cadences, and tick counts are
   config values, never literals in code. Buttons, ROIs, detectors, and
   commands are referenced by semantic snake_case names.

6. SCOPE DISCIPLINE. Implement exactly what the task prompt and the referenced
   FEATURE_SPECS section describe. Do not add features, abstractions, fallback
   paths, logging frameworks, or "improvements" that were not asked for. Do not
   modify files outside the task's stated file list. Prefer extending existing
   patterns over rewriting.

OUTPUT CONVENTIONS for every task:
- Begin your reply with the list of files you will create or modify and the
  framework imports you will use. If either differs from the task prompt, stop
  and ask first.
- After implementing, run the tests or verification script named in the task
  and report the actual output.
- Flag every assumption you made explicitly at the end.
```

---

## Section B — Per-Phase Prompts

Fill `<...>` slots. Each prompt assumes the agent can read the committed docs — but names the exact sections so it actually does.

### B-0 — Phase 0: Repo setup and framework wiring

```
Task: Execute Phase 0 of BUILD_PLAN.md exactly as written. Read BUILD_PLAN.md
"Phase 0" and FEATURE_SPECS.md sections FG-4 and F-CFG-1 before writing anything.

Files to create/modify: only those listed in BUILD_PLAN.md Phase 0. The
bot_framework changes (contrib/config module, pyproject [ml] extra) go in the
bot_framework folder as a separate commit.

Guardrails for this phase:
- load_layered_config: deep-merge semantics exactly as FG-4 specifies (scalars
  replace, dicts merge recursively, lists replace wholesale). No schema
  validation, no env vars, no caching.
- hardware.yaml gets this rig's values from the F-CFG-1 table verbatim,
  including capture.latency_frames: 6 — the one sanctioned home for that literal.
- The config loader must fail loudly naming any missing required key.
- Do NOT scaffold any detector, processor, or navigation code. Empty packages
  only.

Acceptance: implement scripts/verify_phase_0.py per BUILD_PLAN.md and make it
pass. Run it and show me the output.
```

### B-1 — Phase 1: Hardware path end-to-end

```
Task: Execute Phase 1 of BUILD_PLAN.md. Read BUILD_PLAN.md "Phase 1" and
FEATURE_SPECS.md sections F-CAP-1, F-CFG-2, F-CFG-3, F-CTL-1, F-DIAG-1,
F-DIAG-3, FG-3 first. I am pasting the relevant section of
bot_framework/firmware/xbox_controller/protocol.md below this prompt — it is
the only authority for packet field names.

<PASTE protocol.md COMMAND SECTIONS HERE>

Guardrails for this phase:
- buttons.yaml: exactly two entries — press_a (button_1_duration) and
  press_b (button_2_duration), per F-CFG-3's grow-on-demand policy. Do NOT
  pre-populate a full controller map; additional commands are added in later
  phases when a consumer needs them. Button indices
  live here and nowhere else (button_0=X, button_1=A, button_2=B, button_3=Y;
  hat_y positive = up). Every command is single-packet duration form.
- build_command_registry: no index literals in the function body, no press/
  release pairs, no sockets — payloads only; UDPXboxOutput does transport.
- FrameRecorder (in bot_framework/framework/contrib/recording/): per FG-3.
  No threads, no video encoding. Output must be readable by ReplayCapture —
  read ReplayCapture's source first to match its directory convention.
- diag_udp_echo.py must print the exact payload it sends and must FAIL if any
  registry entry is a press/release pair.
- The capture builder asserts 1920x1080 from the first frame's shape and
  prints latency_frames read from the capture object.

Acceptance: scripts/verify_phase_1.py per BUILD_PLAN.md (live checks are
operator y/n prompts). Implement it; I will run the live parts.
```

### B-2 — Phase 2: Visual detection foundation

```
Task: Execute Phase 2 of BUILD_PLAN.md. Read BUILD_PLAN.md "Phase 2" and
FEATURE_SPECS.md sections FG-1, FG-2, F-DET-1, F-DET-2, F-CFG-4, F-DIAG-2,
F-DIAG-4 first.

Guardrails for this phase:
- YoloDetector goes in bot_framework/framework/contrib/ml/ and must contain
  zero Diablo knowledge — no default class names, paths, or thresholds. Cadence
  behavior exactly per FG-1: inference only on frame_id % cadence == 0,
  cached result returned otherwise, Detection.frame_id always the ORIGIN frame.
  No threading. No drawing inside the class. Model loaded once in __init__.
- RoiMotionDetector goes in bot_framework contrib detection as an ADDITIVE
  change — do not touch ColorMatchDetector or TemplateMatchDetector. Numpy
  only. It stores only the previous ROI crop, never a full frame, and does no
  full-frame work (a previous freshness checker throttled the loop to 7fps —
  that failure mode is why FG-2's guardrails exist).
- d4_bot side: build_detectors resolves ROI names from rois.yaml and season
  overrides via load_layered_config; unknown detector type or ROI name fails
  loudly naming the file.
- diag_detector_tuner.py displays values; it never writes config files.
- The replay acceptance harness runs against frames/walk_stand_01/ using
  ReplayCapture.

Acceptance: scripts/verify_phase_2.py per BUILD_PLAN.md. Run the replay parts
and show me real output; leave the live y/n parts to me.
```

### B-3 — Phase 3: Game state model

```
Task: Execute Phase 3 of BUILD_PLAN.md. Read BUILD_PLAN.md "Phase 3" and
FEATURE_SPECS.md sections F-GS-1, F-GS-2, F-GS-3 first.

Guardrails for this phase:
- GameState is a frozen dataclass with exactly the fields in F-GS-1, including
  the future stubs (enemy_present, screen_mode) with their defaults. Every
  detector-derived field carries its origin frame_id.
- StateDiff field names follow F-GS-2 exactly (movement_started,
  movement_stopped, nav_guide_appeared, nav_guide_lost, enemy_appeared).
  diff(None, curr) is all-False.
- GameStateUpdater contains NO decision logic, emits NO actions, constructs NO
  detectors — it feeds the frame to the detectors it was given and assembles
  the snapshot.
- tests/test_state.py: table-driven diff edges, immutability, staleness math.

Acceptance: scripts/verify_phase_3.py — pytest plus the replay check over
frames/walk_stand_01/ per BUILD_PLAN.md. Run both and show output.
```

### B-4a — Phase 4a: Steering walk

```
Task: Execute Phase 4a of BUILD_PLAN.md. Read BUILD_PLAN.md "Phase 4a" and
FEATURE_SPECS.md sections F-NAV-1, F-NAV-2, F-CTL-2, F-FLOW-1 in full before
writing anything. This is the highest-risk phase in the project; follow the
spec literally.

Guardrails for this phase:
- NavigationProcessor implements ONLY the states STEERING, PRE_EFFECT,
  SEARCHING, ARRIVED. Do not implement STUCK_RECOVERY, StuckMonitor, or
  RecoveryLadder — they are Phase 4b. Leave a clearly marked seam.
- latency_frames is injected at construction from the capture object in
  run_nav.py. No literal anywhere. The PRE_EFFECT window is latency_frames
  plus the emitted command's duration converted to ticks, computed via
  FrameHistory frame_id arithmetic — no wall-clock sleeps, no time.sleep,
  no timers.
- Movement is short bursts (duration from config, not a literal) via
  move_duration payloads from the command registry. Each burst's direction is
  recomputed from detections whose origin frame_id postdates the previous
  burst's real-world completion (F-NAV-2).
- The processor reads GameState only — it never calls detectors directly and
  never touches UDP.
- ARRIVED per the F-NAV-1 arrival condition: nav_guide_lost sustained
  arrival_confirm_ticks with recent movement context. SEARCHING handles the
  no-recent-movement lost-guide case.
- run_nav.py mirrors the run_farm_v1.py pattern: build everything, print the
  latency_frames banner, step until the processor reports terminal status,
  clean stop. Flags: --record, --season, --config-dir.

Acceptance: scripts/verify_phase_4a.py per BUILD_PLAN.md, including the
replay-checkable latency-discipline audit of a recorded run's action log.
Implement it; the live runs are mine.
```

### B-4b — Phase 4b: Stuck detection and recovery

```
Task: Execute Phase 4b of BUILD_PLAN.md. Read BUILD_PLAN.md "Phase 4b" and
FEATURE_SPECS.md section F-NAV-3, plus the F-NAV-1 state machine, first.

Guardrails for this phase:
- New file recovery.py: StuckMonitor and RecoveryLadder per F-NAV-3 signatures.
  Stuck requires ALL of: movement burst active or just completed, pre-effect
  window elapsed, character_moving False for stuck_ticks consecutive ticks.
  All tick counts from config.
- The ladder is exactly three rungs (reverse, offset-angle re-approach via
  the steering helper — movement direction, never camera — and B escape),
  each with cooldown and max attempts from config, escalating in order,
  resetting to rung 1 after any confirmed-movement window. Rung exhaustion =
  terminal status stuck_unrecoverable; the processor stops cleanly. Do NOT
  add a re-pin rung, a random-walk rung, or an auto-restart — restart is the
  operator's job.
- navigation.py changes are ADDITIVE: wire the STUCK_RECOVERY state in;
  do not rework steering, PRE_EFFECT, or arrival logic. If you believe
  steering must change to accommodate recovery, stop and say so.

Acceptance: scripts/verify_phase_4b.py per BUILD_PLAN.md (live, operator
y/n). This phase's acceptance is the project milestone gate.
```

---

## Section C — Recurring Task Prompts

### C-1 — Add a new named command

```
Task: Add one new command to d4_bot's command registry.
Command name: <name>   In-game act: <description>
Firmware form: <button_N_duration | hat_duration | move_duration |
trigger_duration>, parameters: <index/axis/direction>, duration_ms: <value>.
I am pasting the matching protocol.md section below.

<PASTE protocol.md SECTION>

Rules: edit ONLY configs/buttons.yaml (and nothing in commands.py unless the
schema genuinely cannot express this command — in which case stop and tell me
why). Single-packet self-releasing form only. Button indices: button_0=X,
button_1=A, button_2=B, button_3=Y; hat_y positive=up.
Verify: run scripts/diag_udp_echo.py --command <name> and show me the printed
payload.
```

### C-2 — Add a new detector

```
Task: Add one new detector named <name>.
Type: <yolo | roi_motion | color_match | template_match>
Watches: <what on screen, and which ROI name — add the ROI to rois.yaml if new,
coordinates from my diag_roi_viewer session: [x, y, w, h]>
Tuning values: <thresholds / model path / cadence>.

Rules: create configs/detectors/<name>.yaml only. build_detectors in
src/d4_bot/detectors.py must construct it with NO code changes — if it can't,
stop and tell me why instead of special-casing. Coordinates go in rois.yaml
only. Use framework detector classes from FEATURE_SPECS.md Section 0; do not
write a new detector class.
Verify: scripts/diag_detector_tuner.py --detector <name> runs and displays it.
```

### C-3 — Write a YAML content loop for a new activity

```
Task: Write a new content loop configs/loops/<name>.yaml for the framework's
ContentLoopProcessor.
Activity, step by step in plain English: <describe the sequence, including
what visual conditions gate which steps>.

Rules: only the six framework step types (command, wait, wait_visual, branch,
repeat, call). Commands and detectors are referenced by their registry names —
list the ones you use and confirm each already exists in buttons.yaml /
configs/detectors/; if one is missing, stop and tell me instead of inventing
it. Respect the latency gate: never place a wait_visual or branch that must
evaluate within latency_frames ticks of a command — insert a wait step sized
in ticks from the capture's latency if the sequence is that tight, and say so.
Match the YAML schema used by configs/loops/ examples and
load_loops_from_file's parser — read that parser's source first.
Verify: the loop parses via load_loops_from_file without error.
```

### C-4 — Debug: a wait_visual step never fires

```
Task: Diagnose why the wait_visual step <step> in configs/loops/<file> never
fires. Do not change any code or config until you have reported findings.

Work through, in order, reporting evidence for each:
1. Latency gate: is the step within latency_frames ticks of a prior command
   step? (This is the most common cause.)
2. Detector truth: does scripts/diag_detector_tuner.py --detector <name> show
   the condition actually detected when the visual is on screen? If not, is it
   ROI placement (check with diag_roi_viewer) or thresholds?
3. Registry naming: does the loop's detector name exactly match the config
   filename / registry key?
4. Timing: is the visual shorter-lived than the detection cadence plus
   latency (e.g., a brief indicator that fades before an off-cadence detector
   samples it)?
Propose the single smallest fix and wait for my approval before applying it.
```

### C-5 — Debug: a controller command produces no visible movement

```
Task: Diagnose why command <name> produces no visible in-game effect. Do not
change code or config until you have reported findings.

Work through, in order, reporting evidence:
1. Payload truth: run scripts/diag_udp_echo.py --command <name>; is the
   printed payload single-packet duration form with the intended index/axis?
   (button_0=X, button_1=A, button_2=B, button_3=Y; hat_y positive=up.)
2. Transport: does UDPXboxOutput point at the hardware.yaml IP/port, and is
   response_mode reporting anything?
3. Duration: is duration_ms long enough to register in-game (>50ms)?
4. Game context: does the game currently accept that input (correct screen
   mode, not in a menu)?
5. Expectation timing: are we judging "no effect" within latency_frames of
   the command? The effect may be visible but late.
Propose the single smallest fix and wait for my approval.
```

### C-6 — Seasonal asset refresh (every ~12 weeks)

```
Task: New Diablo 4 season setup, season number <NN>.
Steps:
1. Create configs/seasons/s<NN>/icons/ and configs/seasons/s<NN>/overrides.yaml
   (start as a valid empty mapping).
2. Walk me through capturing fresh icon templates with
   scripts/capture_icons.py for each template detector currently in
   configs/detectors/ — list them for me first.
3. For each threshold I report as changed from my diag_detector_tuner session,
   put the override under the correct key path in s<NN>/overrides.yaml —
   overrides must mirror the base config structure exactly (load_layered_config
   deep-merge semantics).
4. Update active_season in hardware.yaml.
Do not touch base configs, Python files, or previous season folders. Verify:
build_detectors constructs everything with --season s<NN>.
```

---

## Section D — Refactoring Prompts

### D-1 — Promote game code into a framework contrib module

```
Task: Extract <class/function> from d4_bot/<path> into
bot_framework/framework/contrib/<area>/ because it passes the portability
test: it would work unchanged for another game.

Rules:
- The extracted mechanism must contain zero Diablo knowledge — no D4 ROIs,
  paths, class names, thresholds, or button semantics, not even as defaults.
  Everything game-specific stays behind in d4_bot as constructor arguments or
  config.
- Framework dependency boundary: stdlib + numpy for core contrib; anything
  needing OpenCV-beyond-existing-usage or ML libraries goes under the [ml]
  extra pattern.
- d4_bot then imports it from the new location; delete the old game-side copy
  in the same change — no transitional duplication.
- Additive to the framework: touch no existing framework modules beyond an
  __init__ export.
- Two commits: one in bot_framework, one in d4_bot. Update FEATURE_SPECS.md
  Section 0's import table.
Verify: the current phase's verify script still passes, plus any framework
unit tests you add.
```

### D-2 — Convert two-packet press/release into single-packet duration

```
Task: The code or config at <location> emits separate press and release
actions. This violates the firmware v2.1 contract and must be converted to
the single-packet self-releasing form.

Rules:
- Replace each press+release pair with one button_N_duration / hat_duration /
  move_duration / trigger_duration command whose duration_ms equals the
  original press-to-release interval (ask me if the original interval was
  produced by a sleep or timing loop you cannot statically determine).
- If the pair lives in Python, the fix is almost certainly to route it
  through a named buttons.yaml command instead — prefer that.
- Remove any now-dead release plumbing (timers, scheduled releases, paired
  state tracking).
- protocol.md is the field authority; I will paste the relevant section if
  you need it — ask rather than guess.
Verify: scripts/diag_udp_echo.py for the affected command(s) shows a single
payload per activation.
```

---

*End of COPILOT_PROMPTS.md. Next document: TROUBLESHOOTING.md.*
