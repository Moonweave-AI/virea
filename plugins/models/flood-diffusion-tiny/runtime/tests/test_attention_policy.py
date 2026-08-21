import sys
from types import SimpleNamespace

from virea_flood.flood_backend import FloodBackend, _hide_classic_flash_attention


def test_sdpa_policy_temporarily_masks_flash_imports():
    marker = object()
    previous = sys.modules.get("flash_attn", marker)
    with _hide_classic_flash_attention(True):
        assert "flash_attn" in sys.modules
        assert sys.modules["flash_attn"] is None
    if previous is marker:
        assert "flash_attn" not in sys.modules
    else:
        assert sys.modules["flash_attn"] is previous


def test_cpu_policy_forces_sdpa_and_float32_without_cuda_probe():
    settings = SimpleNamespace(
        attention_backend="flash",
        execution_device="cpu",
    )
    backend = FloodBackend(settings)
    fake_torch = SimpleNamespace(float32="float32", bfloat16="bfloat16")
    query = SimpleNamespace(device=SimpleNamespace(type="cpu"))

    assert backend._resolved_attention_backend() == "sdpa"
    assert backend._attention_compute_dtype(fake_torch, query, "bfloat16") == "float32"


def test_cpu_execution_normalizes_all_materialized_components_to_float32():
    class Component:
        def __init__(self):
            self.calls = []

        def to(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return self

    class Pipeline(Component):
        def float(self):
            self.float_called = True
            return self

    fake_torch = SimpleNamespace(
        float32="float32",
        device=lambda name: f"device:{name}",
    )
    pipeline = Pipeline()
    pipeline.float_called = False
    pipeline.ldf_model = Component()
    pipeline.ldf_model.param_dtype = "bfloat16"
    pipeline.ldf_model.text_encoder = SimpleNamespace(
        model=Component(),
        dtype="bfloat16",
        device="device:cpu",
    )
    pipeline.vae = Component()

    FloodBackend._configure_cpu_execution(pipeline, torch_module=fake_torch)

    assert pipeline.float_called is True
    assert pipeline.ldf_model.param_dtype == "float32"
    assert pipeline.ldf_model.text_encoder.dtype == "float32"
    assert pipeline.ldf_model.calls[-1][1] == {
        "device": "device:cpu",
        "dtype": "float32",
    }
    assert pipeline.vae.calls[-1][1] == {
        "device": "device:cpu",
        "dtype": "float32",
    }
    assert pipeline.ldf_model.text_encoder.model.calls[-1][1] == {
        "device": "device:cpu",
        "dtype": "float32",
    }
