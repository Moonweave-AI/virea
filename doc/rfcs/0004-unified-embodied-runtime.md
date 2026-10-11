<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md)
<!-- END DOC NAV -->

# Unified capability and embodiment runtime

The two architecture proposals supplied for this change establish the design direction: Motion Lab, Character Studio and VRChat Studio share capability interfaces, Motion IR and performance orchestration. The user requested implementation on the existing feature branch on 2026-10-11.

## Domain and invariants

- An interaction expresses intent. A response plan contains words, motion intentions and timing constraints. It does not authorize device operations.
- A native artifact records source representation and model identity. Motion IR v2 carries actors and auxiliary tracks. Canonical211 v3 is the existing humanoid compatibility format.
- A performance contains independent speech and motion tracks. Actual PCM sample counts determine speech duration. A single playback clock drives each execution target.
- A session owns one current epoch. A superseding input cancels preparation and invalidates late output. Only its active target owns the body channel; interruption retains the last acknowledged pose.
- An execution command binds session, turn, epoch, target, payload digest, expiry and expected revision. Repeated dispatch is idempotent. A device acknowledgement and an observed rendered result are separate evidence.

## Implementation boundaries

`packages/contracts` owns portable, versioned messages. `src/virea/ports` defines language, audio, motion, adapter and embodiment interfaces. `src/virea/application` owns compilation, scheduling, session state and dispatch. Providers, browser playback and VRChat supply adapters. Existing numerical implementations stay in `src/virea/motion` and are reached through `virea_retarget`.

Motion Lab's existing job service uses native adapters, Motion IR, retargeting and verification without language or speech. At the baseline, Character Studio and VRChat shared CharacterManager while preparation lived inside UnifiedCharacterSession. This change extracts that preparation and its sample-based audio scheduler, keeps legacy HTTP routes and Python imports, and exposes unambiguous TimedPerformancePlan and IntentPlan names alongside the compatibility aliases.

## Failure handling and resource policy

Cancel child synthesis tasks and release worker histories in `finally`. Preserve native window geometry and model-specific decoding. Validate artifacts before publication. Reject stale epochs, conflicting idempotency keys and invalid receipts. Keep GPU admission, installation jobs, leases and checkpoint verification in the existing control plane. Do not restart logged-in clients or play audio during validation.

## Verification and rollout

Risk is S2 / QA-L3: shared orchestration and avatar output. GitNexus reports critical reach for timeline contracts and the shared motion conversion boundary; the older index also contains ambiguous function records. Review source callers and rebuild the graph. Cover contract round trips, epoch cancellation, speech dependency ordering, command replay, source/target separation and exact native rotation preservation. Run the existing character, VRChat, model-runtime, retarget and browser suites, then real local generation with silent artifact inspection.

Existing deployments retain their routes, model environments and saved connections. Deploy the API/web build after regression checks. Roll back by restoring the preceding commit and rebuilding the web bundle; no model or user-data migration is required. Owner: VIREA maintainers.

## Skeletal follow-up

The shared motion implementation now separates immutable native data, explicit source/target rest-frame binding and declared playback conditioning. One `RigGeometry` FK kernel serves offline conversion and VRChat targets. The compiler never changes a seed to hide a retarget failure. Hand poses use per-frame inputs without automatic mean addition. Source geometry provenance and numerical comparisons are recorded in the [skeletal research log](../research/skeletal-retargeting-2026-10-11.md); [execution quality](../quality/vrchat-motion.md) describes device mounts, support and completion semantics.

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: rfc
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Implementation design for a shared capability and performance core across three workspaces.
canonical: doc/rfcs/0004-unified-embodied-runtime.md
related: []
supersedes: []
superseded_by: []
-->
