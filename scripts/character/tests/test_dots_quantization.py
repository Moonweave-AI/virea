"""Run with the speech runtime's Python; GPU test uses small synthetic layers."""

import sys
import unittest
from pathlib import Path

try:
    import torch
    from bitsandbytes.nn import Linear4bit
except ImportError as exc:
    raise unittest.SkipTest("Requires the isolated dots.tts runtime") from exc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dots_runtime import quantize_language_layers  # noqa: E402


class Language(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = torch.nn.Embedding(16, 64)
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(64, 64), torch.nn.Linear(64, 64, bias=False)
        )
        self.head = torch.nn.Linear(64, 16, bias=False)
        self.head.weight = self.embedding.weight

    def get_output_embeddings(self):
        return self.head


@unittest.skipUnless(torch.cuda.is_available(), "Requires CUDA")
class QuantizationTest(unittest.TestCase):
    def test_nf4_preserves_tied_head_and_runs_cuda_after_runtime_dtype_cast(self):
        torch.manual_seed(4)
        llm = Language().to(dtype=torch.bfloat16)
        inputs = torch.randn(1, 4, 64, dtype=torch.bfloat16, device="cuda")
        original = Language().to(device="cuda", dtype=torch.bfloat16)
        original.load_state_dict(llm.state_dict())
        with torch.no_grad():
            expected = original.layers(inputs)
        self.assertEqual(quantize_language_layers(llm, torch.bfloat16), 2)
        # This is the official runtime's conversion order, including the extra cast.
        llm.to(dtype=torch.bfloat16).to("cuda").eval()
        self.assertIs(llm.head.weight, llm.embedding.weight)
        self.assertNotIsInstance(llm.head, Linear4bit)
        self.assertIsInstance(llm.layers[0], Linear4bit)
        self.assertEqual(llm.layers[0].weight.dtype, torch.uint8)
        self.assertEqual(llm.layers[0].weight.quant_state.quant_type, "nf4")
        with torch.no_grad():
            actual = llm.layers(inputs)
        self.assertTrue(torch.isfinite(actual).all())
        self.assertLess(
            (
                (actual - expected).float().square().mean()
                / expected.float().square().mean()
            ).item(),
            0.04,
        )


if __name__ == "__main__":
    unittest.main()
