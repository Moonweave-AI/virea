# Third-party notices

This runtime does not vendor MoMADiff source or model weights. The model pool installs pinned upstream artifacts outside the source checkout.

## MoMADiff

- Official repository: https://github.com/zzysteve/MoMADiff
- Pinned commit: `6dd9bea254bbca6cf19756ac3ee037cbf4f6021c`
- Upstream project license: MIT, copyright 2025 Zongye Zhang
- Official checkpoints: https://huggingface.co/SteveZh/momadiff_models
- Pinned checkpoint revision: `daf83c1441fbb9e8bacd377e28f557b54080c2a1`

The official repository's `NOTICE` attributes MoMask, MotionGPT, text-to-motion, MDM, and Guided-Diffusion. That notice and the terms of each upstream component remain controlling. The official model card at the pinned Hugging Face revision declares the checkpoint repository as MIT; HumanML3D/AMASS dataset-lineage terms remain separate and are not relicensed by that model-card declaration.

## OpenAI CLIP

- Official repository: https://github.com/openai/CLIP
- Runtime source dependency commit: `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6`
- Official ViT-B/32 checkpoint: `ViT-B-32.pt`
- License: MIT for the repository; the official repository's model and usage notices remain controlling.

## Dataset lineage

The released checkpoint was trained through the HumanML3D/AMASS lineage. Inference does not download either training dataset or an SMPL body model. This does not grant rights to redistribute the original datasets or erase their separate terms.
