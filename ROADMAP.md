# ROADMAP.md — cross-project milestone roadmap

**Status:** Living document. Eighth canonical doc (see ADR entry recording its creation).
**Scope:** Milestone-level planning across `bot_framework`, `d4_bot`, and future game bots (`halo_bot`). Lives in d4_bot for doc-set cohesion despite cross-repo scope — a deliberate tradeoff, recorded in the ADR.
**Relationship to BUILD_PLAN.md:** This doc governs *which milestones exist and in what order*. BUILD_PLAN.md governs *execution detail of active d4_bot phases*. Within an active phase, BUILD_PLAN.md wins. ARCHITECTURE.md rule zero is unchanged.
**Rule:** When a milestone here activates, it gets a planning pass that produces BUILD_PLAN.md phases (or the game-repo equivalent) before any implementation prompt is written.

---

## 1. Where we are

Phase 4a (steering navigation) is complete: commit a627341,
2026-07-18, including ADR-014's overlapping-burst emission. Phase
4a.1 is partially complete — the minimap-pin detector shipped
(6e4def0, 4620c75) but ADR-015's compound-signal arrival amendment
that consumes it was never implemented, leaving arrival on the
single-signal path. Phase 4b (stuck detection and recovery ladder)
has not started and holds the navigation milestone gate.

Order of remaining Phase 4 work: 4a.1 part 2, then 4b.

M1 planning may proceed in parallel — COMBAT_MILESTONE.md scopes M1
as standalone-testable without navigation running — but no milestone
below is considered started until Phase 4b closes per BUILD_PLAN.md.

Known snag for Phase 4b: F-NAV-3's stuck definition and the B-4b
prompt both key on "movement burst active or just completed," an
anchor that no longer exists under ADR-014's continuous emission. A
replacement anchor must be specified before B-4b is run.

---

## 2. Parity inventory — previous-generation (game_bot) features

Source of record: game_bot files present in project knowledge (`core/system_initializer.py`, `config/icon_sets/hud_icons.json`, `config/icon_sets/map_icons.json` references) plus the d4_bot doc set's existing heritage notes. game_bot remains feature-intent reference only; code is never ported (ARCHITECTURE §1.1).

### P-1 — Command interface / operator launcher
- **What game_bot had:** SequenceRegistry loading `commands.json` + `basic_commands.json`; operator selected and ran static commands (navigation, scanning, fighting) through a command interface.
- **Already absorbed:** press/release pairs → firmware v2.1 duration packets (the click is the packet); multi-step sequences → YAML content loops (FEATURE_SPECS F-CFG-3 heritage note).
- **Remaining gap:** the operator-facing surface. Current answer is one entry script per activity (`run_nav.py` pattern).
- **Parity scope (Proposed — pending ruling): THIN.** A single launcher script: list available activities, select one, run it, show live status, abort cleanly. Not a rebuilt console, no interactive command palette. Per-activity scripts remain the substrate; the launcher only fronts them.

### P-2 — Combat: scanning and fighting
- **What game_bot had:** PowerHUDDetector (HUD template detection of powers/cooldowns), AttackManager (loadout-specific power→button maps), EnemyTargeted / A_Confirm icon detection, operator-triggered scan and fight commands.
- **Current status:** already the deferred Phase 5 combat foundation (BUILD_PLAN Phase 5+; FEATURE_SPECS §8): enemy detection → `GameState.enemy_present` → AttackProcessor on `enemy_appeared` edges; loadout YAML per season.
- **Parity scope (Proposed — pending ruling): FULL** — this is the already-planned Phase 5, now explicitly tagged as the parity vehicle for game_bot's scan/fight features.
- **Resolved (see OD-1):** scanning = facing sweep. Enemy presence is detected via the game's own targeting UI — the enemy health bar appears on screen when the character's facing cone acquires a target. Detection is therefore template/ROI work on a stable HUD element (legacy EnemyTargeted icon is reference data), not visual monster detection; the operator's original judgment that no CV approach beats this signal is adopted as the M1 strategy.
- **Reusable data:** EnemyTargeted, A_Confirm, power/HUD icon templates; power-mapping and loadout button-map structures as YAML redesign inputs.

### P-3 — Inventory: slot-state reading and grid navigation
- **What game_bot had:** detection of inventory slot states (empty / GA / favorite / junk / selected) via icon templates; cursor navigation of the inventory grid.
- **Current status:** NOT covered anywhere in the existing Phase 5+ deferred list. This roadmap adds it.
- **Parity scope (Proposed — pending ruling): READ-FIRST.** Milestone delivers: (a) slot-state detection across the grid via template detectors, (b) a grid model tracking cursor position, (c) cursor navigation to a chosen slot via d-pad hops with visual position confirmation. Item *actions* (junk-marking, salvaging, moving items) are explicitly out of scope for the parity milestone and become future features (§4).
- **Framework-boundary note:** "navigate a cursor through a menu grid using discrete inputs, confirming position visually" is a game-agnostic mechanism candidate for `bot_framework/contrib/` — grid dimensions, hop commands, and slot icons stay d4_bot data. Ruling deferred to the milestone's planning pass (Open Decisions OD-3).
- **Reusable data:** EmptySlot, GaSlot, FavSlot, JunkSlot, InventorySelected, CharacterInterface icon templates from `hud_icons.json`.

### P-4 — Map interaction: two-stage cursor navigation
- **What game_bot had:** timed cursor-movement scripts to bring the map cursor near a region/town, then CV icon detection (MapIconPlanner + `map_icons.json`) for fine targeting and movement to the detected icon.
- **Current status:** partially adjacent to deferred items "minimap position tracking" and "town/menuing scripted loops," but the two-stage coarse-then-fine cursor pattern is specified nowhere. This roadmap makes it a first-class milestone.
- **Parity scope (Proposed — pending ruling): FULL** — the two-stage pattern, ending with a pin placed (or waypoint selected) at a detected icon.
- **Why it matters beyond parity:** map interaction is the missing dependency for the recovery ladder's deferred re-pin fallback (FEATURE_SPECS F-NAV-3 rung-4 note) and the substrate for town/menuing loops.
- **Reopened question:** map-cursor work is exactly what the axis-calibration CSVs existed for; F-CTL-2 excluded them as map-cursor-only. The milestone's planning pass must rule on calibration approach (Open Decisions OD-4).
- **Reusable data:** `map_icons.json` icon set; Pin and Map HUD icons.

---

## 3. Milestone sequencing (post-Phase 4)

Default order, dependency-driven:

| # | Milestone | Depends on | Repo(s) touched |
|---|---|---|---|
| M1 | Combat foundation (P-2) | Phase 4 complete | d4_bot; possibly contrib detectors |
| M2 | Processor + YAML-loop composition (ADR-006 gap) | M1 useful but not strictly required | bot_framework |
| M3 | Map interaction (P-4) | M2 (composition makes map flows expressible) | d4_bot; calibration ruling may touch framework |
| M4 | Inventory read-first (P-3) | none hard; benefits from M2 | d4_bot; possible contrib grid-nav mechanism |
| M5 | Operator launcher (P-1) | ≥2 activities existing to launch | d4_bot |
| M6 | Fishing absorption (diablo_bot → d4_bot YAML activity; archive diablo_bot) | M2 | d4_bot |
| M7 | Halo migration (per HALO_MIGRATION.md: parity-first, inference-only, frozen models) | stable framework post-M2; framework tag | bot_framework + new halo_bot |

**Sequencing pressure note (unresolved, OD-2):** M4 (inventory) is the most self-contained and demo-able milestone and can jump the queue for video-content cadence without breaking dependencies. The table above is the dependency-clean default; content cadence may reorder M3/M4/M5.

**M1 architecture note (from OD-1 resolution):** scan is a state inside the combat layer — sweep is continuous stick rotation via ADR-014's burst emitter with programmatically advancing direction, bounded to one revolution, with latency overshoot absorbed by targeting-cone width. Scan contends with navigation for the left stick, reinforcing M2 (processor composition) as a hard dependency for "pause steering, sweep, resume" flows. M1 pre-planning is banked in COMBAT_MILESTONE.md (scope ruling, state machine, gated-rotation architecture, survival scope, acceptance sketch).

Self-restarting run wrapper and minimap position tracking remain deferred exactly as BUILD_PLAN Phase 5+ lists them; they attach to whichever milestone first demands them.

---

## 4. Future features beyond parity

The first future-feature target is defined below. Other parked candidates (route-planned farming via minimap position tracking, multi-activity session orchestration, self-restarting wrapper as standing infrastructure, inventory item actions beyond FF-1's needs) await their own planning sessions.

### FF-1 — Autonomous whisper farming (near-term North Star)

The payoff activity every parity milestone builds toward: the bot farms Tree of Whispers objectives unattended. Architecture is a three-layer churn firewall, designed around the observation that whispers are a rotating cast of instances drawn from a small stable set of behavioral archetypes:

- **Archetype executors (code, d4_bot):** one executor per behavioral pattern, composed from parity capabilities — map-pin the objective (P-4), navigate (Phase 4), fight (M1), detect completion. Change only when the game invents a new mechanic.
- **Objective definitions (YAML, season overlays):** each known whisper maps to an archetype + parameters (completion signal, templates, timeouts) inside the existing configs/seasons structure (F-CFG-5). Seasonal churn lands here as data edits captured via F-DIAG-4, never as code.
- **Selection layer:** reads which whispers are active and chooses only those whose archetype the bot can execute, skipping the rest. This is the honest-scoping mechanism: v1 skips interiors; each later archetype executor widens the farmable set without touching existing layers.

**Ratified archetype taxonomy (non-seasonal content; per operator ground-truthing):** area-kill (kill until meter fills), go-interact (travel to point, interact), kill-target (specific named spawn), interior-instance (requires entering dungeon/cellar — out of scope for v1 executors, in scope for selection-layer recognition). Seasonal whispers that fit no archetype are skipped by the selection layer by design.

**Completion detection:** per-archetype signals read from stable HUD affordances (whisper progress display, cache-ready state — legacy WhisperCacheEnabled icon is reference data). Template/ROI work, seasonal-overlay friendly.

**Dependencies:** M1 (combat), M2 (composition), M3 (map interaction) at minimum; mount handling (legacy Horse* icons are reference data) is a strong accelerator and gets scoped in FF-1's planning pass. FF-1 activates only via a full planning pass producing BUILD_PLAN phases.

### FF-2 — Minimap threat awareness

Omnidirectional enemy awareness by reading the minimap's red enemy dots and boss/elite icons, converting a blind 360-degree sweep into a directed turn toward a known bearing. An optimization over a working sweep, never a dependency for one.

- Prior art: attempted in game_bot and never made accurate. Recorded as an honest failure, not an untried idea.
- Split by tractability. Boss and elite icons have distinct shapes and are template-matchable — ADR-015's precedent that shape beats color on the minimap applies directly. Generic red dots are a few pixels with no shape and fail exactly where map terrain is heavily red; they would need background subtraction against the static map, motion differencing, or reads restricted to low-ambient-red regions.
- May therefore ship in halves: icon bearing detection well before generic dot detection, if generic dots ever prove worth it.
- Scope note: extends ADR-009's minimap-as-motion-sensor ruling to threat reading. That scope change is part of this feature, not assumed.

---

## 5. Halo migration placement

HALO_MIGRATION.md remains the banked spec (parity-first, inference-only milestone using frozen gen3 models; synchronous BotLoop replacing the detection thread; FrameHistory replacing the camera-velocity ring buffer). It slots as M7: after the framework has absorbed the composition mechanism (M2) and received a version tag, so Halo consumes a stable substrate. YOLOv5→v8 retraining debt (QUESTIONS.md items 6–7) becomes unavoidable at this milestone if not resolved earlier.

---

## 6. Open decisions

- **OD-1 — Scanning semantics.** RESOLVED — scanning = facing sweep reading the targeting UI's enemy health bar; see §2 P-2 and the M1 architecture note in §3.
- **OD-2 — Ordering pressure.** Dependency cleanliness (table order in §3) vs. video-content cadence (inventory early). Unresolved; revisit when Phase 4 nears completion.
- **OD-3 — Grid-navigation framework promotion.** Does menu-grid cursor navigation enter `bot_framework/contrib/` at M4, or stay in d4_bot until Halo proves the second consumer? Placement test from ARCHITECTURE applies.
- **OD-4 — Map-cursor movement approach.** Revive axis-calibration CSV data (as redesigned YAML), re-measure fresh, or attempt closed-loop cursor steering via icon detection feedback? Decided in M3's planning pass.
- **OD-5 — Parity scope ratification.** P-2 (combat) RESOLVED 2026-08-04: ratified FULL under this item's unchallenged-default rule at M1's planning pass. M1 delivers defensive combat (ADR-018); FF-1 delivers area-clear. P-1, P-3, and P-4 remain pending, each ratifying or being challenged at its own milestone's planning pass.
- **OD-6 — Board composition measurement.** What fraction of a typical whisper board is completable without entering interiors? Two-minute in-game check at the whisper board; determines whether FF-1 v1 (no interior executors) has enough farmable density to demo. Unmeasured.
- **OD-7 — FF-1 selection input.** Does v1's selection layer read the whisper board/map itself (extends P-4 machinery), or does the operator pre-select targets and the bot only executes? Operator-selects is a legitimate thinner first cut. Undecided.

### Standing principle — detections are grow-on-demand

No master catalog of legacy detections is ported. Each milestone's planning pass declares the detections it needs; templates are captured fresh via F-DIAG-4 (seasonal art churn makes speculative templates stale on arrival). One exception is named as shared infrastructure: **screen-mode detection** (which screen is the game showing — world HUD, map, character/inventory) backing `GameState.screen_mode`. It is specified once and attached to whichever multi-screen milestone activates first (M3 or M4 per OD-2). Legacy HUD, Map, CharacterInterface, InventorySelected icons are its reference data.

---

*End of ROADMAP.md. Milestones activate via planning passes that produce BUILD_PLAN.md phases; this doc never contains implementation detail.*
