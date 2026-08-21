# Third-party notices

This runtime wrapper does not vendor ACMDM or model weights. Installation obtains
the following immutable upstream artifacts directly from their publishers:

- `neu-vi/ACMDM@25ed4ba22fb54d9c3e99361609ee344e7c940303` — MIT.
- `cr8br0ze/ACMDM_Flow_S_PatchSize22@f7b77ecb16968afb0329a4a706978780843a1fc9`
  — Hugging Face model-card metadata `license: mit`.
- `cr8br0ze/AE_2D_Causal@78bbd7fc5ec129a6c74812d542892939261a984f`
  — Hugging Face model-card metadata `license: mit`.
- `openai/CLIP@d05afc436d78f1c48dc0dbf8e5980a9d471f35f6` and its official
  ViT-B/32 checkpoint — MIT.
- PyTorch, torchvision, timm, torchdiffeq, NumPy, FastAPI, Uvicorn, Pydantic,
  ftfy, regex, and tqdm under their respective upstream licenses.

The released weights have HumanML3D/AMASS training-data lineage. Deployers remain
responsible for satisfying the terms of the underlying datasets applicable to
their use case.
