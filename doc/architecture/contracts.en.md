<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](contracts.zh-CN.md)
<!-- END DOC NAV -->

# Capability and execution contracts

[中文](contracts.zh-CN.md) · [Overview](overview.en.md)

Portable Pydantic contracts live in `virea_contracts.performance`. They import no model runtime or numerical array library. Large native arrays, playback windows and audio are stored as artifacts. Messages carry references and SHA-256 digests.

| Contract | Meaning |
|---|---|
| `InteractionRequestV1` | Workflow, user input and optional existing session / direct motion job |
| `ResponsePlanV1` | Speech intentions, atomic motion stages, tool intentions and timing |
| `MotionRequestV1` | Selected model, timed conditions and optional native history |
| `NativeMotionArtifactV1` | Native samples, source profile, model revision and time axis |
| `AudioArtifactV1` | Measured sample rate and sample count; duration is their ratio |
| `ExecutablePerformanceV1` | Validated motion artifact, mixed audio and speech intervals |
| `ExecutionCommandV1` | Session, turn, epoch, target, revision, expiry and idempotency key |
| `ExecutionReceiptV1` | Completion state and explicit evidence level |
| `SessionSnapshotV1` | Current epoch, state, body owner and most recent receipt |

Source and target profiles are separate. Native rotation observations and imputed position-derived twist are recorded independently. An observed-rendered or semantically-satisfied receipt requires evidence references. Device acknowledgement remains its own level.

## HTTP entry points

`GET /api/v1/workflows` lists the three workspaces. `POST /api/v1/interactions` routes an `InteractionRequestV1`. Motion Lab receives an ordinary `motion_job` and requires no character session. Character Studio and VRChat Studio require their existing session ID. Target IDs are checked when supplied. The response returns the request ID, workflow and ordinary job/session result.

```json
{
  "schema_version": "virea.interaction_request.v1",
  "request_id": "first-motion",
  "workflow": "motion_lab",
  "text": "A person waves with one hand.",
  "motion_job": {
    "model_id": "motioncraft-smplx",
    "task": "text_to_motion",
    "input": {"prompt": "A person waves with one hand.", "duration_seconds": 4, "seed": 42}
  }
}
```

Use the selected model's manifest input and parameter schema when constructing `motion_job`; the example shows the request envelope. The existing `/jobs`, `/characters`, `/vrchat` and onboarding APIs remain available. `/docs` provides the server's live OpenAPI reference.

`LanguagePort`, `AudioPort`, `MotionPort`, `MotionAdapterPort` and `EmbodimentPort` define Python integration seams. Providers retain their native streaming and window APIs behind these boundaries. `ToolDispatcher` validates an explicitly registered capability's argument schema, authorization and side effects before invoking it.

The timed `PerformancePlan` compatibility import resolves to `virea_contracts.timeline`; new code can use `TimedPerformancePlan`. The semantic planner exports `IntentPlan`. No consumer needs to infer the plan's meaning from an identical class name in another module.

The nine messages have versioned JSON Schemas in `packages/contracts/schemas/v1/`. Regenerate them with `python -m virea_contracts.schema_export`; add `--check` to verify schema drift. The current conversation planner emits speech and motion. Additional tool capabilities are registered through `ToolDispatcher`.

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
summary: Unified runtime contracts.
canonical: doc/architecture/contracts.en.md
related: []
supersedes: []
superseded_by: []
-->
