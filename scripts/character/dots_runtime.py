"""Load dots.tts with optional NF4 language layers before moving to CUDA."""

from pathlib import Path


def quantize_language_layers(llm, dtype):
    import torch
    from bitsandbytes.nn import Linear4bit, Params4bit

    # Keep the tied embedding/output head and every acoustic module untouched.
    output = llm.get_output_embeddings()
    count = 0
    for parent in list(llm.modules()):
        for name, layer in list(parent.named_children()):
            if not isinstance(layer, torch.nn.Linear) or layer is output:
                continue
            quantized = Linear4bit(
                layer.in_features,
                layer.out_features,
                bias=layer.bias is not None,
                compute_dtype=dtype,
                compress_statistics=True,
                quant_type="nf4",
            )
            quantized.weight = Params4bit(
                layer.weight.detach().to(device="cpu", dtype=dtype),
                requires_grad=False,
                compress_statistics=True,
                quant_type="nf4",
                module=quantized,
            )
            if layer.bias is not None:
                quantized.bias = torch.nn.Parameter(
                    layer.bias.detach().to(device="cpu", dtype=dtype),
                    requires_grad=False,
                )
            setattr(parent, name, quantized)
            count += 1
    if not count:
        raise RuntimeError("No dots.tts language layers found for NF4 quantization")
    return count


def load_runtime(model, *, revision, precision, optimize, quantization, gpu_memory_gib):
    import torch
    from dots_tts.models.dots_tts.model import DotsTtsModel
    from dots_tts.runtime import DotsTtsRuntime
    from huggingface_hub import snapshot_download

    if quantization not in {"none", "nf4"}:
        raise ValueError("quantization must be none or nf4")
    if quantization == "nf4" and (
        not torch.cuda.is_available() or precision != "bfloat16" or optimize
    ):
        raise ValueError("NF4 requires CUDA + bfloat16, with torch.compile disabled")
    if gpu_memory_gib <= 0:
        raise ValueError("GPU memory budget must be positive")
    if torch.cuda.is_available():
        total = torch.cuda.get_device_properties(0).total_memory
        torch.cuda.set_per_process_memory_fraction(
            min(1.0, gpu_memory_gib * 2**30 / total)
        )
        torch.cuda.reset_peak_memory_stats()
    path = Path(model).expanduser()
    if not path.is_dir():
        path = Path(snapshot_download(model, revision=revision))
    loaded = DotsTtsModel.from_pretrained(path)
    dtype = torch.bfloat16 if precision == "bfloat16" else torch.float32
    loaded.core.to(dtype=dtype)
    unquantized_bytes = sum(p.numel() * p.element_size() for p in loaded.parameters())
    layers = (
        quantize_language_layers(loaded.core.llm, dtype) if quantization == "nf4" else 0
    )
    # Prompt features live on the inference device. Bound their retention as well
    # as request concurrency so importing many voices cannot grow VRAM forever.
    loaded._PROMPT_FEATURE_CACHE_MAX_ENTRIES = 4
    runtime = DotsTtsRuntime(loaded, path, precision=precision, optimize=optimize)
    runtime.virea_quantization = quantization
    runtime.virea_quantized_layers = layers
    runtime.virea_gpu_memory_gib = gpu_memory_gib
    runtime.virea_unquantized_weights_mib = round(unquantized_bytes / 2**20, 1)
    return runtime


def runtime_metrics(runtime):
    result = dict(
        quantization=getattr(runtime, "virea_quantization", "none"),
        quantized_layers=getattr(runtime, "virea_quantized_layers", 0),
    )
    if str(runtime.device).startswith("cuda"):
        import torch

        free, total = torch.cuda.mem_get_info()
        result["cuda_memory"] = dict(
            allocated_mib=round(torch.cuda.memory_allocated() / 2**20, 1),
            reserved_mib=round(torch.cuda.memory_reserved() / 2**20, 1),
            peak_allocated_mib=round(torch.cuda.max_memory_allocated() / 2**20, 1),
            device_free_mib=round(free / 2**20, 1),
            device_total_mib=round(total / 2**20, 1),
            allocator_limit_gib=getattr(runtime, "virea_gpu_memory_gib", None),
            unquantized_weights_mib=getattr(
                runtime, "virea_unquantized_weights_mib", None
            ),
        )
    return result
