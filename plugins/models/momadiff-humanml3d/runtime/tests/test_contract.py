from __future__ import annotations

import json
from pathlib import Path

import pytest
from virea_model_sdk import WorkerFailure
from virea_momadiff.backend import (
    CHECKPOINT_REVISION,
    CLIP_REVISION,
    SOURCE_REVISION,
    MoMADiffPaths,
)
from virea_momadiff.worker import (
    CHECKPOINT_ARTIFACT_ID,
    CLIP_ARTIFACT_ID,
    MODEL_ID,
    REPRESENTATION_ID,
    RUNTIME_ID,
    SKELETON_ID,
    SOURCE_ARTIFACT_ID,
    MoMADiffHumanML3DPlugin,
    _resolve_motion_length_frames,
    artifact_paths_from_json,
)


def test_worker_metadata_exposes_only_implemented_memory_strategies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIREA_MEMORY_STRATEGY", "cpu")
    plugin = MoMADiffHumanML3DPlugin(
        MoMADiffPaths(
            source_root=tmp_path / "source",
            checkpoint_root=tmp_path / "checkpoints",
            clip_root=tmp_path / "clip",
        )
    )

    metadata = plugin.metadata()

    assert metadata.model_id == MODEL_ID == "momadiff-humanml3d"
    assert metadata.tasks == ("text_to_motion",)
    assert metadata.output_representation_id == REPRESENTATION_ID
    assert metadata.output_skeleton_id == SKELETON_ID
    assert metadata.resources["memory_strategies"] == ["cuda_full", "cpu"]
    assert metadata.resources["active_memory_strategy"] == "cpu"
    assert metadata.resources["source_revision"] == SOURCE_REVISION
    assert metadata.resources["checkpoint_revision"] == CHECKPOINT_REVISION
    assert metadata.resources["clip_revision"] == CLIP_REVISION
    assert RUNTIME_ID == "momadiff-humanml3d-cu128"


def test_artifact_root_map_uses_stable_model_specific_ids(tmp_path: Path) -> None:
    roots = {
        SOURCE_ARTIFACT_ID: str(tmp_path / "official-source"),
        CHECKPOINT_ARTIFACT_ID: str(tmp_path / "humanml-checkpoints"),
        CLIP_ARTIFACT_ID: str(tmp_path / "clip-vit-b-32"),
    }

    paths = artifact_paths_from_json(json.dumps(roots))

    assert paths.source_root == Path(roots[SOURCE_ARTIFACT_ID])
    assert paths.checkpoint_root == Path(roots[CHECKPOINT_ARTIFACT_ID])
    assert paths.clip_root == Path(roots[CLIP_ARTIFACT_ID])


def test_artifact_root_map_fails_closed_when_clip_is_missing(tmp_path: Path) -> None:
    roots = {
        SOURCE_ARTIFACT_ID: str(tmp_path / "official-source"),
        CHECKPOINT_ARTIFACT_ID: str(tmp_path / "humanml-checkpoints"),
    }

    with pytest.raises(WorkerFailure, match=CLIP_ARTIFACT_ID) as captured:
        artifact_paths_from_json(json.dumps(roots))

    assert captured.value.code == "MODEL_SNAPSHOT_INCOMPLETE"


def test_explicit_seconds_resolve_to_exact_token_aligned_frames() -> None:
    assert _resolve_motion_length_frames(input_frames=None, seconds=4.0, fps=20.0) == 80
    assert _resolve_motion_length_frames(input_frames=80, seconds=4.0, fps=20.0) == 80


@pytest.mark.parametrize(
    ("input_frames", "seconds", "message"),
    [
        (84, 4.0, "disagree"),
        (None, 4.05, "divisible by four"),
        (None, 4.025, "integer frame count"),
    ],
)
def test_explicit_duration_fails_closed_instead_of_changing_length(
    input_frames: int | None,
    seconds: float,
    message: str,
) -> None:
    with pytest.raises(WorkerFailure, match=message) as captured:
        _resolve_motion_length_frames(
            input_frames=input_frames,
            seconds=seconds,
            fps=20.0,
        )

    assert captured.value.code == "INVALID_REQUEST"
