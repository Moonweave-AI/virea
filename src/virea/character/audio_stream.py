"""Reblock incremental PCM across language clauses without inserting silence."""

import io
import wave
from collections import deque


class PCMWindows:
    """Short first window, then 4.8s windows to amortize motion-planner overhead.

    Caption slices describe speech units, not forced word alignment. PCM samples
    are preserved exactly; tiny tails are absorbed instead of padded repeatedly.
    """

    def __init__(self):
        self.parts = deque()
        self.frames = 0
        self.first = True

    def push(self, unit):
        with wave.open(io.BytesIO(unit["audio"]), "rb") as source:
            if source.getparams()[:3] != (1, 2, 24000):
                raise ValueError("stream requires mono PCM16 at 24 kHz")
            pcm = source.readframes(source.getnframes())
        self.parts.append(dict(unit, pcm=pcm))
        self.frames += len(pcm) // 2
        return self.take()

    def take(self, final=False):
        windows = []
        while self.frames:
            target = 57_600 if self.first else 115_200
            if not final and self.frames < target + 14_400:
                break
            count = min(target, self.frames)
            if self.frames - count < 14_400:
                count = self.frames
            remaining, chunks, texts, captions = count, [], [], []
            decision = self.parts[0].get("decision")
            dominant_frames = 0
            while remaining:
                part = self.parts[0]
                size = min(remaining, len(part["pcm"]) // 2)
                if size > dominant_frames:
                    decision, dominant_frames = part.get("decision"), size
                end = round(len(part["text"]) * size * 2 / len(part["pcm"]))
                chunks.append(part["pcm"][: size * 2])
                texts.append(part["text"][:end])
                if not captions or captions[-1] != part["caption"]:
                    captions.append(part["caption"])
                part["pcm"], part["text"] = part["pcm"][size * 2 :], part["text"][end:]
                remaining -= size
                if not part["pcm"]:
                    self.parts.popleft()
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as stream:
                stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                stream.writeframes(b"".join(chunks))
            windows.append(
                dict(
                    audio=buffer.getvalue(),
                    seconds=count / 24000,
                    text="".join(texts),
                    caption="".join(captions),
                    decision=decision,
                    continues=not (final and count == self.frames),
                )
            )
            self.frames -= count
            self.first = False
        return windows
