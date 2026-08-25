from __future__ import annotations

import math
import sys
import types
from dataclasses import dataclass
from typing import Any, Callable


def install_portable_tutel(torch: Any) -> None:
    """Install the single-process Tutel surface used by MotionCraft.

    The released checkpoints store the cosine gate and fused FFN parameters under
    Tutel's public state-dict names. This implementation deliberately preserves
    those names and performs the same top-k gated expert FFNs with ordinary Torch
    operations on CPU, CUDA, and MPS-capable hosts.
    """

    existing = sys.modules.get("tutel")
    if existing is not None and getattr(existing, "__virea_portable__", False):
        return

    nn = torch.nn
    functional = torch.nn.functional

    class CosineTopKGate(nn.Module):
        def __init__(
            self,
            model_dim: int,
            num_global_experts: int,
            k: int = 1,
            fp32_gate: bool = False,
            proj_dim: int = 256,
            init_t: float = 0.5,
            **options: Any,
        ) -> None:
            super().__init__()
            unknown = set(options) - {"capacity_factor", "gate_noise"}
            if unknown:
                raise TypeError(
                    f"unsupported portable Tutel gate options: {sorted(unknown)}"
                )
            self.top_k = min(num_global_experts, int(k))
            self.fp32_gate = bool(fp32_gate)
            self.gate_noise = float(options.get("gate_noise", 0.0))
            self.capacity_factor = float(options.get("capacity_factor", 1.0))
            self.temperature = nn.Parameter(
                torch.log(torch.full((1,), 1.0 / init_t)), requires_grad=True
            )
            self.cosine_projector = nn.Linear(model_dim, proj_dim)
            self.sim_matrix = nn.Parameter(torch.randn(proj_dim, num_global_experts))
            self.clamp_max = math.log(1.0 / 0.01)
            nn.init.normal_(self.sim_matrix, 0.0, 0.01)

        def forward(self, values: Any) -> Any:
            projected = (
                self.cosine_projector.float()
                if self.fp32_gate
                else self.cosine_projector
            )
            similarities = (
                self.sim_matrix.float() if self.fp32_gate else self.sim_matrix
            )
            inputs = values.float() if self.fp32_gate else values
            logits = torch.matmul(
                functional.normalize(projected(inputs), dim=1),
                functional.normalize(similarities, dim=0),
            )
            scale = torch.clamp(self.temperature, max=self.clamp_max).exp()
            return logits * scale

    class FusedExpertsNetwork(nn.Module):
        def __init__(
            self,
            model_dim: int,
            hidden_size_per_expert: int,
            num_experts_per_device: int,
            *,
            activation_fn: Callable[[Any], Any] | None,
            output_dim: int | None = None,
        ) -> None:
            super().__init__()
            self.model_dim = int(model_dim)
            self.hidden_size = int(hidden_size_per_expert)
            self.output_dim = int(output_dim or model_dim)
            self.activation_fn = activation_fn or functional.relu
            count = int(num_experts_per_device)
            self.batched_fc1_w = nn.Parameter(
                torch.empty(count, self.hidden_size, self.model_dim)
            )
            self.batched_fc2_w = nn.Parameter(
                torch.empty(count, self.hidden_size, self.output_dim)
            )
            self.batched_fc1_bias = nn.Parameter(torch.empty(count, self.hidden_size))
            self.batched_fc2_bias = nn.Parameter(torch.empty(count, self.output_dim))
            self.reset_parameters()

        def reset_parameters(self) -> None:
            with torch.no_grad():
                for expert in range(self.batched_fc1_w.shape[0]):
                    first = nn.Linear(self.model_dim, self.hidden_size)
                    second = nn.Linear(self.hidden_size, self.output_dim)
                    self.batched_fc1_w[expert].copy_(first.weight)
                    self.batched_fc1_bias[expert].copy_(first.bias)
                    self.batched_fc2_w[expert].copy_(second.weight.T)
                    self.batched_fc2_bias[expert].copy_(second.bias)

        def expert(self, expert: int, values: Any) -> Any:
            hidden = torch.matmul(values, self.batched_fc1_w[expert].T)
            hidden = hidden + self.batched_fc1_bias[expert]
            hidden = self.activation_fn(hidden)
            output = torch.matmul(hidden, self.batched_fc2_w[expert])
            return output + self.batched_fc2_bias[expert]

    class MOELayer(nn.Module):
        def __init__(
            self,
            gate_type: dict[str, Any],
            model_dim: int,
            experts: dict[str, Any],
            **options: Any,
        ) -> None:
            super().__init__()
            if gate_type.get("type") != "cosine_top":
                raise TypeError("MotionCraft portable Tutel supports cosine_top only")
            expert_options = dict(experts)
            if expert_options.pop("type", None) != "ffn":
                raise TypeError("MotionCraft portable Tutel supports ffn experts only")
            count = int(
                expert_options.pop(
                    "count_per_node",
                    expert_options.pop("num_experts_per_device", 1),
                )
            )
            hidden = int(expert_options.pop("hidden_size_per_expert"))
            activation = expert_options.pop("activation_fn", None)
            output_dim = expert_options.pop("output_dim", None)
            if expert_options:
                raise TypeError(
                    f"unsupported portable Tutel expert options: {sorted(expert_options)}"
                )
            self.register_buffer("_num_global_experts", torch.tensor(count))
            self.gates = nn.ModuleList(
                [
                    CosineTopKGate(
                        model_dim,
                        count,
                        **{k: v for k, v in gate_type.items() if k != "type"},
                    )
                ]
            )
            self.experts = FusedExpertsNetwork(
                model_dim,
                hidden,
                count,
                activation_fn=activation,
                output_dim=output_dim,
            )
            self.normalize_gate = bool(options.get("normalize_gate", True))
            self.l_aux: Any = None

        def _load_from_state_dict(
            self,
            state_dict: dict[str, Any],
            prefix: str,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            key = prefix + "_num_global_experts"
            if key not in state_dict:
                state_dict[key] = self._num_global_experts
            for name, parameter in self.experts.named_parameters():
                state_key = prefix + "experts." + name
                value = state_dict.get(state_key)
                if value is not None and value.numel() == parameter.numel():
                    state_dict[state_key] = value.reshape(parameter.shape)
            return super()._load_from_state_dict(state_dict, prefix, *args, **kwargs)

        def forward(self, inputs: Any, **_: Any) -> Any:
            original_shape = tuple(inputs.shape)
            values = inputs.reshape(-1, original_shape[-1])
            gate = self.gates[0]
            logits = gate(values)
            probabilities = functional.softmax(logits, dim=1)
            weights, expert_ids = probabilities.topk(gate.top_k, dim=1)
            if self.normalize_gate:
                weights = weights / weights.sum(dim=1, keepdim=True).clamp_min(1e-9)
            output = torch.zeros(
                values.shape[0],
                self.experts.output_dim,
                dtype=values.dtype,
                device=values.device,
            )
            for expert in range(int(self._num_global_experts)):
                token_index, rank_index = torch.where(expert_ids == expert)
                if token_index.numel() == 0:
                    continue
                selected = values.index_select(0, token_index)
                computed = self.experts.expert(expert, selected).to(output.dtype)
                computed = computed * weights[token_index, rank_index].to(
                    output.dtype
                ).unsqueeze(1)
                output.index_add_(0, token_index, computed)
            self.l_aux = output.new_zeros(())
            output.l_aux = self.l_aux
            return output.reshape(*original_shape[:-1], self.experts.output_dim)

    moe_module = types.ModuleType("tutel.moe")
    moe_module.moe_layer = MOELayer
    net_module = types.ModuleType("tutel.net")

    @dataclass(frozen=True)
    class _Groups:
        data_group: None = None

    net_module.create_groups_from_world = lambda **_: _Groups()
    tutel_module = types.ModuleType("tutel")
    tutel_module.__virea_portable__ = True
    tutel_module.moe = moe_module
    tutel_module.net = net_module
    sys.modules["tutel"] = tutel_module
    sys.modules["tutel.moe"] = moe_module
    sys.modules["tutel.net"] = net_module
