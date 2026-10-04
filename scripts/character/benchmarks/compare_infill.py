"""Compare the released serial infill with batched decoding on identical tensors."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from virea_sentiavatar.backend import SentiAvatarBackend, _read_audio
from virea_sentiavatar.infill import interpolate_batched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    backend = SentiAvatarBackend()
    backend.load()
    try:
        features, _ = backend._audio_features(
            _read_audio(str(args.audio), backend.roots)
        )
        audio_tokens = backend._audio_tokens(features)
        backend._generation_seed, backend._planner_url = 42, "http://127.0.0.1:8084"
        prompt, _ = backend._pipeline.construct_llm_prompt(
            "动作：双手张开，开心地解释", audio_tokens
        )
        sparse = backend._planner_tokens(
            prompt, temperature=0.5, top_p=0.7, max_new_tokens=1024
        )
        keys = backend._pipeline.sparse_to_keyframes(sparse)
        outputs, results = {}, []
        for repetition in range(3):
            for name, operation in [
                ("serial", backend._pipeline.interpolate_sequence),
                ("batched", interpolate_batched),
            ]:
                torch.cuda.synchronize()
                started = perf_counter()
                outputs[name] = np.asarray(
                    operation(backend._mask_model, keys, features, generate_steps=6)
                )
                torch.cuda.synchronize()
                results.append(
                    dict(mode=name, repeat=repetition, seconds=perf_counter() - started)
                )
                print(results[-1], flush=True)
        report = dict(
            runs=results,
            keyframes=len(keys),
            audio_frames=len(features),
            exact_token_agreement=float(
                np.mean(outputs["serial"] == outputs["batched"])
            ),
            preserved_keyframes=bool(np.array_equal(outputs["batched"][::4], keys)),
        )
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    finally:
        backend.unload()


if __name__ == "__main__":
    main()
