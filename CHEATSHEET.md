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

## Working agreement

Claude operates as the developer; the operator is the technical manager. Claude
does the implementation thinking and drives the Copilot work. The operator makes
design and tactical calls and unblocks. Claude raises: decisions between real
alternatives, anything that changes agreed behaviour or contradicts a doc, and
genuine blockers. Claude does not narrate mechanism, tooling, or environment
work — it handles those and reports the outcome, or the cost if it is material.
State conclusions and their consequences, not the derivation.

Prompt blocks are labelled uniquely (e.g. `P4a.1-B2`, `ENV-B1`) and re-issues
take a letter suffix rather than a new number. Substantive code blocks verify
before committing; text-only blocks may commit as they go.

### Change tiers

Use the lightest tier that matches the risk of the requested change.

**TRIVIAL** — a literal value, name, string, or index. No new behaviour and no
new decision. One block, one commit per file, verification is the existing test
that covers the value plus the full suite. No ADR. Spec edit only if a spec
names the literal. Example: changing which button a command sends.

**MODERATE** — new config keys, a new diagnostic script, or a corrective fix to
code already reviewed in this phase. One block, per-file commits, verification
scoped to the identifiers that changed plus the full suite. Spec edit where a
spec is now wrong. No ADR unless a documented decision changed; a dated
amendment note under the existing ADR is preferred over a new ADR for small
corrections.

**MAJOR** — new behaviour, a new module, anything touching the live processor
path, or anything a future session could get wrong by guessing. Full treatment:
new ADR, spec amendments, per-identifier verification, stop-before-commit,
explicit go before commit.

Rules that apply at every tier:
- Verify by identifier, never by file. Per-file success reports have twice
	concealed partial execution in this project — a block writing 3 of 7 required
	doc entries, and a test file covering 4 of 14 required cases.
- ADRs are immutable once accepted. Amend by appending a new ADR or a dated
	note; never edit an accepted ADR's text. Absence-of-phrase verification
	searches must be scoped to live spec files only, never to ARCHITECTURE.md.

Environment gate:
`C:\Users\brian\source\repos\d4_bot\.venv\Scripts\python -c "import pytest, numpy, cv2; import sys; print(sys.prefix != sys.base_prefix)"`
must print `True`. Checking `sys.prefix != sys.base_prefix` alone is not
enough — an empty venv passes it, which happened in this project and produced a
test run that appeared verified but was not. `bot_framework` has no venv of its
own by design; its tests run from d4_bot's venv. Creating a venv inside
`bot_framework` yields an environment missing every dependency.

## The build loop (repeat until milestone)

1. Open BUILD_PLAN.md → next unfinished phase. Read its FEATURE_SPECS sections yourself first (10 min — this is the review that matters most).
2. Fresh Copilot agent session → paste the phase's Section B prompt verbatim, fill slots (paste protocol.md sections where the prompt says so).
3. Check the agent's *opening reply*: files list + imports list. Wrong → correct **before** any code exists.
4. Let it work. Don't micro-review; the verify script is the reviewer.
5. Run `scripts/verify_phase_N.py`. Fail → route through TROUBLESHOOTING Part 1; two failed corrections → kill the thread, restart at step 2.
6. Pass → record the `bot_framework` commit hash in the phase header, commit (both repos separately if the framework changed), film your notes, next phase.

## Working with Copilot output

**Verbosity default: minimal.** For any implementation task, Copilot's
response should include only (a) files read, (b) ambiguities
encountered and how resolved, and (c) a file-by-file summary of what
will change in one or two sentences per file. Do NOT paste proposed
diffs unless the prompt explicitly requests them. Do NOT include full
file contents in the response. After approval, apply the changes and
report only `git log -1 --stat` — not the diff.

**Escalation triggers (request full diff review).** Prompts should
explicitly ask for full diff review when:
- The change touches core framework interfaces
	(framework/interfaces.py, framework/loop.py, framework/temporal.py).
- The change is a full Phase implementation (B-4a, B-4b, etc.).
- The ADR being implemented is architectural rather than tactical.
- The change modifies more than three files.

**De-escalation triggers (skip diff review by default).**
- Bug fix within a single file.
- Docs-only edits.
- Config-file edits.
- Adding logging or diagnostic output.

**How prompts should signal review level.** For high-scrutiny tasks,
include the line "Show me the proposed diff before I approve." in the
prompt. For low-scrutiny tasks, no signal needed — the default is
approve-and-apply.

Commit gate: single commit, message "Add Copilot output verbosity
policy to CHEATSHEET". Docs-only, no code changes.

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
- **Commit every deliverable:** commit at every deliverable, not just at end of phase. A phase is a sequence of committed deliverables; reverting should never cost more than one deliverable. (Learned via the Phase 3 revert loss.)
- **Audit-prompt pattern:** when multiple verification checks are pending, batch them into one Copilot prompt that runs all checks and saves the outputs/artifacts to disk for offline review, instead of running checks serially in conversation.

## Doc maintenance (the docs only work if they stay true)

- Code and docs disagreeing = a bug, always. Fix the code, or amend the doc with a new dated ADR in ARCHITECTURE §12. Never leave both standing.
- Spec drift found mid-build gets corrected in FEATURE_SPECS.md (BUILD_PLAN Definition of Done #3), so every future prompt inherits the correction.
- Questions you'd have asked your old collaborator go in `QUESTIONS.md` at the repo root. The next capable LLM you sit down with starts by reading the six docs plus that file — the documents are the collaborator of record.
- Canonical doc set: ARCHITECTURE.md, FEATURE_SPECS.md, BUILD_PLAN.md, ROADMAP.md, COPILOT_PROMPTS.md, TROUBLESHOOTING.md, CHEATSHEET.md, and QUESTIONS.md. ROADMAP.md is the eighth doc: milestone-level roadmap across framework and game bots; feeds BUILD_PLAN.
