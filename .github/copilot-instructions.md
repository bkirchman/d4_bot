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
   Narrow exemption: framework-level I/O infrastructure that does not
   participate in the tick decision path may use a worker thread. The current
   and only allowed case is FrameRecorder in bot_framework
   (framework/contrib/recording/recorder.py); this rule governs both repos even
   though it is written in d4_bot. This remains an absolute prohibition for
   processors, detectors, and anything that reads or writes GameState. The
   exemption is safe because the recorder observes the tick, never influences
   it, and drops work under load rather than blocking the tick.
   Under load, the recorder drops rather than blocks.

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
