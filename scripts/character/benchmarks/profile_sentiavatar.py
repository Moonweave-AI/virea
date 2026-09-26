"""Profile one resident SentiAvatar backend in its installed GPU runtime.

Diagnostic only: bypasses worker admission, transport and retargeting. Run on an
idle GPU, with VIREA_ARTIFACT_ROOTS_JSON and VIREA_MEMORY_STRATEGY=cuda_full.
Never use its timings as end-to-end character latency.
"""

from __future__ import annotations

import argparse
import json
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--action", default="动作：点头微笑。你好，很高兴见到你。")
    parser.add_argument("--steps", type=int, nargs="+", default=[6, 6, 6, 4, 2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    import numpy as np
    import torch
    from virea_sentiavatar.backend import SentiAvatarBackend

    report = {
        "schema": "virea.sentiavatar_resident_profile.v1",
        "scope": "backend only; no transport, retarget, export or playback",
        "audio": str(args.audio.resolve()),
        "action": args.action,
        "import_seconds": time.perf_counter() - started,
        "torch": torch.__version__,
        "runs": [],
    }
    backend = SentiAvatarBackend()

    def save() -> None:
        (args.output / "profile.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        started = time.perf_counter()
        backend.load()
        torch.cuda.synchronize()
        report.update(
            load_seconds=time.perf_counter() - started,
            device=backend.device_facts,
            gpu=torch.cuda.get_device_name(),
        )
        for index, steps in enumerate(args.steps):
            row = {"index": index, "generate_steps": steps, "stages": {}}

            def timed(name, operation):
                def run(*values, **kwargs):
                    torch.cuda.synchronize()
                    before = time.perf_counter()
                    value = operation(*values, **kwargs)
                    torch.cuda.synchronize()
                    row["stages"][name] = time.perf_counter() - before
                    if name == "planner_generate":
                        row["planner_new_tokens"] = (
                            value.shape[1] - kwargs["input_ids"].shape[1]
                        )
                    return value

                return run

            torch.cuda.reset_peak_memory_stats()
            with ExitStack() as stack:
                for name in (
                    "_audio_features",
                    "_audio_tokens",
                    "_decode_body",
                    "_face",
                ):
                    stack.enter_context(
                        patch.object(backend, name, timed(name, getattr(backend, name)))
                    )
                stack.enter_context(
                    patch.object(
                        backend._planner,
                        "generate",
                        timed("planner_generate", backend._planner.generate),
                    )
                )
                stack.enter_context(
                    patch.object(
                        backend._pipeline,
                        "interpolate_sequence",
                        timed("infill", backend._pipeline.interpolate_sequence),
                    )
                )
                before = time.perf_counter()
                result = backend.generate(
                    [str(args.audio.resolve())],
                    [args.action],
                    seed=42,
                    temperature=0.2,
                    top_p=0.2,
                    generate_steps=steps,
                    max_new_tokens=1024,
                    generate_face=True,
                )
                torch.cuda.synchronize()
                row["seconds"] = time.perf_counter() - before
            row.update(
                output_seconds=len(result.body153_normalized) / 20,
                peak_allocated_mib=torch.cuda.max_memory_allocated() / 1024**2,
                peak_reserved_mib=torch.cuda.max_memory_reserved() / 1024**2,
            )
            row["rtf"] = row["seconds"] / row["output_seconds"]
            np.savez_compressed(
                args.output / f"run-{index}.npz",
                body=result.body153_normalized,
                mean=result.body_mean153,
                std=result.body_std153,
                face=result.face_arkit51,
            )
            report["runs"].append(row)
            save()
            print(json.dumps(row), flush=True)
    finally:
        save()
        backend.unload()


if __name__ == "__main__":
    main()
