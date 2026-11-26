# TROUBLESHOOTING.md — d4_bot

**Status:** The recovery playbook. Read this when Copilot goes off the rails, when the bot misbehaves at runtime, or when you face a decision alone.
**Prime directive:** Diagnose before editing. Every section here ends in evidence-gathering steps or a paste-ready correction prompt — never in "just tweak it until it works." Silent tweaks are how the design docs and the code drift apart.

---

## Part 1 — Copilot Failure Modes

For each: how to recognize it in generated code (often without deeply reading it), and the correction prompt. All correction prompts are self-contained; paste as-is with slots filled. If two corrections in a row fail, abandon the thread and restart from the phase prompt in COPILOT_PROMPTS.md Section B — long argument threads degrade agent output.

### FM-1 — Invented framework APIs

**What it looks like:** imports that aren't in FEATURE_SPECS.md §0 (`from framework.utils import ...`, `from framework.vision import ...`), method calls that don't exist (`history.get_delayed(...)`, `capture.read()`), or keyword arguments the real signature doesn't take. Copilot states these with total confidence.

**Fast check:** grep the diff's `from framework` lines against the §0 table. Anything not in the table is invented until proven otherwise by reading framework source.

**Correction prompt:**
```
You used <import/call>, which does not exist in bot_framework. The complete
allowed import surface is FEATURE_SPECS.md Section 0. Open the actual source
file in the bot_framework folder for the class you need, quote me its real
signature, and rewrite using only real APIs. If the capability you wanted
genuinely does not exist in the framework, stop and tell me what is missing
instead of substituting.
```

### FM-2 — Reimplementing existing framework classes

**What it looks like:** a new class in `d4_bot/src/` whose name or docstring resembles a framework component — a capture wrapper, a template matcher, a frame ring buffer, a YAML loop runner, a "simple UDP sender." Frequently triggered when Copilot hits FM-1, can't find the API it invented, and writes a local substitute instead of stopping.

**Fast check:** any new class in `d4_bot` doing capture, matching, history, loop interpretation, or transport. Those five jobs are framework jobs, full stop.

**Correction prompt:**
```
You wrote <class>, which reimplements <framework class> from bot_framework.
Delete it entirely and import the framework class per FEATURE_SPECS.md
Section 0. Read the framework class's source first and adapt the calling code
to its real interface. If it lacks something you need, stop and report the gap
— per ARCHITECTURE.md §3 missing mechanisms get added to the framework, never
worked around in the game repo.
```

### FM-3 — Ignoring the capture-latency rule

**What it looks like:** three flavors, escalating subtlety: (a) the literal `6` (or the stale `3`) in timing logic, tick counts, or comparisons; (b) checking a visual condition immediately after emitting an action — no pre-effect window at all; (c) using `time.sleep()` or wall-clock deltas where frame_id arithmetic against FrameHistory is required.

**Fast check:** grep the diff for `sleep`, for bare numeric literals near `frame_id`/`tick`, and for any state read in the same tick an action was emitted.

**Correction prompt:**
```
This code violates the capture-latency rule (copilot-instructions.md rule 1,
ARCHITECTURE.md §4). Capture is latency_frames behind real time; no visual
conclusion about an action is valid within latency_frames ticks of emitting it
(plus the command's duration for duration commands). Fix by: (1) removing
every hardcoded latency literal — the value is injected/read from
capture.latency_frames; (2) implementing the pre-effect window with FrameHistory
frame_id arithmetic; (3) removing all time.sleep and wall-clock timing —
BotLoop owns time. Show me the specific lines you changed.
```

### FM-4 — Two-packet press/release commands

**What it looks like:** paired "press" and "release" payloads, a scheduled release (timer, second UDP send, `duration` implemented in Python instead of in the packet), or buttons.yaml entries with separate down/up steps. game_bot's JSON libraries were built this way, so any code Copilot pattern-matches from that era carries the disease.

**Fast check:** `diag_udp_echo.py` prints one payload per activation, or it doesn't. Also grep for `release` in the diff.

**Correction:** use COPILOT_PROMPTS.md **D-2** verbatim — it exists precisely for this.

### FM-5 — Hardcoded button indices, coordinates, paths, thresholds

**What it looks like:** `button_1` in game logic; `(899, 217, 120, 120)` anywhere outside `rois.yaml`; `E:\...` or absolute paths in code; magic numbers for tick counts, durations, or confidence values inline.

**Fast check:** grep the diff for `button_`, digit-quadruples, drive letters, and numeric literals inside processor/recovery logic.

**Correction prompt:**
```
This code hardcodes <the thing>. Per copilot-instructions.md rule 5: pixel
coordinates live only in configs/rois.yaml; button indices only in
configs/buttons.yaml; thresholds, durations, cadences, and tick counts are
config values loaded at startup; paths are relative and configured. Move each
literal to its correct home and have the code reference it by semantic name.
List each literal you relocated and where it now lives.
```

### FM-6 — Unrequested threads, async, or timers

**What it looks like:** `threading`, `asyncio`, `Timer`, `Queue`, background workers, callbacks — usually justified in a comment as "for performance" or "to avoid blocking." Copilot reaches for this reflexively for anything involving capture or periodic work.

**Correction prompt:**
```
You introduced <threading/async/timer>, which violates copilot-instructions.md
rule 4 and ADR-004. Everything runs inside the synchronous BotLoop tick;
concurrency of concerns is handled by detector cadence, not parallelism.
Rewrite fully synchronous. If you believe this cannot work synchronously,
stop and explain the specific bottleneck with numbers instead of implementing
around it.
```

### FM-7 — Scope creep and "improvements"

**What it looks like:** logging frameworks, retry decorators, plugin systems, abstract base classes for things with one implementation, config options nobody asked for, "robustness" fallbacks that mask real failures, files modified outside the task's list. Individually harmless-looking; collectively how a codebase becomes unmaintainable by a non-engineer.

**Correction prompt:**
```
You implemented beyond the task scope: <list>. Per copilot-instructions.md
rule 6, remove everything not named in the task prompt and its FEATURE_SPECS
section — including <specific extras>. Fallbacks that hide failures are worse
than loud errors in this project. Restore any file you touched outside the
stated file list.
```

### FM-8 — Silent spec drift

**What it looks like:** the code runs, the field/state/file names are *almost* the spec's (`is_moving` vs `character_moving`, `LOST` vs `SEARCHING`, detector file named differently from its registry key). Each mismatch is trivial; the accumulation breaks every future prompt that references spec names.

**Fast check:** after any phase, spot-grep three or four spec names from the relevant FEATURE_SPECS section against the codebase.

**Correction prompt:**
```
Names in this code drift from FEATURE_SPECS.md: <code name> should be
<spec name>, <...>. Rename to match the spec exactly — the spec names are
referenced by every future prompt and document, so the spec wins even when
your name is arguably better. If you believe a spec name is genuinely wrong,
say so and I will change the spec, not the convention.
```

---

## Part 2 — Common Runtime Bugs

### RB-1 — Detector "never fires" (wait_visual or GameState field stuck False)

Run COPILOT_PROMPTS.md **C-4**'s checklist. Summary of the order that finds it fastest: ① latency gate (condition evaluated inside the gated/pre-effect window — the #1 false bug in this system) → ② `diag_detector_tuner` ground truth → ③ ROI placement via `diag_roi_viewer` (did the HUD move? resolution change? new season art?) → ④ the visual is shorter-lived than detection cadence + latency (a fading indicator sampled too late — the fishing-indicator lesson).

### RB-2 — Stale YOLO readings driving bad steering

**Symptom:** character steers toward where the guide *was*; overshoots turns; oscillates.
**Diagnose:** log `GameState.staleness(nav_arrows_frame_id)` per burst decision. If staleness regularly exceeds cadence, inference is slower than budgeted — lower the input size or raise cadence honestly rather than pretending. If staleness is fine but steering still lags, the burst logic is probably re-aiming from detections that predate the previous burst's completion (F-NAV-2 violation) — audit with the Phase 4a recorded-run latency check.

### RB-3 — Controller drift / movement that never stops

**Symptom:** character keeps walking after the bot stops, or inputs feel "sticky."
**Diagnose:** ① confirm every emitted payload is duration-form (`diag_udp_echo`, FM-4) — a stray non-duration packet leaves state latched in the firmware; ② check duration_ms values against what you intended (a 5000 where a 500 belongs reads as drift); ③ power-cycle the Arduino to clear latched state, then reproduce with a single command before blaming the bot logic; ④ UDP is fire-and-forget — a dropped packet loses a burst (harmless, self-healing on the next burst) but should never cause *sustained* motion; sustained motion is always a latched command.

### RB-4 — Latency-gate false negatives ("the gate ate my detection")

**Symptom:** a YAML loop's wait_visual misses a brief visual because it appeared during the gated window after a command.
**Understand first:** the gate is correct — a detection inside that window could be pre-effect imagery. The bug is sequence design.
**Fix pattern:** restructure the loop so the command completes ≥ latency_frames before the visual can appear (insert a `wait`), or watch for a longer-lived downstream visual instead of the brief one. Never "fix" by weakening the gate (ARCHITECTURE §3 rule 4).

### RB-5 — Minimap motion desync (stuck detection lying)

**Symptom:** stuck triggers while walking fine, or never triggers while pinned against a wall.
**Diagnose in order:** ① `diag_roi_viewer` — is the `minimap` ROI still snug (HUD scale/position changed? new season UI?); ② `diag_detector_tuner --detector minimap_motion` while deliberately standing/walking — watch raw vs debounced; standing in town with NPCs crossing the minimap can read as motion → tighten `changed_fraction`; walking through visually sparse terrain can read as still → loosen `diff_threshold`; ③ confirm StuckMonitor only evaluates outside pre-effect windows (FM-3c if not); ④ if thresholds can't separate the cases, shrink the ROI to the minimap's center third, where player-relative scroll is strongest.

### RB-6 — Loop FPS collapse

**Symptom:** loop FPS drops well below 60; everything gets sluggish and timing math degrades.
**Diagnose:** the historical cause on this project is **full-frame work in the hot path** (the freshness checker throttled to 7 fps). Check, in order: ① any detector doing full-frame diffs/copies (FG-2 forbids it — audit); ② YOLO running every tick (cadence misconfigured or the modulo check broken); ③ FrameRecorder writing every frame at high quality (raise `every_n`); ④ debug drawing/imshow left enabled in a diagnostic import path. Only after all four are clean does the ADR-004 escalation (capture thread) become a legitimate conversation — and it requires a new ADR entry.

### RB-7 — Replay and live disagree

**Symptom:** acceptance passes on replay, fails live (or vice versa).
**Understand:** replay is deterministic and typically runs with `latency_frames=0` recordings played through ReplayCapture; live has real latency, dropped frames, and lighting/weather variance. Replay validates *detector truth and logic*, live validates *timing and control*. When they disagree on detection, re-record — the game's look drifted (season, time-of-day, region). When they disagree on behavior, it's almost always timing: audit pre-effect windows against the live recording's action log (the Phase 4a technique).

### RB-8 — Capture runs at roughly half expected FPS despite correct device config

**Symptom:** capture runs at roughly half expected FPS despite correct device config.
**Cause:** another process holds the DirectShow capture device open concurrently (browser tab, recording software, a previous bot process that didn't release).
**Fix:** identify and close the competing consumer, then restart the capture session. Standing habit: before any bot session, verify nothing else has the GC573 open.
**Related:** same root-cause family as exclusive-access black frames — a competing consumer can degrade FPS (shared access) or return black frames entirely (exclusive access held elsewhere).


### RB-11 — Black frames despite successful open

**Symptom:** capture opens successfully with correct geometry, but early frames are all black (mean ~0) before live video appears.
**Cause:** capture-source warm-up window. On this rig, the GC573 emits an initial run of black frames after open (measured as 83 frames, ~1395 ms at 60 fps) and then runs normally.
**Fix:** discard frames after open until the first live frame (non-trivial mean), bounded by a warm-up timeout. From ADR-022 onward, the framework handles this in capture warm-up before control returns to callers.
**Do-not:** do not treat black frames within the first ~2 seconds after open as capture-device failure; do not use OBS-open-as-workaround (withdrawn as misdiagnosis); and do not conflate this with RB-8.
**RB-8 distinction:** RB-11 is transient black warm-up after a successful open; RB-8 is sustained half-rate capture caused by concurrent device sharing.

### RB-9 — Copilot agent session is running system Python despite a correctly provisioned venv

**Symptom:** Copilot agent session runs code whose imports fail or behaves as if packages are missing, despite a correctly provisioned venv.
**Cause:** the agent session silently lost venv context and is running system Python.
**Recognition:** traceback paths under `AppData\Local\Programs\Python` instead of the venv path.
**Fix:** at every Copilot session start, run `python -c "import sys; print(sys.executable)"` and verify it prints the venv path before any other work.

### RB-10 — cv2.imshow fails while capture and inference work fine

**Symptom:** `cv2.imshow` fails or windows never appear in diagnostic scripts, while capture and inference work fine.
**Cause:** `opencv-python-headless` was pulled in as a transitive dependency (yolov5/ultralytics) and shadows the GUI-capable build.
**Recognition:** distinct from a genuine `cv2` install failure — imports succeed, only GUI functions break.
**Fix:** `pip uninstall opencv-python-headless`, then reinstall `opencv-python` (GUI build) in the venv. Durable fix is pinning `opencv-python` explicitly in `bot_framework [ml]` (tracked as QUESTIONS.md environment-hygiene item 2).

### RB-12 — pip.exe blocked by Application Control → use python -m pip

**Symptom:** running `pip.exe` is blocked by Windows Application Control.
**Fix:** use the intended Python interpreter to install packages, for example `python -m pip install <package>`.

---

## Part 3 — "When in Doubt" Defaults

Decisions you'll face without me. The default is not always optimal; it is always *safe and reversible*, which matters more when you can't ask.

| Decision | Default | Why |
|---|---|---|
| Where does a new class go? | `d4_bot/src/d4_bot/`. Promote to framework contrib later via prompt D-1 if it passes the "works for Halo unchanged" test. | Demotion is embarrassing; promotion is a clean refactor. |
| New detector: which type? | Cheapest that can work: `roi_motion` → `color_match` → `template_match` → `yolo`, in that order. | Cost, tunability, and Copilot-simplicity all rank the same way. |
| Threading vs sync? | Sync. Always. The only exception is written in ADR-004 and requires a new ADR. | See FM-6. |
| A new tunable number? | Config key, never a literal. If unsure which file: detector-ish → that detector's YAML; command-ish → buttons.yaml; anything else → a `nav` section in a processor config. | One rule, zero exceptions, greppable later. |
| Naming anything? | ARCHITECTURE §10 table. If the table doesn't cover it, snake_case, semantic not physical, and add it to the table. | The table is the convention's single home. |
| A brief visual keeps getting missed? | Lower that detector's cadence to 1 (every tick) before touching thresholds. | Sampling failure and threshold failure look identical; eliminate the cheap one first. |
| Copilot proposes A vs B and both seem fine? | The one that touches fewer files and adds no new abstractions. | Modular over rewrite (standing rule); reversibility beats elegance. |
| Something violates a doc but works? | It's wrong. Fix the code, or consciously amend the doc (new ADR entry) — never leave them disagreeing. | Doc-code disagreement is compound interest on confusion. |
| Bot misbehaves live and it's late? | Stop, run once more with `--record`, save the dataset, quit. Diagnose offline against the recording tomorrow. | The recording is worth more than a tired live-debug session — and it's series footage. |

---

## Part 4 — Escalation Path (truly stuck, cannot ask me)

Work the ladder in order; each rung is cheap and produces evidence for the next.

1. **Reproduce minimally.** One script, one component, the smallest input that shows the problem. Most "navigation bugs" become "one detector bug" or "one payload bug" under this pressure. The diag tools exist to make this rung fast.
2. **Read the actual framework source.** Not docs, not memory — the module in `bot_framework/`. Signature and behavior questions die here. Have Copilot walk you through a module: *"Read framework/<module>.py and explain what <class> actually does, step by step, quoting the code."* Copilot explaining real code is far more reliable than Copilot recalling APIs.
3. **Interrogate a recording.** Run with `--record`, then have Copilot write a one-off analysis script over `actions.jsonl` + frames: what was commanded at frame N, what was visible at frame N+latency, where did they diverge? This is the FrameHistory debugging pattern from the RL work, offline.
4. **Bisect against the docs.** Diff current behavior against the phase's acceptance criteria — find the *first* phase whose verify script no longer passes and fix there, not at the symptom.
5. **Revert the phase.** Git-revert to the last passing phase boundary and replay the phase prompt from COPILOT_PROMPTS.md in a fresh session. A clean re-execution of a good prompt routinely beats archaeology on a bad thread. This is why phases end in commits.
6. **Decide and log.** If it's a judgment call with no answer in the docs: take the Part 3 default, or the most reversible option, and write an ADR entry in ARCHITECTURE.md §12 stating what you chose and why. Future-you (or a future AI collaborator reading the repo) inherits the reasoning instead of the mystery.
7. **Bank it for later.** Keep a `QUESTIONS.md` at the repo root for things you'd have asked me. Any capable LLM you gain access to later — or a future season of the series with a new collaborator — starts by reading the five docs plus that file. The doc set was built so the *documents* are the collaborator of record, not any one model.

---

*End of TROUBLESHOOTING.md. End of the five-document set.*
