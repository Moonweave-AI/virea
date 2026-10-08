"""Explicit projection onto the SDK avatar's emotes, not skeletal streaming.

The published VIREA avatar retains the SDK Action controller. Other avatars must
opt in only after checking their VRCEmote mapping. Unknown actions stay unknown.
"""

import re

from .contracts import FACE_PARAMETERS

EMOTES = (
    (1, "wave", r"\b(?:wave[sd]?|waving)\b"),
    (2, "clap", r"\bclap(?:s|ped|ping)?\b"),
    (3, "point", r"\bpoint(?:s|ed|ing)?\b"),
    (4, "cheer", r"\bcheer(?:s|ed|ing)?\b"),
    (5, "dance", r"\b(?:dance[sd]?|dancing)\b"),
)
FACES = (
    ("AI_Smile", r"\b(?:smile[sd]?|smiling)\b"),
    ("AI_Sad", r"\b(?:sad|frown[sd]?|frowning)\b"),
    ("AI_Angry", r"\b(?:angry|anger)\b"),
    ("AI_Surprised", r"\b(?:surprised|surprise)\b"),
)
NEGATION = re.compile(r"\b(?:not|never|without|don't|doesn't|no)\b", re.I)


class DesktopTimeline:
    def __init__(self, performance):
        self.clips = []
        for clip in performance.get("motions", []):
            prompt = clip["prompt"]
            allowed = not NEGATION.search(prompt)
            matches = [
                (number, name)
                for number, name, pattern in EMOTES
                if allowed and re.search(pattern, prompt, re.I)
            ]
            # A complex multi-action caption must not silently collapse to one emote.
            number, name = matches[0] if len(matches) == 1 else (0, None)
            faces = [
                parameter
                for parameter, pattern in FACES
                if allowed and re.search(pattern, prompt, re.I)
            ]
            self.clips.append(
                {
                    "id": clip.get("id"),
                    "prompt": prompt,
                    "start": clip["start_seconds"],
                    "duration": clip["duration_seconds"],
                    "emote": number,
                    "preset": name,
                    "faces": faces,
                }
            )

    def sample(self, seconds):
        weights = {name: 0.0 for names in FACE_PARAMETERS.values() for name in names}
        for clip in self.clips:
            local = seconds - clip["start"]
            if 0 <= local < clip["duration"]:
                envelope = min(1.0, local / 0.25, (clip["duration"] - local) / 0.25)
                for parameter in clip["faces"]:
                    weights.update(
                        {name: 0.7 * envelope for name in FACE_PARAMETERS[parameter]}
                    )
                return clip["emote"], weights
        return 0, weights

    def summary(self, enabled):
        return [
            {
                "id": clip["id"],
                "prompt": clip["prompt"],
                "body_output": f"avatar_preset:{clip['preset']}"
                if enabled and clip["preset"]
                else "not_transmitted",
                "face_cues": clip["faces"],
            }
            for clip in self.clips
        ]
