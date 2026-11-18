# Direct input on continuous scrcpy video

## Decision and acceptance status

Selected architecture: an independent P1 input layer over the **unmodified scrcpy 5.0.1 server's video-only stream**. The desktop SDL client is not forked or intercepted. P1 owns displayed-frame coordinate mapping, serialized Appium input, intent-before-dispatch journaling and explicit postconditions. No scrcpy control or audio socket is opened. The separate stock scrcpy observation window remains read-only; the new integrated canvas is the intended recording surface.

A version-pinned SDL fork would reuse mature rendering/input transforms, but would also require maintaining native build dependencies, upstream event-loop changes, double-dispatch prevention and a new acknowledgement bridge. The independent layer reuses P1's existing route contract and makes input ownership explicit, at the cost of maintaining a small, deliberately pinned video protocol decoder. Upstream explicitly provides no protocol compatibility guarantee across versions. Verify the official server hash and reject other versions rather than guessing.

References: [scrcpy developer protocol](https://github.com/Genymobile/scrcpy/blob/v5.0.1/doc/develop.md), [packet implementation](https://github.com/Genymobile/scrcpy/blob/v5.0.1/server/src/main/java/com/genymobile/scrcpy/device/Streamer.java). The source's session-packet layout was checked directly rather than relying on the documentation's older example version.

## Licensing and packaging

scrcpy is [Apache-2.0](https://github.com/Genymobile/scrcpy/blob/v5.0.1/LICENSE). This repository does not redistribute or modify its server/client binaries. Users obtain the official distribution; its upstream license/notices must accompany any future redistribution. Optional PyPI dependencies are PyAV 19.0.2 (BSD-3-Clause) and Pillow 13.0.0 (MIT-CMU). PyAV wheels contain FFmpeg libraries with additional component licenses; a packaged product must inventory and preserve those notices and review its chosen FFmpeg build. These package identifiers are not a claim that the entire binary dependency tree has one license. No native fork or bundled binary distribution is introduced by this POC.

## Input contract

- Decode H.264 into RAM; no audio, video file or device-name metadata collection. Own one random socket/ADB forward and temporary server path, and remove only those owned resources.
- Keep video alive before target launch, outside the target, and after input disconnection. Only a verified selected target can receive input; observation is broader than input permission.
- Preserve aspect ratio and account for letterboxing. Do not infer coordinates from the outer window. Require full video dimensions to match the input adapter's display geometry; no crop/downscale/secondary-display transform is silently accepted.
- Session metadata changes invalidate pending gestures. Recheck generation, frame age, device geometry and foreground before dispatch. Old or disconnected imagery must not be presented as an input-ready frozen surface.
- A transport acknowledgement is insufficient: mark a step successful only after its explicit app postcondition is observed. Preserve partial/uncertain results and never retry uncertain input automatically.
- Maintain current route limits, password rejection, selected-package/build guards and explicit visibility confirmation for coordinate fallback. No financial login/transaction or protected-capture bypass testing.

## Iteration log

1. Initial implementation added video packet/session parsing, pinned server identity, integrated display and freshness/geometry guards. Automated suite: 86 passing tests. A real-device smoke decoded 1080 x 2340 frames.
2. Longer GUI observation exposed an idle-video `TimeoutError` after initial reception. This is a failed integration result, not a completed recording test. The target device was awake/unlocked. Diagnosis compares the optional encoder FPS limit with upstream defaults; click recording/replay acceptance remains pending until continuous reception is stable. Any resulting design change and retest result must be recorded here before claiming success.
3. Removing the FPS limit alone did not resolve the failure. A 30-second initial receive budget produced a successful 20-second smoke, but longer static GUI observation again exceeded the frame-age cutoff. Idle packet absence is now distinguished from EOF: partial packet bytes survive idle timeouts, while the UI labels the age of the last video frame. No stale frame alone authorizes input. Each click/gesture is compared with a fresh, target-guarded Appium screenshot before dispatch; a local 16-pixel-block RGB error above 12 rejects it, and dimension/generation/foreground checks still apply. This is a conservative compression-tolerant correspondence heuristic, not pixel identity or proof of causality; tiny changes below its threshold and the final check-to-input race remain limitations. Tests cover changed local content, dimension mismatch and partial reads across idle timeout. Actual GUI acceptance of this revision is pending.

Physical rotation, desktop resize, capture protection, stream interruption and three reset-before-replay runs are separate acceptance cases. Until measured, they remain unverified; parser/mapping unit tests alone are not device acceptance.
