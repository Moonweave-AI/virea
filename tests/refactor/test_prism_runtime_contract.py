from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from virea_api.service import ControlPlane
from virea_compat import prism_smplh_body22_axis_angle69_to_motion_ir
from virea_contracts.installation import InstallationState
from virea_contracts.runtime import MemoryStrategy, RuntimeSpec
from virea_core import VireaPaths
from virea_model_pool import ModelCatalog
from virea_model_sdk import WorkerFailure
from virea_retarget import retarget_motion_ir
from virea_vrm import export_vrma

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = REPO_ROOT / "plugins" / "models" / "prism-tp2m-1-4b"
RUNTIME_ROOT = MODEL_ROOT / "runtime"
sys.path.insert(0, str(RUNTIME_ROOT / "src"))

from virea_prism.artifacts import (  # noqa: E402
    MODEL_REVISION,
    SOURCE_REVISION,
    STATS_REVISION,
    TOKENIZER_REVISION,
    PrismArtifactRoots,
)
from virea_prism.backend import (  # noqa: E402
    normalize_public_output,
    portable_memory_observation,
)


def _captured_payload() -> dict:
    evidence = json.loads(
        (MODEL_ROOT / "evidence" / "wsl2-real-inference-2026-08-19.json").read_text(
            encoding="utf-8"
        )
    )
    return evidence["captured_public_payload_excerpt"]


def test_captured_real_public_payload_is_packed_as_69d_not_internal_138d() -> None:
    payload = _captured_payload()
    generation = normalize_public_output(
        {
            "transl": np.asarray(payload["transl"], dtype=np.float32),
            "global_orient": np.asarray(payload["global_orient"], dtype=np.float32),
            "body_pose": np.asarray(payload["body_pose"], dtype=np.float32),
        }
    )

    assert generation.carrier.shape == (2, 69)
    assert generation.carrier.dtype == np.dtype("float32")
    np.testing.assert_array_equal(generation.carrier[:, :3], payload["transl"])
    np.testing.assert_array_equal(generation.carrier[:, 3:6], payload["global_orient"])
    np.testing.assert_array_equal(generation.carrier[:, 6:69], payload["body_pose"])
    assert np.isfinite(generation.carrier).all()


def test_captured_prism_result_reaches_motion_ir_retarget_and_vrma(
    tmp_path: Path,
) -> None:
    payload = _captured_payload()
    carrier = np.concatenate(
        (
            np.asarray(payload["transl"], dtype=np.float32),
            np.asarray(payload["global_orient"], dtype=np.float32),
            np.asarray(payload["body_pose"], dtype=np.float32),
        ),
        axis=1,
    )
    adapted = prism_smplh_body22_axis_angle69_to_motion_ir(
        carrier, motion_id="captured-real-prism-contract"
    )
    retargeted = retarget_motion_ir(adapted.motion_ir)
    assert retargeted.quality["finite"] is True
    assert len(retargeted.actors) == 1
    assert retargeted.actors[0].canonical211.shape == (2, 211)

    output = export_vrma(
        retargeted.actors[0], tmp_path / "captured-prism.vrma", fps=30.0
    )
    binary = output.read_bytes()
    assert binary[:4] == b"glTF"
    assert len(binary) > 1000


def test_manifest_registries_and_runtime_freeze_shared_external_assets() -> None:
    manifest = yaml.safe_load(
        (MODEL_ROOT / "manifest.yaml").read_text(encoding="utf-8")
    )
    registered = tuple(
        RuntimeSpec.model_validate(
            yaml.safe_load(
                (REPO_ROOT / "registries" / "runtimes" / filename).read_text(
                    encoding="utf-8"
                )
            )
        )
        for filename in (
            "prism-tp2m-1-4b-cu128-component-split.yaml",
            "prism-tp2m-1-4b-cpu.yaml",
        )
    )
    embedded = tuple(
        RuntimeSpec.model_validate(runtime) for runtime in manifest["runtime_variants"]
    )

    assert manifest["model"]["status"] == "integrated_experimental"
    assert manifest["model"]["adapter_family"] == ("prism-smplh-body22-axis-angle69")
    assert manifest["output"]["representation_id"] == (
        "prism.smplh_body22.axis_angle69.v1"
    )
    assert embedded == registered
    cuda, cpu = registered
    assert cuda.resource_profiles[0].strategy is MemoryStrategy.CUDA_COMPONENT_SPLIT
    assert cuda.resource_profiles[0].min_free_vram_gib == 12.0
    assert cuda.resource_profiles[0].min_free_ram_gib == 28.0
    assert cuda.platforms == ("win-64", "linux-64")
    assert cpu.resource_profiles[0].strategy is MemoryStrategy.CPU
    assert cpu.resource_profiles[0].min_free_ram_gib == 96.0
    assert set(cpu.platforms) == {"win-64", "linux-64", "osx-arm64", "osx-64"}
    assert manifest["resources"]["technical_availability"] == (
        "historical_runtime_0_1_2_acceptance_new_runtime_baselines_require_reacceptance"
    )
    assert manifest["resources"]["integration_state"] == "integrated_experimental"
    assert manifest["resources"]["distribution_status"] == "external_assets_only"
    assert manifest["resources"]["license_status"] == "license_review_required"
    assert manifest["resources"]["ram_admission"] == {
        "admission_min_total_ram_gib": 28.0,
        "worker_preload_min_available_ram_gib": 15.0,
        "post_load_min_available_ram_gib": 2.0,
        "calibration_basis": "25.075_GiB_UMT5_weight_file_plus_successful_legacy_run_inside_31.063_GiB_WSL",
        "managed_runtime_peak_measurement": "required_in_fresh_product_e2e",
        "cpu_admission_min_total_ram_gib": 96.0,
        "cpu_worker_preload_min_available_ram_gib": 96.0,
        "cpu_post_load_min_available_ram_gib": 8.0,
        "cpu_floor_status": "conservative_fail_closed_unmeasured",
    }
    assert manifest["licenses"]["redistribution_allowed"] is False

    artifacts = {item["id"]: item for item in manifest["artifacts"]}
    assert artifacts["prism-source"]["revision"] == SOURCE_REVISION
    assert artifacts["prism-tp2m-1-4b-official-hf"]["revision"] == MODEL_REVISION
    assert artifacts["prism-umt5-xxl-tokenizer"]["revision"] == TOKENIZER_REVISION
    assert artifacts["prism-motionhub-smplh-stats"]["revision"] == STATS_REVISION
    assert manifest["resources"]["smpl_geometry"] == {
        "required_for_generation": False,
        "empty_directory_is_valid_asset": False,
    }
    assert cuda.availability == (
        "windows_and_linux_cuda_lock_resolution_verified_historical_wsl_runtime_0_1_2_evidence_requires_reacceptance"
    )
    assert cpu.availability == (
        "cpu_contract_and_lock_baseline_real_inference_unverified"
    )


def test_runtime_observes_real_cross_platform_system_and_worker_memory() -> None:
    observed = portable_memory_observation()
    assert observed["system_ram_total_bytes"] > 0
    assert (
        0 < observed["system_ram_available_bytes"] <= observed["system_ram_total_bytes"]
    )
    assert observed["process_rss_bytes"] > 0
    assert observed["process_peak_rss_bytes"] >= observed["process_rss_bytes"]


def test_migration_evidence_records_zero_copy_wsl_artifact_root_contract() -> None:
    evidence = json.loads(
        (MODEL_ROOT / "evidence" / "wsl2-real-inference-2026-08-19.json").read_text(
            encoding="utf-8"
        )
    )
    external = evidence["existing_external_artifact_roots"]
    assert external["execution_domain"] == "${PRISM_EXECUTION_DOMAIN}"
    assert external["execution_domain_kind"] == "wsl"
    assert external["recorded_distribution"] == "Ubuntu-24.04"
    assert external["injection_contract"] == "VIREA_ARTIFACT_ROOTS_JSON"
    assert external["copy_large_assets_into_repository"] is False
    roots = external["roots"]
    assert set(roots) == {
        "prism-source",
        "prism-tp2m-1-4b-official-hf",
        "prism-umt5-xxl-tokenizer",
        "prism-motionhub-smplh-stats",
    }
    assert roots["prism-tp2m-1-4b-official-hf"]["relative_to_migration_root"] == (
        "runtime/models/prism_1.4b"
    )
    assert roots["prism-motionhub-smplh-stats"]["relative_to_migration_root"] == (
        "runtime/aux/motionhub/statistics"
    )
    assert all(
        root["root_reference"].startswith("${PRISM_MIGRATION_ROOT}/")
        for root in roots.values()
    )
    serialized = json.dumps(evidence)
    assert "/home/" not in serialized
    assert "\\\\wsl.localhost\\" not in serialized
    assert evidence["claims"]["managed_external_root_staging"] == (
        "passed_reference_only_in_recorded_WSL2_execution_domain"
    )
    calibration = evidence["ram_admission_calibration"]
    assert calibration["preflight_min_free_ram_gib"] == 28.0
    assert calibration["post_load_min_available_ram_gib"] == 2.0
    assert calibration["umt5_weight_file_bytes"] == 26_924_267_472
    assert "not recorded" in calibration["limitation"]


def test_present_wsl_migration_roots_stage_reference_only_installation(
    tmp_path,
) -> None:
    migration_root = Path("/home/example/virea-prism-runtime")
    if not migration_root.is_dir():
        pytest.skip("the recorded PRISM WSL migration source is not on this machine")
    manifest = ModelCatalog.load(REPO_ROOT / "plugins" / "models").get(
        "prism-tp2m-1-4b"
    )
    roots = {
        "prism-source": migration_root / "vendor" / "prism",
        "prism-tp2m-1-4b-official-hf": (
            migration_root / "runtime" / "models" / "prism_1.4b"
        ),
        "prism-umt5-xxl-tokenizer": (
            migration_root / "runtime" / "models" / "prism_1.4b" / "tokenizer"
        ),
        "prism-motionhub-smplh-stats": (
            migration_root / "runtime" / "aux" / "motionhub" / "statistics"
        ),
    }
    revisions: dict[str, str] = {}
    for source in manifest.artifacts:
        assert source.revision is not None
        revisions[source.id] = source.revision
    paths = VireaPaths(tmp_path / "virea-home")
    control = ControlPlane(paths=paths, plugin_root=REPO_ROOT / "plugins" / "models")
    try:
        compatibility = control.runtime_compatibility(manifest.model.id)
        assert compatibility["can_build"] is True
        assert compatibility["selected_resource_profile"] == "cuda-component-split"
        assert compatibility["selected_memory_strategy"] == "cuda_component_split"
        assert compatibility["resource_profile_diagnostics"] == [
            {
                "profile_id": "cuda-component-split",
                "strategy": "cuda_component_split",
                "status": "admitted",
                "reasons": [],
            }
        ]
        assert compatibility["resource_observations"]["free_ram_bytes"] >= int(
            28 * 1024**3
        )
        normalized, domain_id, domain_paths = control.prepare_external_artifact_roots(
            manifest.model.id,
            roots,
            revisions,
        )
        assert domain_id == "wsl:Ubuntu-24.04"
        assert domain_paths == {
            key: str(value.resolve()) for key, value in roots.items()
        }
        outcome = control.model_pool.stage_artifacts(
            manifest.model.id,
            accepted_license=True,
            external_artifact_roots=normalized,
            external_artifact_revisions=revisions,
            external_execution_domain=domain_id,
            external_domain_paths=domain_paths,
        )

        assert outcome.state is InstallationState.BUILDING_RUNTIME
        installation = paths.resolve_locator(outcome.locator or "")
        assert all(
            (installation / "artifacts" / artifact_id).resolve(strict=True)
            == source_root.resolve(strict=True)
            for artifact_id, source_root in roots.items()
        )
        reference = json.loads(
            (installation / "external-artifact-roots.json").read_text(encoding="utf-8")
        )
        assert reference["copy_mode"] == "reference_only"
        assert reference["execution_domain"] == "wsl:Ubuntu-24.04"
        assert {entry["id"] for entry in reference["artifacts"]} == set(roots)
    finally:
        control.close()


def test_runtime_document_and_packaging_exclude_generated_python_cache() -> None:
    readme = (RUNTIME_ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("---\n")
    assert "canonical: plugins/models/prism-tp2m-1-4b/runtime/README.md" in readme
    source_manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include plugins/models/prism-tp2m-1-4b/runtime/src *.py" in (
        source_manifest
    )
    assert "global-exclude __pycache__/*" in source_manifest
    assert "global-exclude *.py[cod]" in source_manifest
    setup_source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    assert 'name in {"__pycache__", ".pytest_cache", ".ruff_cache"}' in setup_source
    assert 'name.endswith((".pyc", ".pyo", ".egg-info"))' in setup_source


def test_worker_loader_is_local_only_and_has_no_download_entrypoint() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            RUNTIME_ROOT / "src" / "virea_prism" / "backend.py",
            RUNTIME_ROOT / "src" / "virea_prism" / "offline_loader.py",
            RUNTIME_ROOT / "src" / "virea_prism" / "worker.py",
        )
    )
    assert "hf_hub_download" not in source
    assert "snapshot_download" not in source
    assert "local_files_only=True" in source
    assert 'os.environ[name] = "1"' in source
    assert "smpl_models/smplx" not in source


def test_worker_artifact_root_map_rejects_non_manifest_ids() -> None:
    values = {
        "prism-source": "/artifacts/source",
        "prism-tp2m-1-4b-official-hf": "/artifacts/model",
        "prism-umt5-xxl-tokenizer": "/artifacts/tokenizer",
        "prism-motionhub-smplh-stats": "/artifacts/statistics",
        "not-in-the-manifest": "/artifacts/extra",
    }
    with pytest.raises(WorkerFailure, match="unexpected: not-in-the-manifest"):
        PrismArtifactRoots.from_json(json.dumps(values))
