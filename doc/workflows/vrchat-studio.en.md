---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Use the vrchat-studio workspace.
canonical: doc/workflows/vrchat-studio.en.md
related: []
supersedes: []
superseded_by: []
---

# VRChat Studio

[中文](vrchat-studio.zh-CN.md) · [Windows setup and client controls](../character/vrchat-operations.en.md)

The AI controls its own VRChat account. An observer account watches the result from another client in the same room.

1. Complete model verification in setup, then open `/app/vrchat.html` on Windows.
2. Use the client launch buttons for the observer and AI. Keep their profiles and OSC ports separate. The AI uses virtual VR; physical VR hardware is optional.
3. Log in to the respective accounts, connect the bridge and select the AI avatar.
4. Run automatic calibration. Watch its local progress bar and step count, then join both accounts to the same instance.
5. Open the side panel: the upper view belongs to the observer, the lower view to the AI. Align the observer so the AI's full body and subtitles are visible.
6. Submit an interaction. The same performance compiler prepares speech and motion; OpenVR/OSC transmits the generated pose to the AI client. Check the execution receipt alongside the actual observer view.
7. Keep audio disabled for silent demonstrations. User and AI messages are relayed as subtitles. Record the two views after confirming the requested movement.

Avatar proportions are calibrated independently of the motion model. Generated local rotations pass through the shared retarget pipeline before target-specific tracking and IK.

Each request retains one native sample. Constant rest-frame bindings connect source and target skeletons; MotionCraft playback uses an explicitly recorded SO(3) temporal filter. Hands use per-frame parameters without automatic mean-pose addition. Elbow and knee trackers follow the upper arms and thighs, and floor support adjusts the complete tracking rig. See [motion execution quality](../quality/vrchat-motion.md) for equations and same-sample comparisons.

[Operation and keyboard mapping](../character/vrchat-operations.en.md) · [Native pose transport](../character/vrchat.en.md) · [Real recording evidence](../quality/vrchat-recordings.md)
