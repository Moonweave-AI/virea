from __future__ import annotations

import sys

import torch
from virea_motioncraft.portable_moe import install_portable_tutel


def test_portable_tutel_preserves_checkpoint_parameter_layout() -> None:
    install_portable_tutel(torch)
    layer = sys.modules["tutel.moe"].moe_layer(
        gate_type={"type": "cosine_top", "k": 2, "fp32_gate": True},
        experts={
            "type": "ffn",
            "count_per_node": 4,
            "hidden_size_per_expert": 16,
            "activation_fn": torch.nn.functional.gelu,
        },
        model_dim=8,
        normalize_gate=True,
    )

    keys = set(layer.state_dict())

    assert "gates.0.temperature" in keys
    assert "gates.0.cosine_projector.weight" in keys
    assert "gates.0.sim_matrix" in keys
    assert "experts.batched_fc1_w" in keys
    assert "experts.batched_fc2_w" in keys
    assert "_num_global_experts" in keys
    output = layer(torch.randn(7, 8))
    assert output.shape == (7, 8)
    assert torch.isfinite(output).all()
