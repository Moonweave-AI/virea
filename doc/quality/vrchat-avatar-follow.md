<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md)
<!-- END DOC NAV -->

# Avatar-independent tracking — 2026-10-11

The generated VR route follows the verified AI client's current avatar. Body,
wrist and finger tracking no longer require a VIREA controller, a particular
Avatar ID or the nine custom `AI_*` parameters. The target must still have a
VRChat Humanoid rig compatible with full-body IK. This is model-derived
tracking input; it is not an interface for assigning every rendered bone.

## Regression coverage

`tests/vrchat/test_avatar_independent.py` covers standard avatars without custom
parameters, subsequent avatar changes, local SDK identities, explicit fixed
binding, stale/unverified feedback, removal of stale tracking values, fresh
calibration after a switch, and playback interruption before/during warmup.
The standard-avatar playback test receives all eight body targets and OpenVR
pose output with zero custom avatar-parameter messages. Calibration regressions
cover cold capture restart, establishing a coherent body pose before searching
for the menu, OSC-only menu input and release on cancellation.

The web tests cover a ready standard avatar without optional expression
parameters, calibration progress taking priority over cached tracking mode,
and failed calibration remaining distinct from missing avatar binding.

| Local check | Result |
|---|---|
| Python 3.12: `python -m pytest tests/vrchat -q` | 361 passed, 1 skipped |
| Python 3.10: `python -m pytest tests/vrchat/test_avatar_independent.py -q` | 16 passed |
| Web: `pnpm --filter @virea/web test` | 182 passed |
| Web: `pnpm --filter @virea/web build` | TypeScript and Vite passed |
| `ruff check` and `ruff format --check` on VRChat source/tests | Passed |
| `python scripts/check_docs.py` / `generate_docs.py --check` | Passed; 225 Markdown files / 2 generated outputs |

## Live verification

The updated API and built frontend were deployed locally while preserving both
logged-in VRChat clients and their shared instance. A complete stationary
calibration reached 8/8 with fresh `TrackingType=6` and a natural standing pose.
The observer then showed the existing supplied Humanoid perform a newly
generated MotionCraft sequence: wave, extend both arms, and return the arms.
The real chatbox displayed the generated speech text.

| Observation | Result |
|---|---|
| Generated performance | 16.0 seconds; seed 20261011 |
| MotionCraft revision | `a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9` |
| Playback | Completed; 479 motion updates |
| Virtual driver | 491 packets sent, 490 acknowledged; device masks 7 / 6 |
| Preset emotes / dropped captions | None / 0 |
| Sound | Audio output disabled; all five active render endpoints muted |

Before the final deployment, an idle tracking interruption blocked playback,
and native menu input failed to reopen calibration. A direct OSC menu command
worked in the same client. Automatic calibration now uses that single input
source, releases it on cancellation, and tolerates capture restart within its
overall deadline. The final calibration-to-generation-to-playback run completed
without an error; this does not guarantee that game feedback never drops.

Two other cached avatar IDs were rejected by VRChat as inaccessible. Those
requests are **not** successful cross-avatar tests. Multiple identities and
avatars without custom parameters are covered by automated tests; live
playback on a second accessible avatar remains unverified. The existing four
README videos predate this change and do not establish universal avatar
compatibility, exact joint reproduction or perfect finger retargeting.

## Operation and rollback

Keep **自动跟随 AI 账号当前角色** enabled. Changing avatars stops old playback
and discards its held pose; the new avatar must finish calibration before a new
performance can play. Failures remain visible and block playback. Fixed binding
is still available by disabling follow mode and specifying an Avatar ID;
legacy configurations that supplied only an explicit ID retain that behavior.
See the [configuration example](../../integrations/vrchat/generated-vr.example.json)
and [operating guide](../character/vrchat-operations.en.md).

The existing GitNexus index reports high fan-out for shared readiness/rendering
code and contains stale/misresolved associations. Rebuilding it failed locally.
Graph analysis was therefore supplemented with direct caller inspection and
regression tests; its counts are not treated as proof of complete coverage.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: reference
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Avatar-independent tracking contract, regression coverage and bounded live verification.
canonical: doc/quality/vrchat-avatar-follow.md
related: [../character/vrchat.en.md, ../character/vrchat.zh-CN.md, vrchat-recordings.md]
supersedes: []
superseded_by: []
-->
