# CHEATSHEET.md — How to actually use these documents

One page. When in doubt, start here; this sheet routes you to the right doc.

---

## Which document, when

| You are... | Open |
|---|---|
| About to make (or question) a design decision | **ARCHITECTURE.md** — check §12 Decisions Log first; someone (you) may have already decided |
| About to have Copilot build something | **FEATURE_SPECS.md** — find the feature ID; it is the spec of record |
| Deciding what to work on next | **BUILD_PLAN.md** — the next phase whose Definition of Done isn't met |
| Opening a Copilot session | **COPILOT_PROMPTS.md** — copy the prompt; never freestyle a phase |
| Looking at output that smells wrong, or a bot misbehaving | **TROUBLESHOOTING.md** — Part 1 for bad code, Part 2 for bad runtime |
| Facing a judgment call alone | **TROUBLESHOOTING.md Part 3** defaults, then log an ADR if it was a real decision |

## The build loop (repeat until milestone)

1. Open BUILD_PLAN.md → next unfinished phase. Read its FEATURE_SPECS sections yourself first (10 min — this is the review that matters most).
2. Fresh Copilot agent session → paste the phase's Section B prompt verbatim, fill slots (paste protocol.md sections where the prompt says so).
3. Check the agent's *opening reply*: files list + imports list. Wrong → correct **before** any code exists.
4. Let it work. Don't micro-review; the verify script is the reviewer.
5. Run `scripts/verify_phase_N.py`. Fail → route through TROUBLESHOOTING Part 1; two failed corrections → kill the thread, restart at step 2.
6. Pass → record the `bot_framework` commit hash in the phase header, commit (both repos separately if the framework changed), film your notes, next phase.

## When something breaks — routing

| Symptom | Go to |
|---|---|
| Import/class that doesn't exist, "helpful" new local class | TROUBLESHOOTING FM-1 / FM-2 |
| Literal 6 (or 3), sleep(), instant visual checks after actions | FM-3 |
| Separate press + release anywhere | FM-4 → prompt D-2 |
| Magic numbers, coordinates, button_N, absolute paths in code | FM-5 |
| threading / asyncio / timers appeared | FM-6 |
| Extra features, logging frameworks, fallbacks nobody asked for | FM-7 |
| Names *almost* match the spec | FM-8 |
| Detector never fires | RB-1 (→ prompt C-4). Suspect the latency gate FIRST |
| Steers at where things *were* | RB-2 |
| Character won't stop moving | RB-3 (power-cycle the Arduino before blaming logic) |
| Stuck detection lying | RB-5 |
| Loop FPS tanked | RB-6 (full-frame work in the hot path until proven otherwise) |
| Replay passes, live fails | RB-7 |

## The five commandments (recite before accepting any diff)

1. **Latency:** logic reads `capture.latency_frames`; no verdicts within the pre-effect window; no literal 6, ever, outside `hardware.yaml`.
2. **Imports:** FEATURE_SPECS §0 is the whole menu. Missing capability = framework gap, not a local workaround.
3. **Firmware:** single-packet self-releasing duration commands only. Indices live in `buttons.yaml` and nowhere else.
4. **No threads.** Cadence, not concurrency. The one exception requires a new ADR (ADR-004).
5. **Config:** YAML; coordinates only in `rois.yaml`; every tunable is a named config value.

## Recurring rituals

- **New season (~12 weeks):** prompt C-6 → `capture_icons.py` → `sNN/overrides.yaml` → flip `active_season` → tuner verification. Never touch base configs or Python.
- **New command / detector / YAML loop:** prompts C-1 / C-2 / C-3. If Copilot says the schema can't express it — believe it, and treat it as a design question, not a special case.
- **Milestone:** tag `bot_framework`, record both hashes in BUILD_PLAN, refresh CLAUDE.md.
- **Late-night misbehavior:** one more run with recording on, save the dataset, stop. Diagnose offline tomorrow (Part 3, last row).

## Doc maintenance (the docs only work if they stay true)

- Code and docs disagreeing = a bug, always. Fix the code, or amend the doc with a new dated ADR in ARCHITECTURE §12. Never leave both standing.
- Spec drift found mid-build gets corrected in FEATURE_SPECS.md (BUILD_PLAN Definition of Done #3), so every future prompt inherits the correction.
- Questions you'd have asked your old collaborator go in `QUESTIONS.md` at the repo root. The next capable LLM you sit down with starts by reading the six docs plus that file — the documents are the collaborator of record.
