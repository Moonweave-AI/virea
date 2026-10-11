import asyncio
import io
import wave
from types import SimpleNamespace

import numpy as np
import pytest
from virea_retarget import retarget_motion_ir

from virea.adapters.capabilities import ArtifactAudio, NativeMotionAdapter
from virea.application.artifacts import ArtifactStore
from virea.application.native_artifact import native_artifact


def test_audio_artifact_uses_measured_samples_and_rejects_false_duration(tmp_path):
    async def run():
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(
                (np.sin(np.arange(16000) / 30) * 8000).astype("<i2").tobytes()
            )

        async def synthesize(_):
            return output.getvalue(), 99.0

        store = ArtifactStore(tmp_path)
        result = await ArtifactAudio(
            SimpleNamespace(synthesize=synthesize), store
        ).synthesize("hello")
        assert result.duration_seconds == 1.0 and result.sample_count == 16000
        assert store.read(result.artifact, result.sha256).startswith(b"RIFF")

    asyncio.run(run())


def test_native_face_samples_survive_the_shared_ir_and_retarget_boundary(tmp_path):
    values = np.zeros((30, 322), dtype=np.float32)
    values[:, 159:209] = np.linspace(0, 0.8, 30)[:, None]
    store = ArtifactStore(tmp_path)
    native = native_artifact(store, "motioncraft", values, {"source_revision": "test"})
    motion = NativeMotionAdapter(store).normalize(native)
    np.testing.assert_array_equal(motion.face_tracks[0]["values"], values[:, 159:209])
    result = retarget_motion_ir(motion)
    np.testing.assert_array_equal(result.face_tracks[0]["values"], values[:, 159:209])
    assert result.actors[0].canonical211.shape == (30, 211)
    with pytest.raises(ValueError, match="source profile"):
        NativeMotionAdapter(store).normalize(
            native.model_copy(update={"model_id": "syntalker"})
        )
