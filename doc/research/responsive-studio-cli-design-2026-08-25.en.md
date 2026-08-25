---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-08-25
updated: 2026-08-26
last_reviewed: 2026-08-26
review_cycle_days: 30
summary: Primary-source research behind responsive job submission, durable live progress, interactive WebGL viewers, and semantic CLI/Web presentation.
canonical: doc/research/responsive-studio-cli-design-2026-08-25.en.md
related:
  - responsive-studio-cli-design-2026-08-25.zh-CN.md
  - ../engineering-briefs/responsive-studio-and-unified-catalog-2026-08-25.en.md
  - ../getting-started/browser-playback.en.md
  - ../model-catalog/first-wave-2026-08-20.en.md
supersedes: []
superseded_by: []
---

# Responsive Studio and CLI design research log

> [English](responsive-studio-cli-design-2026-08-25.en.md) · [中文](responsive-studio-cli-design-2026-08-25.zh-CN.md)

## Question and evidence boundary

Which interaction and implementation patterns make a local, long-running model pipeline feel immediate without inventing
progress, duplicating work, hiding unsupported models, or destabilizing WebGL? Sources were limited to official standards,
documentation, and upstream repositories for technical claims. Product interfaces informed information hierarchy only;
VIREA does not copy their brands, assets, or layouts.

## Pinned primary sources

| Source | Relevant fact | VIREA consequence |
|---|---|---|
| [RFC 9110: 202 Accepted](https://www.rfc-editor.org/rfc/rfc9110.html#name-202-accepted) | A server may accept work before processing is complete. | Persist and return a Job identity before hardware detection, byte verification, or Worker startup. |
| [web.dev Interaction to Next Paint](https://web.dev/articles/inp) | Interaction feedback is measured at the next presentation; 200 ms or less is the recommended good boundary. | Paint `validating` synchronously and yield one frame before the first slow request. |
| [W3C Long Tasks](https://www.w3.org/TR/longtasks-1/) | Main-thread tasks at or above 50 ms are observable long tasks. | Do not repeatedly parse results or rebuild the complete application tree during progress. |
| [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/) and [MDN WebSocket](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket) | A persistent bidirectional connection can deliver ordered application messages. | Use the existing per-Job event stream; poll only as a bounded disconnect fallback. |
| [Three.js OrbitControls](https://threejs.org/docs/pages/OrbitControls.html) | Orbit, dolly, and pan are provided by an addon control whose `update()` is required with damping. | Both source and VRM viewers expose mouse/touch camera control and reset. |
| [Three.js cleanup](https://threejs.org/manual/en/cleanup.html) and [WebGLRenderer.dispose](https://threejs.org/docs/pages/WebGLRenderer.html) | GPU resources require explicit disposal. | Stop inactive RAF loops and dispose controls, clips, geometry, materials, render lists, and renderer ownership. |
| [three-vrm VRMUtils](https://pixiv.github.io/three-vrm/docs/classes/three-vrm.VRMUtils.html) | `deepDispose` releases VRM object resources. | Superseded Avatar loads and final teardown must release the old scene graph. |
| [Rich Live](https://github.com/Textualize/rich/blob/master/rich/live.py) | Live display refreshes one bounded renderable region and handles terminal transience. | Use semantic, bounded TTY updates; retain throttled plain output for redirection and logs. |
| [Open Design](https://github.com/nexu-io/open-design) and its [Apache-2.0 license](https://github.com/nexu-io/open-design/blob/main/LICENSE) | It treats design-system rules as a reusable semantic skill layer. | Adopt original VIREA tokens and component contracts, not copied pixels or branded assets. |
| [OpenAI Codex](https://github.com/openai/codex), [OpenCode TUI](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/tui.mdx), and [SkillHub](https://github.com/iflytek/skillhub) | Current developer tools prioritize a no-argument entry, compact persistent context, discoverable choices, and separate human/machine output. | Keep `uv run virea`, show restored selections and deployment state, and preserve stable plain/JSON automation paths. |
| [ARIA progressbar](https://www.w3.org/TR/wai-aria-1.2/#progressbar) and [WCAG use of color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) | Progress needs an accessible name/value; color cannot be the only state signal. | Every state has text plus a symbol; unknown totals remain indeterminate. |

## Repository observations

Before this change, the Generate handler awaited execution discovery and a synchronous server submit before rendering.
The server then performed repeated live machine detection and SHA-256 scans. A separate 750 ms Job poll and the global
revision stream both refreshed Job state; every revision also reloaded all model manifests and rebuilt the complete DOM,
detaching both canvases. Each viewer scheduled RAF while inactive, lacked camera controls, and the source viewer overwrote
camera position every frame.

At the 2026-08-25 observation snapshot, the catalog had 14 non-test manifests. Six contained a VIREA Runtime and
production-acceptance contract; eight only stated that the upstream project was runnable. A truthful interface therefore
had to expose every record while disabling an operation whose Worker, Runtime, task-input contract, artifact installation,
adapter, and target acceptance did not exist. This snapshot was superseded on 2026-08-26: all 14 now have those integration
contracts and are `integrated_experimental`, while current real-checkpoint acceptance remains separate evidence.

## Decisions and rejected alternatives

The accepted model is immediate local state, a durable idempotent Job, per-Job live events, revision-keyed collection
refresh, and a stable viewer island. Bootstrap snapshots are followed by a post-render revision barrier; an unknown or
stale data root blocks submission. Root changes force reconciliation of every root-scoped collection. Authority epochs
ensure that a late state failure or collection completion cannot supersede a newer observation, and a fresh state read
immediately before POST catches a service restart during target discovery. An ambiguous attempt retains a canonical
SHA-256 request fingerprint, so a recovered state/list can find the original Job without storing prompt or path plaintext.
Full byte integrity remains a cancellation-aware,
single-flight Worker admission gate, but is removed from the HTTP critical path and presentation-only catalog reads.
Lifecycle boundaries yield deterministic progress; no ETA or inferred model percentage is shown.

Rejected alternatives include faster polling, disabling request timeouts without idempotency, treating cached metadata as
full verification, exposing the eight records that were upstream-only on 2026-08-25 as VIREA-runnable before integration,
and adding OrbitControls while continuing to overwrite the camera each frame. Their 2026-08-26 integration changes the
capability fact, but does not turn target-acceptance contracts into real-checkpoint evidence. The rejected approaches
preserve duplicate work or misrepresent system truth.

## Validation criteria and limits

Automated tests cover immediate busy feedback, stable idempotency, unavailable and A-to-B/C data-root authority races,
late state responses, an ambiguous durable submit whose response cannot be parsed, fast submission under a deliberately
slow verifier, cancellable and single-flight verification, zero model-catalog reloads for Job-only revisions, live-stream
fallback behavior, catalog parity, camera-control ownership, inactive-loop stopping, and bounded cleanup. Web
typechecking/build, Python contract tests, documentation checks, and the repository suite are release gates.

The local automated environment cannot prove every GPU driver, browser, model checkpoint, or operating-system build.
Real production acceptance remains per model, Runtime, execution domain, and machine evidence. The change removes known
blocking architecture and fails closed; it does not turn unobserved combinations into a universal support claim.
