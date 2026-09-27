"""Batch the official independent five-frame infill windows on the GPU.

Keep the six confidence-ranked decoding iterations and fixed keyframes. No
sampling or precision change is needed to remove per-token host synchronization.
"""

import numpy as np


def interpolate_batched(model, keyframes, features, *, generate_steps=6):
    import torch

    if len(keyframes) < 2:
        return keyframes
    device = next(model.parameters()).device
    levels, size = model.config.num_tokens_per_frame, model.config.codebook_size
    mask_id = model.config.vocab_size - 1
    offsets = torch.arange(levels, device=device) * size
    keys = torch.as_tensor(keyframes, dtype=torch.long, device=device)
    batch = len(keys) - 1
    tokens = torch.full((batch, 5, levels), mask_id, device=device, dtype=torch.long)
    tokens[:, 0], tokens[:, -1] = keys[:-1] + offsets, keys[1:] + offsets
    tokens = tokens.flatten(1)
    indices = np.minimum(
        np.arange(batch)[:, None] * 4 + np.arange(5), len(features) - 1
    )
    audio = torch.as_tensor(features[indices], dtype=torch.float32, device=device)
    per_step = max(1, 3 * levels // generate_steps)
    remaining = 3 * levels
    with torch.inference_mode():
        for step in range(generate_steps):
            scores, predicted = model(tokens, audio_features=audio).max(dim=-1)
            scores = scores.masked_fill(tokens != mask_id, -torch.inf)
            count = (
                remaining if step == generate_steps - 1 else min(per_step, remaining)
            )
            # Stable ties match the source's Python stable sort by confidence.
            positions = scores.argsort(dim=-1, descending=True, stable=True)[:, :count]
            tokens.scatter_(1, positions, predicted.gather(1, positions))
            remaining -= count
            if not remaining:
                break
    frames = tokens.reshape(batch, 5, levels) - offsets
    dense = torch.cat((frames[:, :4].reshape(-1, levels), keys[-1:]), dim=0)
    return dense.cpu().tolist()
