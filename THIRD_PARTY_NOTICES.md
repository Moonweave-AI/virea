# Third-Party Notices

This notice records third-party material used or distributed by VIREA,
including model Runtimes, the browser bundle, the public retargeting gallery,
and source-skeleton tables. It does not grant a license to VIREA code as a
whole.

## Common media changes

All 28 dataset-derived GIFs were transformed as follows: source motion was decoded and coordinate-normalized, retargeted into VIREA canonical v3, transferred to the credited VRM humanoid, camera-framed for a whole-body, hand, foot, or facing view, and encoded as an animated GIF. Twelve have the public-use basis documented below; the other sixteen are displayed at the repository owner's explicit direction while upstream permission remains unverified. Display does not convert those sixteen files into publicly licensed material. The repository does not distribute the source motion arrays, dialogue, audio, face channels, source video or music, or the `.vrm` model. Exact per-file samples, source revisions, change statements, dimensions, frame counts, durations, and recorded identities are in the [media manifest](doc/showcase/media/manifest.json); those identities are provenance records, not a new release-readiness hash gate.

No upstream author, publisher, or Avatar creator endorses VIREA.

## VRM Avatar: “Unnamed Character 6” by Reira

- Creator credit: **Reira**
- Audited model SHA-256: `f7c947ef380b9478db166db0366cec1dc3ceebafecf76a1b986fe104e793d998`
- Embedded permission settings: everyone may use the Avatar; credit is necessary; alteration is allowed; personal and corporate commercial use are disallowed; redistribution of the model is disallowed.
- Exact permission URL: <https://hub.vroid.com/license?allowed_to_use_user=everyone&characterization_allowed_user=everyone&corporate_commercial_use=disallow&credit=necessary&modification=allow&personal_commercial_use=disallow&redistribution=disallow&sexual_expression=disallow&version=1&violent_expression=allow>
- Official explanation: [VRoid character conditions of use](https://vroid.pixiv.help/hc/en-us/articles/360013153714--About-the-characters-conditions-of-use)

Only rendered non-commercial GIFs are included. The `.vrm` file is not redistributed.

## BEAT public GIFs

- Source: [H-Liu1997/BEAT](https://huggingface.co/datasets/H-Liu1997/BEAT), revision `604f5eca9d8dc2e1b8c3ed21045f9e24a7b6d3ff`
- License declaration: [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) at the pinned [official dataset revision](https://huggingface.co/datasets/H-Liu1997/BEAT/tree/604f5eca9d8dc2e1b8c3ed21045f9e24a7b6d3ff)
- Attribution: Haiyang Liu and the BEAT authors and contributors
- Citation: [BEAT: A Large-Scale Semantic and Emotional Multi-Modal Dataset for Conversational Gestures Synthesis](https://arxiv.org/abs/2203.05297)
- Files: `doc/showcase/media/beat/{hero,hands,feet,facing}.gif`

The files are modified retargeted renderings. Existing upstream copyright, attribution, patent, trademark, and NOTICE obligations remain applicable under Apache-2.0.

## Motion-X / AIST++ public GIFs

- Motion-X authority: [IDEA-Research/Motion-X](https://github.com/IDEA-Research/Motion-X), revision `2a7db28fc624af736c3eaaa8c10ff375ed69991e`
- AIST++ authority: [google/aistplusplus_api](https://github.com/google/aistplusplus_api), revision `2dd7b3e946b794fd0081c98e2e2433545abf8b87`
- Motion-X license: [CC BY-NC-SA 4.0](https://motion-x-dataset.github.io/static/license/Motion-X%20License.pdf), © International Digital Economy Academy
- AIST++ annotation license: [CC BY 4.0](https://google.github.io/aistplusplus_dataset/factsfigures.html), © Google LLC
- Citations: [Motion-X](https://arxiv.org/abs/2307.00818) and [AI Choreographer / AIST++](https://arxiv.org/abs/2101.08779)
- Files: `doc/showcase/media/motionx/{hero,hands,feet,facing}.gif`

The files are modified retargeted renderings and are offered under **CC BY-NC-SA 4.0** for non-commercial use. Attribution, license link, indication of changes, and ShareAlike are required.

## SuSuInterActs public GIFs

- Dataset source: [Chuhaojin/SuSuInterActs](https://huggingface.co/datasets/Chuhaojin/SuSuInterActs), revision `9aaaf212d05c5867c2bb08290f40bf523e1aa4b3`
- Authority repository: [SentiAvatar/SentiAvatar](https://github.com/SentiAvatar/SentiAvatar), revision `71c61b05a0609a41c17aa146c9f4ee7778ebc649`
- Copyright and required licensor credit: © 2026 **山东思维光谱科技发展有限公司 / Shandong SentiPulse Technology Development Co., Ltd.**
- License: [SentiPulse Non-Commercial Source License v1.0](https://github.com/SentiAvatar/SentiAvatar/blob/71c61b05a0609a41c17aa146c9f4ee7778ebc649/LICENSE)
- Citation: [SentiAvatar: Towards Expressive and Interactive Digital Humans](https://arxiv.org/abs/2604.02908)
- Files: `doc/showcase/media/susuinteracts/{hero,hands,feet,facing}.gif`

The files are modified derivative renderings for non-commercial use. Public use must credit the licensor, refer to the license, and state the modifications. Distribution must include the license, add no legal or technical restrictions, and clearly remain non-commercial. The license is **source-available, not open source**. Its definition of commercial use includes use by or for a for-profit entity, revenue-bearing services, SaaS/API/cloud services, internal commercial operations, advertising, marketing, and monetization; those uses require a separate written commercial license.

<details>
<summary>Copy of SentiPulse Non-Commercial Source License v1.0</summary>

```text
SentiPulse Non-Commercial Source License v1.0

Copyright (c) 2026
山东思维光谱科技发展有限公司
Shandong SentiPulse Technology Development Co., Ltd.

This License governs the use, reproduction, modification, and distribution
of the software, source code, model weights, datasets, documentation, and
other related materials (collectively, the "Licensed Materials").

1. Grant of Rights

Subject to the terms and conditions of this License, the Licensor hereby
grants you a non-exclusive, worldwide, royalty-free license to:

a) Use the Licensed Materials for non-commercial purposes only;
b) Copy and reproduce the Licensed Materials;
c) Modify, adapt, and create derivative works of the Licensed Materials;
d) Distribute the Licensed Materials or derivative works, provided that
   such distribution is also non-commercial and complies with this License.

2. Non-Commercial Use Only

You may not use the Licensed Materials, in whole or in part, for any
commercial purpose.

For the avoidance of doubt, "commercial purpose" includes, but is not
limited to:

a) Use by or on behalf of a for-profit entity;
b) Use in products, services, or systems that generate revenue, fees,
   subscriptions, or other consideration, whether directly or indirectly;
c) Use as part of a hosted service, SaaS offering, API service, or
   cloud-based platform;
d) Use in internal business operations, production systems, or
   decision-making processes of a commercial organization;
e) Use in connection with advertising, marketing, or monetization activities.

Any use not expressly permitted under this License shall be deemed
commercial use.

3. Attribution

You must provide appropriate attribution in any distribution or public use
of the Licensed Materials or derivative works, including:

a) The name of the Licensor;
b) A reference to this License; and
c) An indication of any modifications made.

Attribution must not imply endorsement by the Licensor.

4. Distribution Conditions

If you distribute the Licensed Materials or derivative works:

a) You must include a copy of this License;
b) You must not impose any additional legal or technical restrictions;
c) You must clearly state that the materials are licensed for
   non-commercial use only.

5. No Open Source Grant

This License does not grant rights under any open source license and shall
not be construed as an open source license. The Licensed Materials are
source-available but not open source.

6. Commercial Licensing

Commercial use of the Licensed Materials requires a separate written
commercial license agreement with the Licensor.

For commercial licensing inquiries, please contact:
legal@sentipulse.com

7. No Trademark Rights

This License does not grant permission to use the Licensor’s trademarks,
logos, or brand identifiers.

8. Disclaimer of Warranty

THE LICENSED MATERIALS ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT.

9. Limitation of Liability

IN NO EVENT SHALL THE LICENSOR BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING
FROM, OUT OF, OR IN CONNECTION WITH THE LICENSED MATERIALS OR THE USE OR
OTHER DEALINGS IN THE LICENSED MATERIALS.

10. Termination

This License shall automatically terminate if you breach any of its terms.
Upon termination, you must cease all use and distribution of the Licensed
Materials.

11. Governing Law

This License shall be governed by and construed in accordance with the laws
of the People's Republic of China, excluding its conflict of law principles.
```

</details>

## SentiAvatar MTA63 source-skeleton geometry

- Source repository: [SentiAvatar/SentiAvatar](https://github.com/SentiAvatar/SentiAvatar), revision `1067a67f2ddab48dfbdd73189a3d1a46abd4cdca`
- Source files: `motion_generation/meta/mta63joints/template_susu_retarget_63nodes.bvh`, `motion_generation/meta/mta63joints/src_joint_dict.json`, and the related local-rotation export implementation
- License at that revision: [CC BY-NC 4.0](https://github.com/SentiAvatar/SentiAvatar/blob/1067a67f2ddab48dfbdd73189a3d1a46abd4cdca/LICENSE), © 2026 Chuhao Jin

VIREA adapted the numerical MTA63 hierarchy and rest geometry in `src/virea/motion/codecs.py`: offsets were converted from centimetres to metres and stored as `float32`; the hierarchy was separated into body and hand tables; duplicated wrist slots were represented explicitly; source metacarpals were retained for FK; and stable identifiers were added. This adapted material is restricted to non-commercial use, requires attribution and indication of changes, and may not carry additional restrictions.

## PRISM managed runtime

- Source repository: [ZeyuLing/PRISM](https://github.com/ZeyuLing/PRISM), revision `3c58bc5d946f0827171a3712ed36314f4b1a5186`
- Adapted source: `prism/pipelines/prism_ar_t2m_pipeline.py`, prompt-encoding sequence
- Local integration: `plugins/models/prism-tp2m-1-4b/runtime/src/virea_prism/offline_loader.py`

The pinned PRISM and VersatileMotion repositories do not publish usable
licensing terms. The prompt-encoding sequence in the managed runtime follows
the upstream tokenizer, attention-mask, encoder, trim, pad, repeat, and reshape
flow. VIREA's local MIT notice does not cover that adapted sequence. The
runtime may be used for the current private/internal technical acceptance, but
public or commercial redistribution requires upstream permission or a
separately evidenced independent replacement.

## Browser Web distribution

The production assets under `apps/web/dist` bundle the following pinned
browser dependencies. Their MIT licenses apply only to the named third-party
software and do not license VIREA as a whole.

- `three` `0.183.2`: [npm package](https://www.npmjs.com/package/three/v/0.183.2),
  [official source tag `r183`](https://github.com/mrdoob/three.js/tree/r183),
  [MIT license](https://github.com/mrdoob/three.js/blob/r183/LICENSE),
  Copyright © 2010–2026 three.js authors.
- `@pixiv/three-vrm` `3.5.1` and `@pixiv/three-vrm-animation` `3.5.1`:
  [official source tag `v3.5.1`](https://github.com/pixiv/three-vrm/tree/v3.5.1),
  [MIT license](https://github.com/pixiv/three-vrm/blob/v3.5.1/LICENSE),
  Copyright © 2019–2026 pixiv Inc.
- `vite` `7.3.1`: the production output contains Vite's injected
  `modulepreload` runtime helper; [official source tag `v7.3.1`](https://github.com/vitejs/vite/tree/v7.3.1),
  [Vite core MIT license and complete bundled-dependency notices](https://github.com/vitejs/vite/blob/v7.3.1/packages/vite/LICENSE.md),
  Copyright © 2019–present, VoidZero Inc. and Vite contributors.

The corresponding license texts ship beside the browser bundle at
`apps/web/dist/third-party-notices/three-LICENSE.txt` and
`apps/web/dist/third-party-notices/pixiv-three-vrm-LICENSE.txt`, while the Vite
core terms accompanying the generated helper are in
`apps/web/dist/third-party-notices/vite-core-LICENSE.txt`. Their canonical Vite
public sources are under `apps/web/public/third-party-notices/` so a clean Web
rebuild preserves the notices.

## Permission-required source families

| Source | Public media status | Official terms |
|---|---|---|
| AMASS | Permission required | [AMASS license](https://amass.is.tue.mpg.de/license.html) |
| BABEL | Permission required | [BABEL license](https://babel.is.tue.mpg.de/license.html) |
| GRAB | Permission required | [GRAB license](https://grab.is.tue.mpg.de/license.html) |
| Selected HumanML3D samples | Permission required because the selected carriers are AMASS-derived | [HumanML3D data notice](https://github.com/EricGuo5513/HumanML3D#how-to-obtain-the-data) |


<!--
---
type: notice
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-09
updated: 2026-08-21
last_reviewed: 2026-08-21
review_cycle_days: 90
title: VIREA Third-Party Notices
audience: Users, distributors, and IP reviewers
visibility: Public
summary: VIREA 模型 Runtime、权重、公开重定向媒体、指定 VRM Avatar 与内嵌第三方几何资料的来源、署名、改动和许可边界。
canonical: THIRD_PARTY_NOTICES.md
related:
  - README.md
  - doc/showcase/README.md
  - doc/showcase/media/manifest.json
  - doc/showcase/publication-policy.json
supersedes: []
superseded_by: []
---
-->
