"""Run directly in the installed GPU runtime; also collected by pytest."""

import unittest
from types import SimpleNamespace

import numpy as np
import torch
from virea_sentiavatar.infill import interpolate_batched


class AmbiguousInfill(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.zeros(()))
        self.config = SimpleNamespace(
            num_tokens_per_frame=4, codebook_size=8, vocab_size=33
        )
        self.seen = []

    def forward(self, tokens, audio_features):
        self.seen.append(tokens.clone())
        logits = torch.zeros(
            *tokens.shape, self.config.vocab_size, device=tokens.device
        )
        # Incorrect levels and MASK are more likely than legitimate predictions.
        logits[..., 32] = 100
        for position in range(tokens.shape[1]):
            level = position % 4
            logits[:, position, ((level + 1) % 4) * 8 + 7] = 90
            logits[:, position, level * 8 + 3] = 80
        return logits


class InfillContractTest(unittest.TestCase):
    def test_disjoint_codebooks_never_emit_another_level_or_mask(self):
        for device in ["cpu", *(["cuda"] if torch.cuda.is_available() else [])]:
            with self.subTest(device=device):
                model = AmbiguousInfill().to(device)
                keys = [[0, 1, 2, 3], [4, 5, 6, 7], [7, 6, 5, 4]]
                dense = interpolate_batched(model, keys, np.zeros((9, 768)))
                self.assertEqual(dense[::4], keys)
                self.assertEqual(len(dense), 9)
                self.assertTrue(
                    all(row == [3] * 4 for i, row in enumerate(dense) if i % 4)
                )
                self.assertEqual(len(model.seen), 6)
                self.assertEqual(
                    [int((x == 32).sum()) for x in model.seen], [24, 20, 16, 12, 8, 4]
                )


if __name__ == "__main__":
    unittest.main()
