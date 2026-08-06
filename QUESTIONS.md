# QUESTIONS.md — d4_bot open items and deferred debt

## Environment hygiene (do before or during Phase 4a)
1. pytest missing from any declared dev dep — install manually in every
   venv. Move to bot_framework [dev] extra.
2. opencv-python-headless gets pulled as transitive dep from
   yolov5/ultralytics, breaks cv2.imshow in diagnostic scripts.
   Explicitly pin opencv-python (with GUI) in bot_framework [ml].
3. Copilot agent sessions can silently lose venv context and run system
   Python. Every session start: verify `python -c "import sys; print(sys.prefix != sys.base_prefix)"`
   prints True. Matching on executable path is unreliable — VS Code's own
   install directory is `AppData\Local\Programs\Microsoft VS Code`, which
   produces a false positive against an `AppData\Local\Programs\Python` pattern.
   Fresh Copilot sessions do not inherit an activated venv unless the workspace
   interpreter is set.
4. YoloDetector should print torch build + CUDA availability at startup
   so environment problems fail loud instead of silently degrading.
5. yolov5 and pandas are declared in [ml] extra but as transitive deps
   for legacy YOLOv5 checkpoint loading. Framework contract quietly
   depends on the legacy ecosystem — clean fix is model retraining.

## Deferred technical debt
6. nav_arrow model is legacy YOLOv5, tuned to threshold ~0.50. Shows
   false positives on similar-colored moving objects under the marker.
   Candidate for eventual native YOLOv8 retraining with augmented
   training data (Phase 2.5 if steering quality matters, or defer
   until Halo migration forces the same conversation).
7. In-place YOLOv5→YOLOv8 conversion attempted once and failed
   (head architecture divergence). Retraining is the only clean path.
   Applies to Halo H0 too — gen3's models are v5-era.
- **Map screen occludes both arrival signals.** Opening the in-game map hides
   the minimap and the on-screen nav arrows simultaneously, so
   NavigationProcessor reads it as both-signals-lost and fires `arrived` within
   `arrival_confirm_ticks` (400 ms). There is no screen-mode detection to
   distinguish an occluded HUD from a genuine signal loss. Consequences: (a)
   any human opening the map mid-run false-arrives the bot; (b) Phase 4a.1's
   mid-run-unpin acceptance case cannot be executed as written, since clearing
   a pin requires the map screen. Case deferred, not waived. ADR-020 already
   names screen-mode detection as the one shared-infrastructure exception to
   grow-on-demand detection; this is that dependency surfacing early. Resolve
   when screen-mode detection lands, then restore the unpin acceptance case.
   Related to ADR-021 and OD-2.
- **Arrival vs mid-run-unpin discriminator.** `pin_position` travels from the
   minimap border to the interior as the character approaches; a pin vanishing
   from the border is an unpin, one vanishing near the interior is a true
   arrival. Implementing this would restore an honest `guide_lost` verdict for
   mid-run unpin, which ADR-021 traded away. Requires live measurement of the
   interior-fraction threshold before it can be specified. Related to OD-6.
- ~~**Minimap-pin detection as a disambiguation signal for arrival vs
   detector failure.** The current arrival heuristic ("nav arrow
   vanished + recent movement + sustained lost") cannot distinguish
   real arrival from a nav-arrow detector failure while a pin is
   still active. If we can detect the pin marker on the minimap
   independently:
      - Pin visible + no arrow detected: arrow detector is failing on
         an active waypoint. Do NOT terminate as arrived; extend
         SEARCHING or trigger a diagnostic.
      - No pin visible + no arrow detected: legitimate arrival or
         unpinned. Current terminal-transition logic applies.
      - Pin visible + arrow detected: normal navigation.
      - No pin visible + arrow detected: cross-check indicates false
         positive arrow detection (relevant to nav_arrow YOLOv5
         false-positive shelf, also banked).
   Adds a new detector (minimap-pin) and a cross-check in the
   arrival/searching decision. Belongs to a future phase — probably
   packaged with the nav_arrow model retrain rather than as a
   standalone task, since improved arrow reliability plus pin
   cross-check together produce a substantially better navigation
   signal. Do not implement in Phase 4a or 4b.~~
   **Resolved 2026-07-18:** Landed as Phase 4a.1 via ADR-015.
   Compound-signal design (both nav_arrows and pin_visible must be
   lost for arrival) with backstop timeout on nav_arrow-only if pin
   detector fails.

## Doc updates pending
8. ~~**Core-interface drift is a recurring failure mode.** Two incidents now (this one; the earlier `process` argument name churn). Before any phase whose prompt cites a framework class signature, the standing rule is: have Copilot quote the actual source file back before writing code. Consider adding a lightweight signature-check script that greps FEATURE_SPECS §0 signatures against framework source and fails on mismatch — deferred, but worth a session when it bites a third time.~~
   **Resolved 2026-07-18**: FrameProcessor signature drift was formally captured in ARCHITECTURE ADR-019 and reflected in FEATURE_SPECS §0 and BUILD_PLAN workflow text; Phase 4a work (including ADR-014's overlapping-burst emission) confirmed the quote-the-source discipline as the working practice. Signature-check script remains deferred and is tracked as future hardening, not a blocker for 4a closeout.

Items 8–11 cleared to TROUBLESHOOTING.md / CHEATSHEET.md on 2026-08-03.

## Workflow annoyances
12. PowerShell up-arrow history stopped working in VS Code terminal
    despite ConsoleHost and PSReadLine 2.0.0 loaded. Fresh terminal
    didn't fix. Workaround: Ctrl+R for reverse search. Try: upgrade
    PSReadLine to 2.3+, check profile, try Windows Terminal directly.

## Active debugging
- ~~Black-frame capture issue.~~ **Resolved 2026-08-03:** transient capture-card/driver fault, cleared by restart. Not a code defect. If it recurs, first suspect is the hardcoded MJPG FOURCC negotiation in AVerMediaCapture._open_capture — OpenCV accepts an unsupported format silently and delivers black frames with valid geometry.
- **Nav-arrow model recall is degraded.** The legacy YOLOv5 nav-arrow
   checkpoint requires confidence_threshold 0.25 to fire reliably;
   configs/detectors/nav_arrow.yaml shipped at 0.50 and the detector
   was unreliable there. Operator-confirmed 2026-08-04. This
   quantifies the detector unreliability ADR-015's compound-signal
   arrival was designed to tolerate, and strengthens the case that
   compound-signal arrival is load-bearing rather than defensive — at
   0.25 the arrow stream necessarily includes low-confidence
   detections. Relevant to the YOLOv5-to-v8 retraining debt (items
   6-7): retraining is the real fix, 0.25 is the workaround. Do not
   raise the threshold back without retraining or re-measuring.

- **Minimap-pin detector diverges from the detector config pattern.**
   Every other detector has its own YAML in configs/detectors/,
   discovered by globbing that directory per F-DET-1 and prompt C-2.
   The pin detector is special-cased: build_detectors() reads its
   settings from configs/navigation.yaml under minimap_pin_* keys via
   _load_navigation_config(). Consequences: (a) its template was
   untracked from 6e4def0 until 2026-08-04 because nothing in
   configs/detectors/ referenced it; (b) seasonal overrides reach it
   through the navigation: block rather than the detector-override
   path, a different code path from every other detector; (c)
   minimap_pin_template_path resolves to configs/minimap_pin_template.png,
   outside the seasons/ tree, though minimap iconography is seasonal
   churn per F-CFG-5. Migration to configs/detectors/minimap_pin.yaml
   with a seasonal template path is cheap now and gets expensive once
   season overrides depend on the current shape.

## Dataset labeling (parked for later)
13. If replay verification is ever going to catch regressions, need a
    lightweight labeling scheme — segmented recordings with timestamp
    ranges saved beside the frames, OR a labels.jsonl written by the
    recorder when the operator tags segments with a keypress. Not a
    today problem; a "before we care about regressions" problem.

- **Overlapping-burst emission (ADR-014) has downstream implications for Phase 4b stuck detection.** F-NAV-3's stuck definition currently keys on "movement burst active or just completed" — an anchor that doesn't exist under continuous emission. Proposed replacement anchor is banked in F-NAV-3's impact bullet. Confirm the replacement wording and add unit tests during Phase 4b implementation session, not before.

## Resolved
- ~~**Phase 4a.1 part 2 outstanding (arrival unsafe).** NavigationProcessor does not read pin state; arrival remains single-signal. configs/navigation.yaml has arrival_confirm_ticks: 12, matching neither ADR-015's pre-amendment value (120) nor its target (24), and no backstop key exists. Live navigation runs will false-arrive on nav_arrow dropouts until ADR-015's compound-signal amendment is implemented. Do not run run_nav.py for acceptance until this closes.~~ **Resolved 2026-08-06:** Compound-signal arrival implemented per ADR-015 with the discriminator amendments in ADR-021. arrival_confirm_ticks is 24 and nav_arrow_only_arrival_backstop_ticks is 300. Live acceptance still pending.
- ~~Arrival heuristic under overlap is brittle to prolonged detector
   dropouts.~~ **Resolved 2026-07-18:** Not previously banked; noting
   here for provenance. Under ADR-014's overlapping-burst emission,
   "recent movement" was always true because bursts are continuous,
   which meant arrival hinged entirely on frames_since_guide_lost >=
   arrival_confirm_ticks. A prolonged detector dropout would trigger
   spurious mid-transit arrival. Mitigated in Phase 4a by tuning
   arrival_confirm_ticks up to 120 (2 seconds); eliminated in Phase
   4a.1 via ADR-015's compound-signal arrival, with arrival_confirm_ticks
   tuned back to 24.