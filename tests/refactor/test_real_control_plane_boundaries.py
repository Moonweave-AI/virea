"""Contract-only tests for real Worker artifacts; these are not model evidence."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from virea_api.service import REAL_ADAPTER_FAMILIES, ControlPlane
from virea_contracts import (
    ArtifactRef,
    ModelIdentity,
    ModelResult,
    NativeMotionDescriptor,
)
from virea_core import VireaPaths

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"


def test_worker_environment_exposes_all_installed_artifact_roots(tmp_path) -> None:
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        first = tmp_path / "artifacts" / "weights"
        second = tmp_path / "artifacts" / "source"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        with control._lock:
            control._model_root_overrides["job-generic"] = {
                "weights": first,
                "upstream-source": second,
            }

        environment = control._worker_environment(
            job_id="job-generic",
            model_id="generic-real-model",
            adapter_family="generic-real-adapter",
        )

        assert json.loads(environment["VIREA_ARTIFACT_ROOTS_JSON"]) == {
            "upstream-source": str(second.resolve()),
            "weights": str(first.resolve()),
        }
        assert environment["HF_HUB_OFFLINE"] == "1"
        assert environment["TRANSFORMERS_OFFLINE"] == "1"
        assert "VIREA_MODEL_ROOT" not in environment
    finally:
        control.close()


def test_verified_installation_roots_are_reused_without_a_second_hash_pass(
    tmp_path, monkeypatch
) -> None:
    paths = VireaPaths(tmp_path / "home")
    control = ControlPlane(paths=paths, plugin_root=PLUGIN_ROOT)
    manifest = control.catalog.get("flood-diffusion-tiny")
    snapshot = paths.model_store / "snapshots" / "verified-installation"
    for source in manifest.artifacts:
        (snapshot / "artifacts" / source.id).mkdir(parents=True)
    calls = 0

    def verified_report(model_id: str, *, cancel_event=None) -> dict:
        nonlocal calls
        calls += 1
        assert model_id == manifest.model.id
        assert cancel_event is None
        return {
            "model_id": model_id,
            "installation_id": "verified-installation",
            "state": "READY",
            "locator": paths.relative_locator(snapshot),
            "installed": True,
            "ready": True,
            "diagnostics": [],
        }

    monkeypatch.setattr(control.model_pool, "verify_latest", verified_report)
    try:
        verified = control._verify_installed_model(manifest.model.id)
        environment = control._worker_environment(
            job_id="job-verified",
            model_id=manifest.model.id,
            adapter_family=manifest.model.adapter_family,
            artifact_roots=verified.artifact_roots,
        )

        assert calls == 1
        assert json.loads(environment["VIREA_ARTIFACT_ROOTS_JSON"]) == {
            source.id: str((snapshot / "artifacts" / source.id).resolve())
            for source in manifest.artifacts
        }
    finally:
        control.close()


def _result(job_id: str, artifact: ArtifactRef, *, frames: int = 2) -> ModelResult:
    return ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id="flood-diffusion-tiny",
            plugin_version="0.1.0",
            upstream_repository="AlayaLab/FloodDiffusionTiny",
            upstream_revision="e86746efa2f16b94a1bb08550e3d8d4a32163f14",
            runtime_id="flood-diffusion-tiny-cu128",
        ),
        task="text_to_motion",
        native=NativeMotionDescriptor(
            representation_id="humanml3d.vector263.v1",
            skeleton_id="humanml3d.body22.v1",
            fps=20.0,
            frame_count=frames,
            coordinate_system="humanml3d.right_handed_y_up_z_forward",
            units="meters",
            root_translation_semantics="relative",
            root_rotation_semantics="relative",
            artifacts=(artifact,),
        ),
    )


def _acmdm_result(
    job_id: str,
    artifacts: tuple[ArtifactRef, ...],
    *,
    frames: int,
) -> ModelResult:
    return ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id="acmdm-humanml3d",
            plugin_version="0.1.0",
            upstream_repository="https://github.com/neu-vi/ACMDM",
            upstream_revision="25ed4ba22fb54d9c3e99361609ee344e7c940303",
            runtime_id="acmdm-humanml3d-cu128",
        ),
        task="text_to_motion",
        native=NativeMotionDescriptor(
            representation_id="humanml3d.body22.positions.v1",
            skeleton_id="humanml3d.body22.v1",
            fps=20.0,
            frame_count=frames,
            coordinate_system="humanml3d.right_handed_y_up_z_forward_global",
            units="meters",
            root_translation_semantics="absolute_xyz_is_joint_0_in_every_frame",
            root_rotation_semantics="not_provided_absolute_joint_positions_only",
            artifacts=artifacts,
        ),
    )


def _prism_result(
    job_id: str,
    artifacts: tuple[ArtifactRef, ...],
    *,
    frames: int,
) -> ModelResult:
    return ModelResult(
        job_id=job_id,
        model=ModelIdentity(
            id="prism-tp2m-1-4b",
            plugin_version="0.1.0",
            upstream_repository="https://github.com/ZeyuLing/PRISM",
            upstream_revision="3c58bc5d946f0827171a3712ed36314f4b1a5186",
            runtime_id="prism-tp2m-1-4b-cu128-component-split",
        ),
        task="text_to_motion",
        native=NativeMotionDescriptor(
            representation_id="prism.smplh_body22.axis_angle69.v1",
            skeleton_id="smplh.body22.v1",
            fps=30.0,
            frame_count=frames,
            coordinate_system="prism.smplh.right_handed_y_up_z_forward",
            units="meters",
            root_translation_semantics="public_pipeline_postprocessed_absolute_xyz",
            root_rotation_semantics=(
                "explicit_global_orientation_axis_angle_local_to_world"
            ),
            artifacts=artifacts,
        ),
    )


def test_real_artifact_must_resolve_inside_current_job_staging(tmp_path) -> None:
    job_root = tmp_path / "jobs" / "job-a"
    staging = job_root / "staging"
    staging.mkdir(parents=True)
    valid = staging / "motion.npy"
    np.save(valid, np.zeros((2, 263), dtype=np.float32), allow_pickle=False)
    reference = ArtifactRef(
        name="source_humanml3d_263d",
        media_type="application/x-npy",
        uri="virea-job://job-a/staging/motion.npy",
        byte_length=valid.stat().st_size,
        dtype="float32",
        shape=(2, 263),
    )
    assert (
        ControlPlane._artifact_path(
            job_root=job_root, job_id="job-a", artifact=reference
        )
        == valid.resolve()
    )
    escaped = reference.model_copy(
        update={"uri": "virea-job://job-a/staging/../outside.npy"}
    )
    with pytest.raises(ValueError, match="escapes"):
        ControlPlane._artifact_path(job_root=job_root, job_id="job-a", artifact=escaped)
    wrong_job = reference.model_copy(
        update={"uri": "virea-job://job-b/staging/motion.npy"}
    )
    with pytest.raises(ValueError, match="current virea-job"):
        ControlPlane._artifact_path(
            job_root=job_root, job_id="job-a", artifact=wrong_job
        )


def test_humanml3d_artifact_contract_rejects_nonfinite_values(tmp_path) -> None:
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-real-contract"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        native_path = staging / "source_humanml3d_263d.npy"
        values = np.zeros((2, 263), dtype=np.float32)
        values[1, 9] = np.nan
        np.save(native_path, values, allow_pickle=False)
        artifact = ArtifactRef(
            name="source_humanml3d_263d",
            media_type="application/x-npy",
            uri=f"virea-job://{job_id}/staging/{native_path.name}",
            byte_length=native_path.stat().st_size,
            dtype="float32",
            shape=(2, 263),
        )
        with pytest.raises(ValueError, match="NaN or infinity"):
            control._load_native_artifact(
                job_root=job_root,
                job_id=job_id,
                model_result=_result(job_id, artifact),
                adapter_family="humanml3d-motion263-body22",
            )
    finally:
        control.close()


def test_humanml3d_contract_accepts_model_specific_native_artifact_name(
    tmp_path,
) -> None:
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-momadiff-contract"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        native_path = staging / "native-momadiff.npy"
        values = np.zeros((4, 263), dtype=np.float32)
        np.save(native_path, values, allow_pickle=False)
        artifact = ArtifactRef(
            name="native_momadiff_humanml3d_vector263",
            media_type="application/x-npy",
            uri=f"virea-job://{job_id}/staging/{native_path.name}",
            byte_length=native_path.stat().st_size,
            dtype="float32",
            shape=values.shape,
        )

        loaded_path, loaded = control._load_native_artifact(
            job_root=job_root,
            job_id=job_id,
            model_result=_result(job_id, artifact, frames=4),
            adapter_family="humanml3d-motion263-body22",
        )

        assert loaded_path == native_path.resolve()
        np.testing.assert_array_equal(loaded, values)
    finally:
        control.close()


def test_acmdm_contract_strictly_loads_and_adapts_absolute_body22_positions(
    tmp_path,
) -> None:
    assert "joint-positions-body22" in REAL_ADAPTER_FAMILIES
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-acmdm-contract"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        native_path = staging / "source_acmdm_absolute_positions22.npy"
        values = np.zeros((4, 22, 3), dtype=np.float32)
        values[:, 0, 1] = 1.0
        np.save(native_path, values, allow_pickle=False)
        artifact = ArtifactRef(
            name="source_acmdm_absolute_positions22",
            media_type="application/x-npy",
            uri=f"virea-job://{job_id}/staging/{native_path.name}",
            byte_length=native_path.stat().st_size,
            dtype="float32",
            shape=values.shape,
        )
        result = _acmdm_result(job_id, (artifact,), frames=4)

        loaded_path, loaded = control._load_native_artifact(
            job_root=job_root,
            job_id=job_id,
            model_result=result,
            adapter_family="joint-positions-body22",
        )
        motion = control._adapt_native_motion(
            adapter_family="joint-positions-body22",
            native=loaded,
            model_result=result,
        )

        assert loaded_path == native_path.resolve()
        np.testing.assert_array_equal(loaded, values)
        assert motion.frame_count == 4
        assert motion.provenance["adapter"]["source_model_id"] == ("acmdm-humanml3d")
        assert motion.provenance["adapter"]["upstream_revision"] == (
            "25ed4ba22fb54d9c3e99361609ee344e7c940303"
        )
        assert motion.provenance["adapter"]["source_representation_id"] == (
            "humanml3d.body22.positions.v1"
        )
        assert motion.provenance["adapter"]["output_skeleton_id"] == (
            "humanml3d.body22.v1"
        )

        with pytest.raises(ValueError, match="exactly one float32 NPY"):
            control._load_native_artifact(
                job_root=job_root,
                job_id=job_id,
                model_result=_acmdm_result(
                    job_id,
                    (artifact, artifact.model_copy(update={"name": "duplicate"})),
                    frames=4,
                ),
                adapter_family="joint-positions-body22",
            )

        wrong_dtype_path = staging / "source_acmdm_wrong_dtype.npy"
        np.save(
            wrong_dtype_path,
            np.zeros((4, 22, 3), dtype=np.float64),
            allow_pickle=False,
        )
        wrong_dtype = artifact.model_copy(
            update={
                "uri": f"virea-job://{job_id}/staging/{wrong_dtype_path.name}",
                "byte_length": wrong_dtype_path.stat().st_size,
            }
        )
        with pytest.raises(ValueError, match="dtype must be float32"):
            control._load_native_artifact(
                job_root=job_root,
                job_id=job_id,
                model_result=_acmdm_result(job_id, (wrong_dtype,), frames=4),
                adapter_family="joint-positions-body22",
            )
    finally:
        control.close()


def test_prism_captured_public_payload_crosses_model_result_and_motion_ir_boundary(
    tmp_path,
) -> None:
    assert "prism-smplh-body22-axis-angle69" in REAL_ADAPTER_FAMILIES
    evidence = json.loads(
        (
            PLUGIN_ROOT
            / "prism-tp2m-1-4b"
            / "evidence"
            / "wsl2-real-inference-2026-08-19.json"
        ).read_text(encoding="utf-8")
    )
    captured = evidence["captured_public_payload_excerpt"]
    transl = np.asarray(captured["transl"], dtype=np.float32)
    global_orient = np.asarray(captured["global_orient"], dtype=np.float32)
    body_pose = np.asarray(captured["body_pose"], dtype=np.float32)
    carrier = np.concatenate((transl, global_orient, body_pose), axis=1)
    assert carrier.shape == (2, 69)

    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-prism-captured-contract"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        native_path = staging / "source_prism_smplh_body22_axis_angle69.npy"
        raw_path = staging / "source_prism_smplx_raw.npz"
        metadata_path = staging / "generation_metadata.json"
        np.save(native_path, carrier, allow_pickle=False)
        np.savez_compressed(
            raw_path,
            transl=transl,
            global_orient=global_orient,
            body_pose=body_pose,
            fps=np.asarray([30.0], dtype=np.float32),
        )
        metadata_path.write_text(
            json.dumps(
                {
                    "source_job_id": captured["source_job_id"],
                    "payload": "captured_public_prism_excerpt",
                }
            ),
            encoding="utf-8",
        )
        artifacts = (
            ArtifactRef(
                name="source_prism_smplh_body22_axis_angle69",
                media_type="application/x-npy",
                uri=f"virea-job://{job_id}/staging/{native_path.name}",
                byte_length=native_path.stat().st_size,
                dtype="float32",
                shape=carrier.shape,
            ),
            ArtifactRef(
                name="source_prism_smplx_raw",
                media_type="application/x-npz",
                uri=f"virea-job://{job_id}/staging/{raw_path.name}",
                byte_length=raw_path.stat().st_size,
            ),
            ArtifactRef(
                name="generation_metadata",
                media_type="application/json",
                uri=f"virea-job://{job_id}/staging/{metadata_path.name}",
                byte_length=metadata_path.stat().st_size,
            ),
        )
        result = _prism_result(job_id, artifacts, frames=2)

        loaded_path, loaded = control._load_native_artifact(
            job_root=job_root,
            job_id=job_id,
            model_result=result,
            adapter_family="prism-smplh-body22-axis-angle69",
        )
        motion = control._adapt_native_motion(
            adapter_family="prism-smplh-body22-axis-angle69",
            native=loaded,
            model_result=result,
        )

        assert loaded_path == native_path.resolve()
        np.testing.assert_array_equal(loaded, carrier)
        assert motion.frame_count == 2
        assert motion.fps == 30.0
        assert motion.provenance["adapter"]["source_model_id"] == ("prism-tp2m-1-4b")
        assert motion.provenance["adapter"]["upstream_revision"] == (
            "3c58bc5d946f0827171a3712ed36314f4b1a5186"
        )
        assert motion.provenance["adapter"]["source_representation_id"] == (
            "prism.smplh_body22.axis_angle69.v1"
        )
    finally:
        control.close()


def test_mardm_contract_loads_motion_and_checkpoint_statistics(tmp_path) -> None:
    control = ControlPlane(paths=VireaPaths(tmp_path / "home"), plugin_root=PLUGIN_ROOT)
    try:
        job_id = "job-mardm-contract"
        job_root = control.paths.job_directory(job_id)
        staging = job_root / "staging"
        staging.mkdir(parents=True)
        arrays = {
            "source_mardm_ric67_normalized": np.zeros((2, 67), dtype=np.float32),
            "mardm_t2m_eval_mean": np.zeros(67, dtype=np.float32),
            "mardm_t2m_eval_std": np.ones(67, dtype=np.float32),
        }
        artifacts = []
        for name, values in arrays.items():
            path = staging / f"{name}.npy"
            np.save(path, values, allow_pickle=False)
            artifacts.append(
                ArtifactRef(
                    name=name,
                    media_type="application/x-npy",
                    uri=f"virea-job://{job_id}/staging/{path.name}",
                    byte_length=path.stat().st_size,
                    dtype="float32",
                    shape=values.shape,
                )
            )
        result = ModelResult(
            job_id=job_id,
            model=ModelIdentity(
                id="mardm-humanml3d",
                plugin_version="0.1.0",
                upstream_repository="https://github.com/neu-vi/MARDM",
                upstream_revision="5e32b69723376028f38125ccee33011549cd341d",
                runtime_id="mardm-humanml3d-cu128",
            ),
            task="text_to_motion",
            native=NativeMotionDescriptor(
                representation_id="mardm.humanml3d.ric67.v1",
                skeleton_id="humanml3d.body22.v1",
                fps=20.0,
                frame_count=2,
                coordinate_system="humanml3d.right_handed_y_up_z_forward",
                units="checkpoint_normalized",
                root_translation_semantics="official_ric",
                root_rotation_semantics="official_ric",
                artifacts=tuple(artifacts),
            ),
        )

        primary, loaded = control._load_native_artifact(
            job_root=job_root,
            job_id=job_id,
            model_result=result,
            adapter_family="mardm-ric67-body22",
        )
        motion = control._adapt_native_motion(
            adapter_family="mardm-ric67-body22",
            native=loaded,
            model_result=result,
        )

        assert primary.name == "source_mardm_ric67_normalized.npy"
        assert set(loaded) == set(arrays)
        assert motion.frame_count == 2
        assert motion.provenance["adapter"]["checkpoint_id"] == (
            "mardm-source-5e32b697:t2m-eval-stats"
        )
        assert motion.provenance["adapter"]["source_model_id"] == "mardm-humanml3d"
        assert motion.provenance["adapter"]["upstream_revision"] == (
            "5e32b69723376028f38125ccee33011549cd341d"
        )
    finally:
        control.close()
