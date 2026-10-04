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
        self.position = 0
        self.marks = deque()
        self.rate = None

    def mark(self, name: str):
        """Place an event at an exact PCM boundary, before reblocking."""
        self.marks.append((name, self.position + self.frames))

    def push(self, unit):
        with wave.open(io.BytesIO(unit["audio"]), "rb") as source:
            channels, width, rate, frames, compression, _ = source.getparams()
            if (
                channels != 1
                or width != 2
                or compression != "NONE"
                or rate not in (24000, 44100, 48000)
            ):
                raise ValueError("stream requires mono PCM16 at 24, 44.1 or 48 kHz")
            if self.rate is not None and rate != self.rate:
                raise ValueError("speech sample rate changed within a stream")
            self.rate = rate
            pcm = source.readframes(source.getnframes())
            if not frames or len(pcm) != frames * 2:
                raise ValueError("empty or truncated speech audio")
        self.parts.append(dict(unit, pcm=pcm))
        self.frames += len(pcm) // 2
        return self.take()

    def take(self, final=False):
        windows = []
        while self.frames:
            target = round(self.rate * (2.4 if self.first else 4.8))
            tail = round(self.rate * 0.6)
            if not final and self.frames < target + tail:
                break
            count = min(target, self.frames)
            if self.frames - count < tail:
                count = self.frames
            remaining, chunks, texts, captions = count, [], [], []
            decision = self.parts[0].get("decision")
            speech_start = self.parts[0].get("speech_start")
            dominant_frames = 0
            while remaining:
                part = self.parts[0]
                size = min(remaining, len(part["pcm"]) // 2)
                if size > dominant_frames:
                    decision, dominant_frames = part.get("decision"), size
                end = round(len(part["text"]) * size * 2 / len(part["pcm"]))
                chunks.append(part["pcm"][: size * 2])
                texts.append(part["text"][:end])
                if part.get("caption") and (
                    not captions or captions[-1] != part["caption"]
                ):
                    captions.append(part["caption"])
                part["pcm"], part["text"] = part["pcm"][size * 2 :], part["text"][end:]
                remaining -= size
                if not part["pcm"]:
                    self.parts.popleft()
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as stream:
                stream.setparams((1, 2, self.rate, 0, "NONE", "not compressed"))
                stream.writeframes(b"".join(chunks))
            windows.append(
                dict(
                    audio=buffer.getvalue(),
                    seconds=count / self.rate,
                    text="".join(texts),
                    caption="".join(texts) or "".join(captions),
                    decision=decision,
                    speech_start=speech_start,
                    continues=not (final and count == self.frames),
                    speech_marks=[],
                )
            )
            while self.marks and self.marks[0][1] <= self.position + count:
                name, at = self.marks.popleft()
                windows[-1]["speech_marks"].append(
                    {"name": name, "offset_seconds": (at - self.position) / self.rate}
                )
            self.position += count
            self.frames -= count
            self.first = False
        return windows
