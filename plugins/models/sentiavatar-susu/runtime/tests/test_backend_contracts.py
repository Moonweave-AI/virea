from __future__ import annotations

import base64
import hashlib
import io
import warnings
import wave
from pathlib import Path

import numpy as np
import pytest
from virea_model_sdk.upstream_runtime import InstalledArtifactRoots
from virea_sentiavatar import backend as backend_module
from virea_sentiavatar.backend import SentiAvatarBackend, _read_audio


def _wav_bytes(*, sample_rate: int = 8_000, seconds: float = 1.0) -> bytes:
    stream = io.BytesIO()
    samples = np.zeros((int(sample_rate * seconds),), dtype=np.int16)
    with wave.open(stream, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())
    return stream.getvalue()


def test_inline_audio_is_decoded_and_resampled_to_16khz() -> None:
    encoded = base64.b64encode(_wav_bytes()).decode("ascii")
    roots = InstalledArtifactRoots(roots={})

    waveform = _read_audio(f"data:audio/wav;base64,{encoded}", roots)

    assert waveform.dtype == np.float32
    assert waveform.shape == (16_000,)


def test_artifact_audio_reference_cannot_escape_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(_wav_bytes())
    roots = InstalledArtifactRoots(roots={"sentiavatar-source": root})

    with pytest.raises(Exception, match="unsafe|escapes"):
        _read_audio(
            "artifact://sentiavatar-source/../outside.wav",
            roots,
        )


def test_kmeans_contract_extracts_only_pinned_numeric_centers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    checkpoints = tmp_path / "checkpoints"
    source.mkdir()
    checkpoint = checkpoints / "hubert_kmeans" / "model.mdl"
    checkpoint.parent.mkdir(parents=True)
    payload = b"pinned-estimator-fixture"
    checkpoint.write_bytes(payload)
    monkeypatch.setattr(
        backend_module,
        "_KMEANS_MODEL_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    roots = InstalledArtifactRoots(
        roots={
            "sentiavatar-source": source,
            "sentiavatar-checkpoints": checkpoints,
        }
    )
    backend = SentiAvatarBackend(roots)
    estimator_type = type(
        "MiniBatchKMeans", (), {"__module__": "sklearn.cluster._kmeans"}
    )
    estimator = estimator_type()
    estimator.cluster_centers_ = np.zeros((500, 768), dtype=np.float64)

    class FakeJoblib:
        @staticmethod
        def load(path: Path):
            from sklearn.exceptions import InconsistentVersionWarning

            assert path == checkpoint
            warnings.warn(
                InconsistentVersionWarning(
                    estimator_name="MiniBatchKMeans",
                    current_sklearn_version="1.8.0",
                    original_sklearn_version="1.0.2",
                )
            )
            return estimator

    with warnings.catch_warnings(record=True) as leaked:
        centers = backend._load_kmeans_centers(FakeJoblib)

    assert leaked == []
    assert centers.shape == (500, 768)
    assert centers.dtype == np.float32
    assert centers.flags.c_contiguous


def test_hubert_contract_loads_only_the_pinned_tensor_state_dict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    checkpoints = tmp_path / "checkpoints"
    source.mkdir()
    checkpoint = checkpoints / "chinese-hubert-base" / "pytorch_model.bin"
    checkpoint.parent.mkdir(parents=True)
    payload = b"pinned-hubert-fixture"
    checkpoint.write_bytes(payload)
    monkeypatch.setattr(
        backend_module,
        "_HUBERT_MODEL_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    backend = SentiAvatarBackend(
        InstalledArtifactRoots(
            roots={
                "sentiavatar-source": source,
                "sentiavatar-checkpoints": checkpoints,
            }
        )
    )

    class Tensor:
        pass

    state_dict = {f"parameter.{index}": Tensor() for index in range(211)}

    class FakeTorch:
        @staticmethod
        def load(path: Path, *, map_location: str, weights_only: bool):
            assert path == checkpoint
            assert map_location == "cpu"
            assert weights_only is True
            return state_dict

    FakeTorch.Tensor = Tensor

    class FakeConfig:
        @classmethod
        def from_pretrained(cls, root: Path, *, local_files_only: bool):
            assert root == checkpoint.parent
            assert local_files_only is True
            return cls()

    class FakeModel:
        def __init__(self, config: FakeConfig) -> None:
            assert isinstance(config, FakeConfig)
            self.loaded = False

        def load_state_dict(self, values, *, strict: bool) -> None:
            assert values is state_dict
            assert strict is True
            self.loaded = True

    model = backend._load_hubert_model(FakeTorch, FakeConfig, FakeModel)

    assert isinstance(model, FakeModel)
    assert model.loaded is True
