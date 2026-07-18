# QUESTIONS.md — d4_bot open items and deferred debt

## Environment hygiene (do before or during Phase 4a)
1. pytest missing from any declared dev dep — install manually in every
   venv. Move to bot_framework [dev] extra.
2. opencv-python-headless gets pulled as transitive dep from
   yolov5/ultralytics, breaks cv2.imshow in diagnostic scripts.
   Explicitly pin opencv-python (with GUI) in bot_framework [ml].
3. Copilot agent sessions can silently lose venv context and run system
   Python. Every session start: verify `python -c "import sys; print(sys.executable)"`.
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
- **Minimap-pin detection as a disambiguation signal for arrival vs
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
  signal. Do not implement in Phase 4a or 4b.

## Doc updates pending
8. ~~**Core-interface drift is a recurring failure mode.** Two incidents now (this one; the earlier `process` argument name churn). Before any phase whose prompt cites a framework class signature, the standing rule is: have Copilot quote the actual source file back before writing code. Consider adding a lightweight signature-check script that greps FEATURE_SPECS §0 signatures against framework source and fails on mismatch — deferred, but worth a session when it bites a third time.~~
   **Resolved 2026-07-18**: FrameProcessor signature drift was formally captured in ARCHITECTURE ADR-015 and reflected in FEATURE_SPECS §0 and BUILD_PLAN workflow text; Phase 4a work (including ADR-014's overlapping-burst emission) confirmed the quote-the-source discipline as the working practice. Signature-check script remains deferred and is tracked as future hardening, not a blocker for 4a closeout.
9. TROUBLESHOOTING.md should absorb tonight's runtime bugs:
   - RB-8: capture running at half FPS due to another consumer holding
     the DirectShow device open (fixed by killing the other consumer).
   - RB-9: Copilot agent sessions using system Python instead of venv;
     recognize via traceback paths under AppData\Local\Programs\Python.
   - RB-10: opencv-python-headless breaking cv2.imshow, distinct from
     genuine cv2 install failures.
10. Add "always commit at every deliverable, not just at end of phase"
    as a standing habit to CHEATSHEET.md build loop. Learned via the
    Phase 3 revert loss.
11. Add "audit prompt" pattern to CHEATSHEET.md — batch multiple
    verification checks into one Copilot prompt that saves artifacts
    to disk for offline review, instead of doing them serially.

## Workflow annoyances
12. PowerShell up-arrow history stopped working in VS Code terminal
    despite ConsoleHost and PSReadLine 2.0.0 loaded. Fresh terminal
    didn't fix. Workaround: Ctrl+R for reverse search. Try: upgrade
    PSReadLine to 2.3+, check profile, try Windows Terminal directly.

## Dataset labeling (parked for later)
13. If replay verification is ever going to catch regressions, need a
    lightweight labeling scheme — segmented recordings with timestamp
    ranges saved beside the frames, OR a labels.jsonl written by the
    recorder when the operator tags segments with a keypress. Not a
    today problem; a "before we care about regressions" problem.

- **Overlapping-burst emission (ADR-014) has downstream implications for Phase 4b stuck detection.** F-NAV-3's stuck definition currently keys on "movement burst active or just completed" — an anchor that doesn't exist under continuous emission. Proposed replacement anchor is banked in F-NAV-3's impact bullet. Confirm the replacement wording and add unit tests during Phase 4b implementation session, not before.