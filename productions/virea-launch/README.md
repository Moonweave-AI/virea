---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-12
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: VIREA · Bring your avatars to life
canonical: productions/virea-launch/README.md
related: []
supersedes: []
superseded_by: []
---

# VIREA · Bring your avatars to life

The English launch film shows how VIREA brings **existing avatars** to life through language, voice and generated movement. VIREA is pronounced **/ˈvɪəriə/**.

[Film, original demos and editable project](https://github.com/Moonweave-AI/virea/releases/tag/launch-film-2026-10) · [Storyboard](STORYBOARD.md) · [Render instructions](edit/README.md)

| Edition | Format |
|:--|:--|
| Master | 3840 × 2160, 30 FPS, 3,795 frames; English narration, music and captions |
| No music | Identical picture; narration and transition effects retained |
| Silent | Identical picture; no audio stream |
| Web preview | 1920 × 1080, sized for GitHub inline playback |

The source project uses deterministic Remotion scenes. Whole-window product recordings remain intact during camera moves; front-facing holds make the interface readable. Moonweave's charcoal, silver, lilac and dusty rose palette carries through the artwork, typography and transitions.

Download the media package and extract it to edit locally. Its `source/edit` and `source/workbench` directories include the selected footage and assets. The repository keeps code and compact delivery documentation; renders, dependencies, logs and source media remain outside Git history.

## What is in the film

Motion Lab compares PRISM and SentiAvatar source skeletons with the retargeted VRM. Character Studio shows a continuous MotionCraft performance. VRChat receives generated head, hand, body and foot poses, shown through the digital character and actual game footage. Set Up connects device discovery, model deployment and generation verification. A final architecture scene connects the model interfaces to both execution targets.

See [design](DESIGN.md), [media and credits](ASSETS.md), and [delivery checks](DELIVERY.md).
