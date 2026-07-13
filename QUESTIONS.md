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

## Doc updates pending
8. FEATURE_SPECS §0 documents FrameProcessor.process(frame, history) —
   the real signature is process(frame, services) where services is a
   dict containing capture, output, history, loop, plus custom keys.
   Discovered via test_loop.py services-injection commit. Update
   FEATURE_SPECS §0 and F-NAV-1 before or during Phase 4a doc pass.
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