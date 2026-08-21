# Third-party notices

This runtime does not bundle model weights or MARDM source. VIREA installs the
following immutable upstream artifacts into its external model store.

## MARDM

- Code: `neu-vi/MARDM` revision
  `5e32b69723376028f38125ccee33011549cd341d`.
- Code license: MIT, as published in that revision's `LICENSE.txt`.
- SiT-XL: `cr8br0ze/MARDM_SiT_XL` revision
  `6b9a9d6ea5456995e9883bda317e45ef111ecad3`.
- HumanML3D AE: `cr8br0ze/AE_humanml3d` revision
  `820463f243a39fe8d657c7216ac92f6fcbcb0c37`.
- Length estimator: `cr8br0ze/length_estimator` revision
  `af13da82bf96542c887d2bb60e93d3c79880a1ab`.
- The Hugging Face metadata for all three pinned revisions declares MIT.

## OpenAI CLIP

- Code: `openai/CLIP` revision
  `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6`.
- Checkpoint: official `ViT-B-32.pt` URL published by OpenAI CLIP.
- License: MIT as published in the pinned repository.

## Dataset lineage

The released MARDM checkpoints are trained for the HumanML3D representation,
whose lineage includes HumanML3D and AMASS. Installing these inference files
does not grant rights to redistribute the original datasets or underlying body
model assets. Deployers remain responsible for their intended use, prompts,
outputs, and distribution.
