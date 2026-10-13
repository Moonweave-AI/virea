---
type: how-to
status: Active
owner: VIREA maintainers
created: 2026-10-12
updated: 2026-10-13
last_reviewed: 2026-10-13
review_cycle_days: 90
summary: Delivery and validation
canonical: productions/virea-launch/DELIVERY.md
related: []
supersedes: []
superseded_by: []
---

# Delivery and validation

The media release contains the 4K master, narration-and-effects edition, silent edition, 1080p web preview, cover, English SRT and editable source package.

Validation covers full video/audio decode, exact 3,795-frame picture length, matching compressed picture across audio editions, caption timing, offline audio placement and true peaks. A clean-context review checked the final cover, all chapters, key transitions, the extended SentiAvatar/Character footage and closing copy. Fifteen 4K frames match the workbench import pixel for pixel.

Audio was analyzed offline without speaker playback. The public README uses compact video attachments and links to the 4K originals. The final package carries checksums and source hashes so a later edit can be traced to its inputs.

After changing any scene, timing or asset, render again and repeat the affected checks. `package_delivery.py` packages the explicit allowlist in `delivery-manifest.json` after the measured export, media identity and workbench checks pass.
