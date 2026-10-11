<!-- BEGIN DOC NAV -->
[✦ VIREA](../../README.md) · [Documentation](../README.en.md) · [Set Up](../getting-started/automatic-setup.en.md) · [Demos](../demos/README.en.md) · [简体中文](README.zh-CN.md)
<!-- END DOC NAV -->

# 🔌 Model catalog

Connect the capabilities your workflow needs. Motion Lab can generate movement on its own; Character Studio and VRChat Studio combine language, speech and motion.

| Capability | Cloud connections | Local options | First check |
|:--|:--|:--|:--|
| 💬 Language | OpenAI, DeepSeek, Anthropic, Alibaba Bailian, Gemini and compatible providers | Ollama, LM Studio, llama.cpp and VIREA endpoints | Generate a structured reply |
| 🎙️ Speech | OpenAI Speech, Bailian, ElevenLabs, Azure and supported endpoints | Kokoro, Audio8 and local services | Generate a waveform and inspect its duration |
| 🦴 Motion | Motion capability endpoint | MotionCraft, SynTalker, SentiAvatar + ARDY, plus Motion Lab's catalog | Generate motion frames and preview the source skeleton |

## Choose in this order

1. Open **Set Up** and choose a provider or local recipe.
2. Detect the available models and voices. Select from the returned list.
3. For a local model, review the detected device, memory requirements and download plan, then deploy.
4. Run **generation verification**. Inspect the text, waveform or motion that the service actually returns.
5. Activate the connection and open a workspace.

[Step-by-step setup](../getting-started/automatic-setup.en.md) · [Platform choices](../platforms/README.en.md)

## Native motion stays identifiable

| Stage | What it carries |
|:--|:--|
| Native result | The model's original representation, skeleton, units and timing |
| Source adapter | An explicit mapping into Motion IR, including observed and inferred quantities |
| Retargeting | Source and target rest frames, joint hierarchy, FK and target bone motion |
| Execution | A timed performance and target-specific delivery |

The [generated model matrix](support-matrix.generated.md) lists every catalog entry, its native skeleton, runtime and resource profiles. [MotionCraft and SynTalker](../character/unified-motion.en.md) have a dedicated interaction guide; [model integration](../development/model-adapter.zh-CN.md) explains how to add another source.

## Read the matrix correctly

Use the **Runtime** column to choose an environment, **resources** to check memory, and **observations** to find recorded generation runs. The setup page distinguishes an installed environment from a connection that has produced a verified result.

For automation, installation state has two useful views: `full_integrity` checks current artifact bytes; `metadata` provides a faster view of persisted state. Execution checks full integrity before starting a worker. Multi-task models retain acceptance records for each declared task, bound to the installation and artifact identity. See [status semantics](../reference/status-semantics.en.md#acceptance-suites-and-content-binding).

<details>
<summary>⌨️ Command-line model selection</summary>

From the development environment, run these in the repository root:

```sh
# List model identifiers for scripts.
uv run virea model list --json

# Inspect the selected model's requirements and source representation.
uv run virea model info MODEL

# Preview installation in a detected execution domain.
uv run virea model install MODEL --execution-domain DOMAIN --virea-home PATH
```

`MODEL` comes from the model list; `DOMAIN` comes from `doctor --json`; `PATH` is your VIREA data directory. Apply the plan with the options in the [CLI reference](../reference/cli.en.md#model-install-and-model-repair).

</details>

<!-- BEGIN DOC FOOTER -->
---

[📚 Documentation map](../catalog.en.md) · [🛠️ Troubleshooting](../operations/troubleshooting.en.md) · [🤝 Contributing](../../CONTRIBUTING.md)
<!-- END DOC FOOTER -->

<!--
type: index
status: Active
owner: VIREA maintainers
created: 2026-08-23
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 14
summary: English entry point for selecting VIREA model manifests, execution-domain Runtimes, resource profiles, and evidence boundaries.
canonical: doc/models/README.en.md
related:
  - README.zh-CN.md
  - support-matrix.generated.md
  - ../getting-started.en.md
  - ../reference/cli.en.md
  - ../reference/status-semantics.en.md
  - ../model-catalog/first-wave-2026-08-20.en.md
supersedes: []
superseded_by: []
-->
