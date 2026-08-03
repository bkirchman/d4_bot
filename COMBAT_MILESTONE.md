# COMBAT_MILESTONE.md — banked pre-planning for M1

**Status:** Banked strategy document (HALO_MIGRATION.md precedent). Not canonical. When M1 activates, a full planning pass converts this into BUILD_PLAN.md phases and FEATURE_SPECS.md entries; nothing here is implementation-ready.
**Drafted:** during the Fable-model transition documentation pass, with operator rulings inline.

---

## 1. Scope ruling

M1 is **defensive combat**, not area-clear. The CombatProcessor's contract: when the targeting UI acquires an enemy, kill it, sweep for more, report clear. Area-clear ("kill until a meter fills") is FF-1's area-kill executor, which composes defensive combat with a movement pattern — it is not M1.

Consequence: M1 is testable standalone via a combat-only entry script (character parked where enemies spawn, no navigation running). Stick contention between combat and navigation is therefore not an M1 problem; it surfaces in M2, and "nav + combat running together" is M2's natural demo.

## 2. Detection strategy (per OD-1 resolution, ROADMAP §2 P-2)

Enemy presence = the game's own targeting UI: the enemy health bar appearing when the character's facing cone acquires a target. Template/ROI work on a stable HUD element; no visual monster detection, no YOLO. Legacy EnemyTargeted icon is reference data.

**Measurement task for the planning pass (not a decision):** capture live frames with a normal enemy and with an elite/boss targeted; measure health-bar ROI position(s). If elites render a different bar layout, that is two templates/ROIs, not one — resolved by measurement, F-DIAG-4 workflow.

## 3. State machine sketch

IDLE (watch health-bar ROI) → ENGAGE (edge: enemy_appeared; hold the facing that acquired the target) → ATTACKING (execute loadout rotation; kill-verification latency-gated) → health bar gone and persisting past the latency window → SWEEP (facing sweep per ROADMAP §3 M1 architecture note: short stick nudges rotating the targeting cone, each check gated on latency_frames) → target found: re-ENGAGE; sweep completes clear: IDLE with combat_clear flag set for the caller.

Failure rungs (honest-failure pattern, mirroring NavigationProcessor):
- engage_timeout: health bar persists past a configured timeout (unkillable target, obstruction) → terminal status combat_timeout.
- Death: revive-screen detection → terminal status character_dead. No auto-revive in v1.

Mid-fight bar loss that does NOT persist past the latency window is not a kill — re-sweep before concluding (the enemy may have left the facing cone). The latency gate is what makes kill-vs-moved distinguishable.

## 4. Attack rotation and the gate architecture

Loadout = per-build YAML: an ordered sequence of buttons.yaml command names with inter-press delays. No HUD cooldown reading in v1 (legacy PowerHUDDetector intent is NOT carried initially — grow-on-demand applied to detection).

Each sequence entry carries an optional **gate** field:
- `none` (default): press on schedule.
- `resource`: press only when the resource globe ROI reads above a configured threshold.
- `cooldown`: press only when the skill's HUD slot reads ready.

**v1 ships with all gates `none`.** Operator ruling: the bot's build is simple, few commands, not resource-starved — blind timed rotation is expected to suffice. The gate field exists because the "pressing is forgiving" assumption has known failure modes the operator flagged on instinct: resource-starved spenders whiff as a normal state; contextual interact can hijack presses near corpses/shrines/doors/items; movement skills on a rotation reposition the character out of its own targeting cone. If M1 acceptance shows whiffing or press-hijacking, the fix is turning on exactly the gates reality demands — resource-globe reading is the same cheap color/ROI detector family as the health globe (§5), an increment, not a redesign.

Build constraint recorded: the M1 loadout must avoid movement skills in the rotation, and acceptance should be run away from dense interactables, so the `none`-gate assumption gets a fair test.

## 5. Survival scope

In scope for v1 (unattended farming is the stated goal):
- Health-globe detection: color-match on the globe ROI (same detector family as the fishing drop indicator). Below threshold → potion press.
- Potion policy: simple threshold-drink. No potion-count awareness, no flee logic (explicitly out of scope; rabbit hole).
- Death: revive-screen detection → character_dead terminal status.

## 6. Deferred (listed so they aren't relitigated)

- Cooldown/resource HUD reading (pulled in via gates only on evidence)
- Buff maintenance, dodge usage (no legacy AttackManager behavior carried unless the operator flags one)
- Flee/kiting logic
- Elite/boss-specific tactics beyond the two-ROI measurement
- Area-clear behavior (FF-1's area-kill executor)

## 7. Acceptance sketch (to be formalized in the planning pass)

Combat-only entry script; character parked in a spawn-active area with the M1 loadout. Pass = across three consecutive sessions: every spawned normal enemy engaged and killed; sweep finds off-cone enemies; combat_clear reached when the area is genuinely clear; a potion fires when health drops below threshold; an induced unkillable/obstructed scenario exits cleanly with combat_timeout.
