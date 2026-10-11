---
type: research-log
status: Active
owner: VIREA maintainers
created: 2026-10-11
updated: 2026-10-11
last_reviewed: 2026-10-11
review_cycle_days: 30
summary: Same-sample investigation of rest-frame geometry, SO3 conditioning and device constraints.
canonical: doc/research/skeletal-retargeting-2026-10-11.md
related: [../quality/vrchat-motion.md, ../math-retarget/smplx-to-vrm.zh-CN.md]
supersedes: []
superseded_by: []
---

# Skeletal retargeting: geometry before heuristics

## Research question, hypothesis and motivation

Why can a MotionCraft performance look distorted after conversion to a normalized rig and VRChat? The hypotheses are separable: incorrect rest geometry changes bone directions; inconsistent device mounts overconstrain IK; source temporal noise survives if the official renderer's conditioning is omitted. A different random sample cannot establish whether these defects were repaired.

Success means preserving rigid-bone and frame-change invariants, reducing geometric error on the same native sample, measuring filtering distortion, and separating device inputs from rendered-avatar observations. Model-independent retargeting must remain valid when poses, local axes, body proportions or providers change.

## Setup

- Baseline: `b6e6e4b71348aa6c4dc113a0edd0e12773e36421`.
- Model: MotionCraft revision `a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9`, existing T2M checkpoint.
- Sample: seed 42; six seconds, 180 frames at 30 Hz. Waltz for four seconds, then stand for two seconds.
- Native NPZ SHA256: `64b46c09cb1b1319000a434431a7077d69923ee061ca82bf780f1203e28ad370`.
- Environment: Windows, Python 3.12, project NumPy/SciPy. Comparisons run on CPU without inference, playback or audio output.
- Reference: external neutral SMPL-X joint table, SHA256 `aa80c6e1b28e9d43470f250a2d168bacf2cb0cc5e8688ff2e48e71f4db13ba6c`. This private geometry experiment neither bundles nor deploys the restricted asset. A locally licensed SMPL-X model can supply its own geometry.
- Input hand rotations are used as supplied. No learned mean pose is added.

## Primary-source review

| Source | Finding and implementation decision |
|---|---|
| [MotionCraft paper](https://arxiv.org/html/2407.21136v3) and [pinned viewer](https://github.com/cure-lab/MotionCraft/blob/a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9/tools/visualize.py) | The whole-body display path filters reconstructed pose and translation. Separate raw generation from prepared playback. |
| [SynTalker paper](https://arxiv.org/html/2410.00464v1) and [implementation](https://github.com/RobinWitch/SynTalker) | Decode its own representation and body-part conditions. Recovered joint positions are not observed axial rotations. |
| [SMPL-X implementation](https://github.com/vchoutas/smplx/blob/main/smplx/body_models.py) | Geometry derives from the template. Parameterized hand poses and full local rotations differ; mean addition is an upstream representation choice, not a retarget repair. |
| [VRM pose compatibility](https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm_animation-1.0/how_to_transform_human_pose.md) | Different rest frames require explicit local rotation transformations. |
| [Modern Robotics, Lynch and Park](https://hades.mech.northwestern.edu/images/9/90/MR-tablet-temporary.pdf), chapters 3–4 | Compose rigid transforms along one ordered hierarchy, with offsets in parent coordinates. |
| [Markley et al., Quaternion Averaging](https://ntrs.nasa.gov/api/citations/20070017872/downloads/20070017872.pdf) | Weighted quaternion outer products yield a sign-invariant chordal mean. Handle ambiguous eigenspaces explicitly. |
| [Gleicher, Retargetting Motion to New Characters](https://graphics.cs.wisc.edu/Papers/1998/Gle98/retarget-preprint.pdf) | Changed proportions require sequence-level task constraints, including contact. Correct rotations alone do not establish valid locomotion. |
| [GMR paper](https://arxiv.org/html/2510.02252v1) and [implementation](https://github.com/YanjieZe/GMR/blob/master/general_motion_retargeting/motion_retarget.py) | Rest alignment, local scaling, uniform root scaling and constrained IK solve distinct problems. Record residuals; robot limits cannot simply be applied to avatars. |
| [Valve hand skeleton](https://github.com/ValveSoftware/openvr/wiki/Hand-Skeleton) and [VRChat IK](https://docs.vrchat.com/docs/ik-20-features-and-options) | Device frames and attachment points are execution contracts. All tracking targets must describe the same skeleton. |

## Method

Let `o_j` be a joint offset in parent coordinates, `R_j` the child-to-parent rotation, and `G_j` its world orientation:

$$
G_j = G_{p(j)}R_j, \qquad x_j = x_{p(j)} + G_{p(j)}o_j.
$$

With constant target-to-source joint frames `C_j`:

$$
R'_0=R_0C_0,\qquad R'_j=C_{p(j)}^{-1}R_jC_j.
$$

If offsets transform as `o'_j = C_parent⁻¹ o_j`, induction gives identical world positions and `G'_j = G_j C_j`. The randomized property test checks every bone and frame without a learned model. Different target bone lengths are represented by target offsets; bones remain rigid throughout playback.

World quaternions are composed directly from local quaternions. Reconstructing them independently from matrices can switch representatives between `q` and `−q`; direct composition preserves the continuous lift of a continuous input curve. A full-turn parent/child regression checks this alongside independent world-position equations.

For different rest geometries, fit `C_j` from normalized outgoing directions. Multiple directions use a proper Kabsch rotation. A single direction leaves twist unobservable; minimum-angle swing fixes a constant gauge. Leaves inherit the parent gauge. Different branch angles cannot all be matched by one rigid rotation; retain the residual.

Temporal conditioning applies Gaussian weights, sigma 3.5 samples, to `q qᵀ` and takes the dominant eigenvector. It respects quaternion sign and the π boundary and commutes with constant left/right frame changes. Root translation uses sigma 3 samples. Raw arrays stay unchanged.

## Metrics, baselines and results

Compare source-FK directions with copied local rotations and with source-bound rotations on the target. Both consume the same 180 frames. Interframe SO(3) distances are measured separately from geometric accuracy.

| Metric | Copied rotations | Rest binding | Binding + conditioning |
|---|---:|---:|---:|
| Mean bone-direction error | 15.3585° | 3.6321° | Separate temporal measurement |
| Maximum single-child direction error | 37.9207° | 0.000021° | — |
| Maximum body interframe rotation | 60.6904° | 60.6904° | 9.4320° |

Conditioning changes a body joint by up to **32.5162°** relative to the unfiltered sample. Reducing noise does not preserve every frame's angle. Rest binding alone preserves temporal angular distances. The native digest is unchanged; the experiment generates zero new samples.

## Raw artifacts and reproduction

```bash
python -m scripts.verify.retarget_geometry --native native.npz --source-rig SMPLX_NEUTRAL.npz --output report.json
python -m pytest tests/test_kinematic_frames.py tests/test_source_rig_binding.py tests/character/test_native_sample_identity.py -q
```

The native file contains numeric `values` of shape `(T, 322)`. Geometry is a numeric model NPZ, an NPZ containing `joints55`, or a `(55, 3)` NPY. Use locally licensed assets; this verifier performs no downloads. Private `same-native-mathematics.json` and regression logs remain in `.virea-runtime/qa/refactor-20261011/`.

## Negative results and uncertainty

- Rejecting seed 42 and playing seed 43 did not establish a retarget fix. The retry path and continuity gate were removed. Tests enforce one native sample per plan.
- Both conversion and the old source-FK comparison substituted canonical rest geometry. Their agreement was circular evidence.
- Branch-direction error remains because of different branch geometry. Contact and target-specific proportion constraints need their own measurements.
- Known rest geometry does not supply arbitrary avatar joint limits, collisions or balance constraints. These tests establish kinematic invariants, not complete dynamics.
- The external reference is not a production dependency. Without an installed profile, the compatibility adapter reports `canonical_approximation`; this does not establish exact source geometry.
- These are numerical results, not a new VRChat visual acceptance run. Existing recordings retain their original provenance.

## Conclusion and next step

Promote the shared FK kernel, constant-frame transport, explicit geometry input and no-reseeding behavior to engineering. Keep raw artifacts unchanged and playback conditioning measurable. Iterate on branch/contact constraints and source-to-rendered pose measurements using current avatar geometry and the same retained sample.
