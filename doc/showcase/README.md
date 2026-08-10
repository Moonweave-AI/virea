---
type: eval-report
status: Active
owner: "@Joker-of-Gotham"
created: 2026-08-08
updated: 2026-08-10
last_reviewed: 2026-08-10
review_cycle_days: 30
title: VIREA Showcase — canonical v3 retargeting results
audience: Researchers, motion engineers, dataset users, and reviewers
visibility: Public
summary: 七个数据集在指定 VRM Avatar 上的 canonical v3 重定向结果，含公开与待许可两类。
canonical: doc/showcase/README.md
related:
  - ../../README.md
  - ../../THIRD_PARTY_NOTICES.md
  - ../validation.zh-CN.md
  - publication-policy.json
  - media/manifest.json
supersedes: []
superseded_by: []
---

<p align="center">
  <img src="../assets/virea-hero.png" width="100%" alt="VIREA canonical humanoid Showcase banner">
</p>

<div align="center">

# VIREA Showcase

### Canonical v3 retargeting results across seven motion sources

Each dataset presents four distinct data entries, all rendered as full-body overview showing the VRM's overall posture.

</div>

The gallery shows modified retargeted motion on **"Unnamed Character 6" by Reira**. Source motion was coordinate-normalized, converted to VIREA canonical v3, transferred to the VRM humanoid, and rendered in a whole-body view. Neither source datasets nor the `.vrm` model are distributed here. All twenty-eight GIFs (four per dataset × seven datasets) are listed with exact provenance and SHA-256 values in the [media manifest](media/manifest.json).

---

## BEAT

<table>
  <tr>
    <td width="50%" align="center"><img src="media/beat/hero.gif" width="100%" alt="BEAT Wayne gesture 100 — full-body overview"><br><sub><strong>Wayne gesture 100</strong></sub></td>
    <td width="50%" align="center"><img src="media/beat/hands.gif" width="100%" alt="BEAT Wayne gesture 101 — full-body overview"><br><sub><strong>Wayne gesture 101</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/beat/feet.gif" width="100%" alt="BEAT Wayne gesture 102 — full-body overview"><br><sub><strong>Wayne gesture 102</strong></sub></td>
    <td width="50%" align="center"><img src="media/beat/facing.gif" width="100%" alt="BEAT Wayne gesture 103 — full-body overview"><br><sub><strong>Wayne gesture 103</strong></sub></td>
  </tr>
</table>

The source BVH clips are from the pinned [official BEAT dataset revision](https://huggingface.co/datasets/H-Liu1997/BEAT/tree/604f5eca9d8dc2e1b8c3ed21045f9e24a7b6d3ff), declared [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0). Credit: Haiyang Liu and the BEAT authors and contributors. See the [BEAT paper](https://arxiv.org/abs/2203.05297).

---

## Motion-X / AIST++

<table>
  <tr>
    <td width="50%" align="center"><img src="media/motionx/hero.gif" width="100%" alt="Motion-X Dance Break — full-body overview"><br><sub><strong>Dance Break</strong></sub></td>
    <td width="50%" align="center"><img src="media/motionx/hands.gif" width="100%" alt="Motion-X 3 Step — full-body overview"><br><sub><strong>3 Step</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/motionx/feet.gif" width="100%" alt="Motion-X 6 Step — full-body overview"><br><sub><strong>6 Step</strong></sub></td>
    <td width="50%" align="center"><img src="media/motionx/facing.gif" width="100%" alt="Motion-X Battle Rock — full-body overview"><br><sub><strong>Battle Rock</strong></sub></td>
  </tr>
</table>

Motion-X annotations © International Digital Economy Academy are licensed [CC BY-NC-SA 4.0](https://motion-x-dataset.github.io/static/license/Motion-X%20License.pdf). The AIST++ source annotations © Google LLC are licensed [CC BY 4.0](https://google.github.io/aistplusplus_dataset/factsfigures.html). Modified GIFs are offered under CC BY-NC-SA 4.0 for non-commercial use. Cite [Motion-X](https://motion-x-dataset.github.io/) and [AIST++](https://google.github.io/aistplusplus_dataset/).

---

## SuSuInterActs

<table>
  <tr>
    <td width="50%" align="center"><img src="media/susuinteracts/hero.gif" width="100%" alt="SuSuInterActs near-face interaction — full-body overview"><br><sub><strong>Near-face interaction</strong></sub></td>
    <td width="50%" align="center"><img src="media/susuinteracts/hands.gif" width="100%" alt="SuSuInterActs gesture motion — full-body overview"><br><sub><strong>Gesture motion</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/susuinteracts/feet.gif" width="100%" alt="SuSuInterActs crossed-arm motion — full-body overview"><br><sub><strong>Crossed-arm motion</strong></sub></td>
    <td width="50%" align="center"><img src="media/susuinteracts/facing.gif" width="100%" alt="SuSuInterActs dialogue motion — full-body overview"><br><sub><strong>Dialogue motion</strong></sub></td>
  </tr>
</table>

SuSuInterActs © 2026 **Shandong SentiPulse Technology Development Co., Ltd.** is governed by the [SentiPulse Non-Commercial Source License v1.0](https://github.com/SentiAvatar/SentiAvatar/blob/71c61b05a0609a41c17aa146c9f4ee7778ebc649/LICENSE). Modified derivative renderings for non-commercial use. The license is source-available, not open source. Cite [SentiAvatar: Towards Expressive and Interactive Digital Humans](https://arxiv.org/abs/2604.02908).

---

## AMASS

<table>
  <tr>
    <td width="50%" align="center"><img src="media/amass/hero.gif" width="100%" alt="AMASS stand to skip — full-body overview"><br><sub><strong>Stand to skip</strong></sub></td>
    <td width="50%" align="center"><img src="media/amass/hands.gif" width="100%" alt="AMASS upper-body swing — full-body overview"><br><sub><strong>Upper-body swing</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/amass/feet.gif" width="100%" alt="AMASS lie to crouch — full-body overview"><br><sub><strong>Lie to crouch</strong></sub></td>
    <td width="50%" align="center"><img src="media/amass/facing.gif" width="100%" alt="AMASS crawl forward — full-body overview"><br><sub><strong>Crawl forward</strong></sub></td>
  </tr>
</table>

AMASS © Max Planck Gesellschaft. [License terms](https://amass.is.tue.mpg.de/license.html) apply; four distinct ACCAD clips rendered as modified retargeted GIFs.

---

## BABEL

<table>
  <tr>
    <td width="50%" align="center"><img src="media/babel/hero.gif" width="100%" alt="BABEL walk cycle — full-body overview"><br><sub><strong>Walk cycle</strong></sub></td>
    <td width="50%" align="center"><img src="media/babel/hands.gif" width="100%" alt="BABEL urban gestures — full-body overview"><br><sub><strong>Urban gestures</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/babel/feet.gif" width="100%" alt="BABEL run motion — full-body overview"><br><sub><strong>Run motion</strong></sub></td>
    <td width="50%" align="center"><img src="media/babel/facing.gif" width="100%" alt="BABEL walk to stand — full-body overview"><br><sub><strong>Walk to stand</strong></sub></td>
  </tr>
</table>

BABEL © Max Planck Gesellschaft. [License terms](https://babel.is.tue.mpg.de/license.html) apply; four distinct ACCAD clips rendered as modified retargeted GIFs.

---

## GRAB

<table>
  <tr>
    <td width="50%" align="center"><img src="media/grab/hero.gif" width="100%" alt="GRAB airplane fly — full-body overview"><br><sub><strong>Airplane fly</strong></sub></td>
    <td width="50%" align="center"><img src="media/grab/hands.gif" width="100%" alt="GRAB airplane lift — full-body overview"><br><sub><strong>Airplane lift</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/grab/feet.gif" width="100%" alt="GRAB airplane off-hand — full-body overview"><br><sub><strong>Airplane off-hand</strong></sub></td>
    <td width="50%" align="center"><img src="media/grab/facing.gif" width="100%" alt="GRAB airplane pass — full-body overview"><br><sub><strong>Airplane pass</strong></sub></td>
  </tr>
</table>

GRAB © Max Planck Gesellschaft. [License terms](https://grab.is.tue.mpg.de/license.html) apply; four distinct object-interaction clips rendered as modified retargeted GIFs.

---

## HumanML3D

<table>
  <tr>
    <td width="50%" align="center"><img src="media/humanml3d/hero.gif" width="100%" alt="HumanML3D sample 0 — full-body overview"><br><sub><strong>Text-motion sample 0</strong></sub></td>
    <td width="50%" align="center"><img src="media/humanml3d/hands.gif" width="100%" alt="HumanML3D sample 3 — full-body overview"><br><sub><strong>Text-motion sample 3</strong></sub></td>
  </tr>
  <tr>
    <td width="50%" align="center"><img src="media/humanml3d/feet.gif" width="100%" alt="HumanML3D sample 4 — full-body overview"><br><sub><strong>Text-motion sample 4</strong></sub></td>
    <td width="50%" align="center"><img src="media/humanml3d/facing.gif" width="100%" alt="HumanML3D turning sample 7 — full-body overview"><br><sub><strong>Turning sample 7</strong></sub></td>
  </tr>
</table>

HumanML3D uses AMASS-carried motion. [HumanML3D license](https://github.com/EricGuo5513/HumanML3D#how-to-obtain-the-data) applies; four distinct text-motion test samples rendered as modified retargeted GIFs.

---

## Avatar and media terms

| Material | Attribution and scope |
|---|---|
| VRM Avatar | **"Unnamed Character 6" by Reira**; non-commercial use, credit required, alteration allowed, `.vrm` redistribution prohibited. [Official VRoid condition guide](https://vroid.pixiv.help/hc/en-us/articles/360013153714--About-the-characters-conditions-of-use). |
| BEAT GIFs | Modified retargeted renderings under the upstream Apache-2.0 declaration and notices. |
| Motion-X / AIST++ GIFs | Modified retargeted renderings; CC BY-NC-SA 4.0, non-commercial, attribution and ShareAlike required. |
| SuSuInterActs GIFs | Modified derivative renderings; SentiPulse Non-Commercial Source License v1.0, attribution and license copy required, no additional restrictions. |
| AMASS GIFs | Modified retargeted renderings; AMASS license terms apply, four ACCAD clips. |
| BABEL GIFs | Modified retargeted renderings; BABEL license terms apply, four ACCAD carrier clips. |
| GRAB GIFs | Modified retargeted renderings; GRAB license terms apply, four object-interaction clips. |
| HumanML3D GIFs | Modified retargeted renderings; HumanML3D license terms apply, four text-motion test samples. |

No upstream author, dataset publisher, Avatar creator, or licensor endorses VIREA. The exact public allowlist is [machine-readable](publication-policy.json); comprehensive attribution and license text are in [Third-Party Notices](../../THIRD_PARTY_NOTICES.md).
