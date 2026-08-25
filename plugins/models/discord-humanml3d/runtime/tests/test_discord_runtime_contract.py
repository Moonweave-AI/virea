from __future__ import annotations

import json
import zipfile
from pathlib import Path
from threading import Event

import numpy as np
import pytest
import yaml
from virea_contracts.job import JobRequest
from virea_contracts.runtime import RuntimeSpec
from virea_contracts.worker import WorkerInferRequest
from virea_discord.artifacts import (
    MOMASK_ARCHIVE,
    MOMASK_MEMBERS,
    REQUIRED_SOURCE_FILES,
    SOURCE_ARCHIVE,
    SOURCE_PREFIX,
    ArtifactRoots,
    materialize_artifacts,
)
from virea_discord.backend import DiscordBackend, GenerationOutput
from virea_discord.worker import DiscordHumanML3DPlugin, resolve_motion_length
from virea_model_sdk import WorkerContext, WorkerFailure

MODEL_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = MODEL_ROOT.parents[2]


def _zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_artifact_roots_require_both_precise_manual_files(tmp_path: Path) -> None:
    mapping = {
        name: tmp_path / name
        for name in (
            "discord-momask-rf-decoder",
            "momask-humanml3d-models",
            "discord-source",
            "openai-clip-vit-b32",
        )
    }
    for path in mapping.values():
        path.mkdir()
    roots = ArtifactRoots.from_json(
        json.dumps({key: str(value) for key, value in mapping.items()})
    )
    assert roots.rf_decoder == mapping["discord-momask-rf-decoder"].resolve()
    del mapping["discord-momask-rf-decoder"]
    with pytest.raises(WorkerFailure, match="discord-momask-rf-decoder"):
        ArtifactRoots.from_json(
            json.dumps({key: str(value) for key, value in mapping.items()})
        )


def test_materializer_validates_source_and_every_momask_member(tmp_path: Path) -> None:
    rf, momask, source, clip = (
        tmp_path / name for name in ("rf", "momask", "source", "clip")
    )
    for path in (rf, momask, source, clip):
        path.mkdir()
    (rf / "DisCoRD_Momask_RFDecoder_best.pth").write_bytes(b"rf")
    (clip / "ViT-B-32.pt").write_bytes(b"clip")
    _zip(
        source / SOURCE_ARCHIVE,
        {f"{SOURCE_PREFIX}{name}": b"source" for name in REQUIRED_SOURCE_FILES},
    )
    _zip(momask / MOMASK_ARCHIVE, {name: b"model" for name in MOMASK_MEMBERS.values()})
    artifacts = materialize_artifacts(
        ArtifactRoots(rf, momask, source, clip), cache_root=tmp_path / "cache"
    )
    assert artifacts.rf_checkpoint.read_bytes() == b"rf"
    assert (
        artifacts.source_root / "checkpoints/Momask/checkpoints/net_best_fid.tar"
    ).is_file()

    incomplete = {name: b"model" for name in MOMASK_MEMBERS.values()}
    del incomplete[MOMASK_MEMBERS["mask_checkpoint"]]
    _zip(momask / MOMASK_ARCHIVE, incomplete)
    with pytest.raises(WorkerFailure, match="missing"):
        materialize_artifacts(
            ArtifactRoots(rf, momask, source, clip), cache_root=tmp_path / "cache2"
        )


def test_request_bounds_require_explicit_four_frame_length() -> None:
    assert resolve_motion_length({"motion_length_frames": 80}) == (80, None)
    assert resolve_motion_length({"seconds": 4.0}) == (80, 4.0)
    with pytest.raises(WorkerFailure, match="requires"):
        resolve_motion_length({})
    with pytest.raises(WorkerFailure, match="multiple of 4"):
        resolve_motion_length({"motion_length_frames": 82})
    with pytest.raises(WorkerFailure, match="either"):
        resolve_motion_length({"motion_length_frames": 80, "seconds": 4.0})


def test_backend_rejects_unknown_strategy_and_bad_native_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = DiscordBackend(
        ArtifactRoots(tmp_path, tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cuda_cpu_offload")
    with pytest.raises(WorkerFailure, match="only cuda_full and whole-model cpu"):
        backend.load()
    path = tmp_path / "bad.npy"
    np.save(path, np.zeros(264, dtype=np.float32), allow_pickle=False)
    with pytest.raises(WorkerFailure, match="263"):
        backend._vector(path, label="mean")


def test_manifest_worker_and_registry_contracts_are_identical(tmp_path: Path) -> None:
    plugin = DiscordHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )
    assert plugin.metadata().output_representation_id == "humanml3d.vector263.v1"
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    embedded = tuple(
        RuntimeSpec.model_validate(item) for item in manifest["runtime_variants"]
    )
    registered = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPOSITORY_ROOT / "registries" / "runtimes" / name).read_text(
                    encoding="utf-8"
                )
            )
        )
        for name in ("discord-humanml3d-cu128.yaml", "discord-humanml3d-cpu.yaml")
    )
    assert embedded == registered
    manual = {
        item["id"]: item for item in manifest["artifacts"] if item["kind"] == "manual"
    }
    assert manual["discord-momask-rf-decoder"]["expected_files"] == [
        "DisCoRD_Momask_RFDecoder_best.pth"
    ]
    assert manual["momask-humanml3d-models"]["expected_files"] == [
        "humanml3d_models.zip"
    ]
    assert "**" not in json.dumps(manual)
    assert manifest["model"]["status"] == "integrated_experimental"
    assert (
        "native_artifact_validation"
        in manifest["production_acceptance"]["required_stages"]
    )


def test_worker_publishes_real_backend_float32_native_artifact(tmp_path: Path) -> None:
    plugin = DiscordHumanML3DPlugin(
        ArtifactRoots(tmp_path, tmp_path, tmp_path, tmp_path), tmp_path / "cache"
    )

    class Backend:
        loaded = True
        device_facts = {"device": "cpu", "torch_version": "test"}

        @staticmethod
        def generate(*args: object, **kwargs: object) -> GenerationOutput:
            return GenerationOutput(
                np.ones((80, 263), dtype=np.float32), generated_frames=80
            )

    plugin._backend = Backend()  # type: ignore[assignment]
    request = WorkerInferRequest(
        job_id="job-discord",
        request=JobRequest(
            model_id="discord-humanml3d",
            task="text_to_motion",
            input={"prompt": "A person walks forward."},
            parameters={"motion_length_frames": 80, "seed": 1, "fps": 20.0},
        ),
        staging_locator="native",
    )
    result = plugin.infer(request, WorkerContext("job-discord", tmp_path, Event()))
    array = np.load(tmp_path / "source_humanml3d_vector263.npy", allow_pickle=False)
    assert array.shape == (80, 263)
    assert array.dtype == np.float32
    assert result.native.frame_count == 80
    assert result.native.artifacts[0].shape == (80, 263)
