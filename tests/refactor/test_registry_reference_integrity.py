"""Cross-registry reference integrity for model and adapter manifests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import yaml
from virea_contracts.model import ModelSupportStatus
from virea_contracts.runtime import RuntimeSpec
from virea_contracts.runtime_identity import RUNTIME_CORE_EPOCH
from virea_model_pool import ModelCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRIES = REPO_ROOT / "registries"
PLUGIN_ROOT = REPO_ROOT / "plugins" / "models"
ADAPTER_ROOT = REPO_ROOT / "plugins" / "adapters"


def _registry_ids(directory: Path) -> dict[str, Path]:
    by_id: dict[str, Path] = {}
    for path in sorted(directory.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        identifier = payload.get("id") if isinstance(payload, dict) else None
        assert isinstance(identifier, str) and identifier, f"{path} has no registry id"
        assert identifier not in by_id, (
            f"duplicate registry id {identifier!r}: {by_id.get(identifier)} and {path}"
        )
        by_id[identifier] = path
    assert by_id, f"no registry entries found under {directory}"
    return by_id


def _yaml_by_id(
    directory: Path, pattern: str = "*.yaml"
) -> dict[str, tuple[Path, dict[str, Any]]]:
    by_id: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(directory.glob(pattern)):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict), f"{path} must contain a YAML mapping"
        identifier = payload.get("id")
        assert isinstance(identifier, str) and identifier, f"{path} has no id"
        assert identifier not in by_id, f"duplicate id {identifier!r} under {directory}"
        by_id[identifier] = (path, payload)
    assert by_id, f"no YAML declarations found under {directory}"
    return by_id


def _named_values(
    value: Any, key_name: str, path: str = "$"
) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key == key_name:
                yield child_path, child
            yield from _named_values(child, key_name, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _named_values(child, key_name, f"{path}[{index}]")


def test_registry_index_lists_every_profile_file_exactly_once() -> None:
    index = yaml.safe_load((REGISTRIES / "index.yaml").read_text(encoding="utf-8"))
    for section in ("skeletons", "representations", "runtimes"):
        declared = index["registries"][section]
        assert len(declared) == len(set(declared)), (
            f"registries/index.yaml contains duplicate {section} entries"
        )
        directory = REGISTRIES / section
        discovered = {
            path.relative_to(REPO_ROOT).as_posix() for path in directory.glob("*.yaml")
        }
        assert set(declared) == discovered, (
            f"registries/index.yaml {section} drift: "
            f"missing={sorted(discovered - set(declared))}, "
            f"stale={sorted(set(declared) - discovered)}"
        )

    for section in ("models", "bundles"):
        declared = index["registries"][section]
        assert len(declared) == len(set(declared)), (
            f"registries/index.yaml contains duplicate {section} entries"
        )
        directory = REGISTRIES / section
        formal = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in directory.glob("*.yaml")
            if yaml.safe_load(path.read_text(encoding="utf-8")).get("status") != "draft"
        }
        assert set(declared) == formal, (
            f"registries/index.yaml {section} formal-entry drift: "
            f"missing={sorted(formal - set(declared))}, "
            f"stale={sorted(set(declared) - formal)}"
        )

    research_only = (
        "registries/models/first-wave.v1.yaml",
        "registries/bundles/starter.yaml",
    )
    all_declared = {
        path for entries in index["registries"].values() for path in entries
    }
    for locator in research_only:
        path = REPO_ROOT / locator
        assert path.is_file()
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["status"] == "draft"
        assert locator not in all_declared


def test_pinned_adapter_representation_semantics_are_not_genericized() -> None:
    representations = _yaml_by_id(REGISTRIES / "representations")
    skeletons = _yaml_by_id(REGISTRIES / "skeletons")

    hy = representations["hy_motion.body22.rot6d_translation.v1"][1]
    assert hy["rotation_layout"] == "upstream_view_3x2_interleaved_columns"

    inter_export = representations["interhuman.two_actor_smpl22.pos3_rot6d.v1"][1]
    assert inter_export["root_rotation_semantics"] == (
        "absent_zero_sentinel_mapped_to_identity"
    )
    inter_skeleton = skeletons["interhuman.two_actor_smpl22.v1"][1]
    assert inter_skeleton["root_motion"]["rotation"] == (
        "absent_zero_sentinel_mapped_to_identity"
    )

    senti = representations["susu.body25_hands40.cont6d_root_delta.v1"][1]
    assert senti["units"] == "root_delta_centimeters_rotations_dimensionless"

    senti_adapter = yaml.safe_load(
        (ADAPTER_ROOT / "sentiavatar-susu-mta63" / "adapter.yaml").read_text(
            encoding="utf-8"
        )
    )
    senti_output = senti_adapter["output_profile"]
    canonical = representations[senti_output["representation_id"]][1]
    assert senti_output["skeleton_id"] == canonical["skeleton_id"]
    assert senti_output["frame_shape"][1:] == canonical["frame_shape"]
    assert senti_output["units"] == canonical["units"]
    assert (
        senti_output["rotation_representation"] == canonical["rotation_representation"]
    )
    assert senti_output["rotation_layout"] == canonical["rotation_layout"]


def test_prism_is_installable_but_external_only_until_license_review_completes() -> (
    None
):
    manifest = ModelCatalog.load(PLUGIN_ROOT).get("prism-tp2m-1-4b")
    assert manifest.model.status is ModelSupportStatus.INTEGRATED_EXPERIMENTAL
    assert manifest.model.upstream.repository == "https://github.com/ZeyuLing/PRISM"
    assert (
        manifest.model.upstream.revision == "3c58bc5d946f0827171a3712ed36314f4b1a5186"
    )
    assert [runtime.id for runtime in manifest.runtime_variants] == [
        "prism-tp2m-1-4b-cu128-component-split",
        "prism-tp2m-1-4b-cpu",
    ]
    assert manifest.production_acceptance is not None
    assert manifest.licenses.redistribution_allowed is False
    assert manifest.resources["integration_state"] == "integrated_experimental"
    assert manifest.resources["technical_availability"] == (
        "historical_runtime_0_1_2_acceptance_new_runtime_baselines_require_reacceptance"
    )
    assert manifest.resources["distribution_status"] == "external_assets_only"
    assert manifest.resources["license_status"] == "license_review_required"
    assert manifest.resources["native_public_feature_dim"] == 69
    assert manifest.resources["internal_network_feature_dim"] == 138
    artifacts = {artifact.id: artifact for artifact in manifest.artifacts}
    artifact = artifacts["prism-tp2m-1-4b-official-hf"]
    assert artifact.repository == "ZeyuLing/PRISM-TP2M-1.4B"
    assert artifact.revision == "825daaa27f4f3845eb0978674c3acb378a12cda6"
    assert artifacts["prism-umt5-xxl-tokenizer"].revision == (
        "66cb9e7e85526fe440a945569e42c72fb6cbc0ad"
    )
    assert artifacts["prism-motionhub-smplh-stats"].revision == (
        "c3f6c8eb8a4ba9e5ca521cdc0af9264756b66726"
    )

    release_assets = json.loads(
        (REGISTRIES / "bundles" / "release-assets.v1.json").read_text(encoding="utf-8")
    )
    released_models = {item["model_id"]: item for item in release_assets["models"]}
    assert "prism-tp2m-1-4b" in released_models
    released_prism = released_models["prism-tp2m-1-4b"]
    assert released_prism["shared_worker_project"]["project_package"] == (
        "virea-model-prism-tp2m-1-4b-runtime"
    )
    assert released_prism["runtime_project"]["project_package"] == (
        "virea-model-prism-tp2m-1-4b-cu128-runtime"
    )
    assert {
        project["project_package"]
        for project in released_prism["additional_runtime_projects"]
    } == {"virea-model-prism-tp2m-1-4b-cpu-runtime"}


def test_acmdm_memory_floor_calibration_binds_fixed_and_maximum_requests() -> None:
    manifest = ModelCatalog.load(PLUGIN_ROOT).get("acmdm-humanml3d")
    runtime = manifest.runtime_variants[0]
    calibration = manifest.resources["memory_floor_calibration"]

    assert manifest.resources["memory_floor_status"] == (
        "calibrated_fixed_and_maximum_request_on_win64_rtx5090"
    )
    assert calibration["schema_version"] == (
        "virea.runtime_memory_floor_calibration.v1.0.0"
    )
    assert calibration["scope"] == {
        "platform": "win-64",
        "accelerator": "NVIDIA GeForce RTX 5090 Laptop GPU",
        "device_uuid_redacted": True,
        "runtime_id": "acmdm-humanml3d-cu128",
        "runtime_project_package": "virea-model-acmdm-humanml3d-runtime",
        "runtime_project_version": "0.1.3",
        "runtime_core_epoch": "virea-runtime-core-20260821.2",
        "python_version": "3.11",
        "torch_version": "2.11.0+cu128",
        "torch_cuda_version": "12.8",
        "memory_strategy": "cuda_full",
    }
    observations = calibration["observations"]
    assert [observation["frame_count"] for observation in observations] == [80, 196]
    assert [observation["job_id"] for observation in observations] == [
        "01M0J2AKYNW53B285ZHJ55NBK1",
        "01M0J2Q7GXAR4YBH2ZH1670JZS",
    ]
    assert [observation["result_id"] for observation in observations] == [
        "01M0J2BP0W0Z5XSRPQPG443CZ7",
        "01M0J2QP7TCM2AD7VCD4EAZSRN",
    ]
    for observation in observations:
        assert observation["result_id"] in observation["model_result_locator"]
        assert observation["job_id"] in observation["generation_metadata_locator"]
    assert calibration["observed_maxima"] == {
        "process_peak_rss_bytes": 2552532992,
        "system_ram_available_drop_peak_bytes": 1540747264,
        "cuda_max_memory_allocated_bytes": 673024512,
        "cuda_max_memory_reserved_bytes": 687865856,
        "cuda_device_free_drop_bytes": 759169024,
    }
    assert calibration["floor_formula"] == {
        "ram_observed_basis_bytes": 2552532992,
        "cuda_observed_basis_bytes": 759169024,
        "headroom_policy": "max_2_gib_or_20_percent",
        "ram_headroom_bytes": 2147483648,
        "cuda_headroom_bytes": 2147483648,
        "derived_min_free_ram_gib": 5,
        "derived_min_free_vram_gib": 3,
        "registered_min_free_ram_gib": 8,
        "registered_min_free_vram_gib": 6,
        "floors_not_reduced": True,
    }
    assert runtime.resource_profiles[0].min_free_ram_gib == 8
    assert runtime.resource_profiles[0].min_free_vram_gib == 6
    assert runtime.project_version == "0.1.4"
    assert runtime.availability == (
        "cuda_wrapper_contract_and_lock_baseline_historical_runtime_0_1_3_"
        "evidence_requires_reacceptance"
    )


def test_momadiff_memory_floor_calibration_binds_both_runtime_profiles() -> None:
    manifest = ModelCatalog.load(PLUGIN_ROOT).get("momadiff-humanml3d")
    calibration = manifest.resources["memory_floor_calibration"]
    runtimes = {runtime.id: runtime for runtime in manifest.runtime_variants}

    assert manifest.resources["memory_floor_status"] == (
        "calibrated_per_profile_fixed_and_maximum_request_on_win64"
    )
    assert calibration["schema_version"] == (
        "virea.runtime_memory_floor_calibration.v1.0.0"
    )
    assert calibration["evidence_root_logical_id"] == (
        "virea-0.4.0/production-e2e-20260821/momadiff-humanml3d"
    )
    assert calibration["artifact_revisions"] == {
        "momadiff-upstream-source": "6dd9bea254bbca6cf19756ac3ee037cbf4f6021c",
        "momadiff-humanml3d-checkpoints": ("daf83c1441fbb9e8bacd377e28f557b54080c2a1"),
        "openai-clip-vit-b-32": ("d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"),
    }

    cuda = calibration["profiles"]["cuda-full"]
    assert cuda["evidence_classification"].endswith("not_production_browser_evidence")
    assert cuda["scope"]["runtime_project_version"] == "0.1.3"
    assert cuda["scope"]["runtime_core_epoch"] == ("virea-runtime-core-20260821.2")
    assert [item["frame_count"] for item in cuda["observations"]] == [80, 196]
    assert [item["job_id"] for item in cuda["observations"]] == [
        "01M0J3CBKV7NKT2ENF03CQQD43",
        "01M0J3E659QANNHRGJYZ7K8S4E",
    ]
    assert [item["result_id"] for item in cuda["observations"]] == [
        "01M0J3D3EM9XCD1KHBCEWWPHEE",
        "01M0J3EMPKJTVQ65XKWVD46X5G",
    ]
    for observation in cuda["observations"]:
        assert observation["job_id"] in observation["generation_metadata_locator"]
        assert observation["result_id"] in observation["model_result_locator"]
    assert cuda["observed_maxima"] == {
        "process_peak_rss_bytes": 4404617216,
        "system_ram_available_drop_peak_bytes": 3827294208,
        "cuda_max_memory_allocated_bytes": 701373440,
        "cuda_max_memory_reserved_bytes": 721420288,
        "cuda_device_free_drop_load_to_inference_bytes": 792723456,
    }
    assert cuda["floor_formula"] == {
        "ram_observed_basis_bytes": 4404617216,
        "ram_headroom_bytes": 2147483648,
        "derived_min_free_ram_gib": 7,
        "registered_min_free_ram_gib": 8,
        "cuda_observed_basis_bytes": 792723456,
        "cuda_headroom_bytes": 2147483648,
        "derived_min_free_vram_gib": 3,
        "registered_min_free_vram_gib": 6,
        "floors_not_reduced": True,
    }

    cpu = calibration["profiles"]["whole-model-cpu"]
    assert cpu["evidence_classification"] == (
        "direct_worker_resource_calibration_not_production_browser_evidence"
    )
    assert cpu["scope"]["runtime_project_version"] == "0.1.3"
    assert cpu["scope"]["runtime_core_epoch"] == ("virea-runtime-core-20260821.2")
    assert cpu["scope"]["cuda_visible_devices"] == "-1"
    assert cpu["scope"]["torch_cuda_available"] is False
    assert cpu["scope"]["torch_cuda_device_count"] == 0
    assert [item["frame_count"] for item in cpu["observations"]] == [80, 196]
    assert [item["qa_job_id"] for item in cpu["observations"]] == [
        "momadiff-cpu-80-20260821T121330347878Z",
        "momadiff-cpu-196-20260821T121512012901Z",
    ]
    assert all(item["state_store_result_id"] is None for item in cpu["observations"])
    assert all(item["nvidia_worker_pid_seen"] is False for item in cpu["observations"])
    assert [item["nvidia_smi_sample_count"] for item in cpu["observations"]] == [
        67,
        34,
    ]
    assert cpu["observed_maxima"] == {
        "process_peak_rss_bytes": 4527616000,
        "system_ram_available_drop_peak_bytes": 4305440768,
    }
    assert cpu["floor_formula"] == {
        "ram_observed_basis_bytes": 4527616000,
        "ram_headroom_bytes": 2147483648,
        "derived_min_free_ram_gib": 7,
        "registered_min_free_ram_gib": 12,
        "floors_not_reduced": True,
    }
    assert cpu["portability"] == {
        "cpu_profile_extrapolated_to_other_platforms": False,
        "linux_or_macos_production_evidence": False,
        "admission_rechecks_current_free_resources": True,
        "production_browser_evidence": False,
    }

    cuda_runtime = runtimes["momadiff-humanml3d-cu128"]
    cpu_runtime = runtimes["momadiff-humanml3d-cpu"]
    assert cuda_runtime.resource_profiles[0].min_free_ram_gib == 8
    assert cuda_runtime.resource_profiles[0].min_free_vram_gib == 6
    assert cpu_runtime.resource_profiles[0].min_free_ram_gib == 12
    assert cuda_runtime.availability == (
        "historical_real_checkpoint_acceptance_and_calibration_requires_current_"
        "core_epoch_reacceptance"
    )
    assert cpu_runtime.availability == (
        "historical_real_checkpoint_calibration_requires_current_core_epoch_"
        "reacceptance_other_platforms_unverified"
    )


def test_all_model_manifest_outputs_resolve_to_representation_and_skeleton_registries() -> (
    None
):
    representations = _registry_ids(REGISTRIES / "representations")
    skeletons = _registry_ids(REGISTRIES / "skeletons")
    catalog = ModelCatalog.load(PLUGIN_ROOT)

    assert catalog.ids()
    for manifest in catalog.manifests():
        context = f"plugins/models/{manifest.model.id}/manifest.yaml"
        assert manifest.output.representation_id in representations, (
            f"{context} output.representation_id={manifest.output.representation_id!r} "
            "does not resolve to registries/representations"
        )
        assert manifest.output.skeleton_id in skeletons, (
            f"{context} output.skeleton_id={manifest.output.skeleton_id!r} "
            "does not resolve to registries/skeletons"
        )
        for face_profile in manifest.output.face_representation_ids:
            assert face_profile in representations, (
                f"{context} output.face_representation_ids contains {face_profile!r}, "
                "which does not resolve to registries/representations"
            )
        if manifest.test_fixture is not None:
            assert (
                manifest.test_fixture.expected_representation_id
                == manifest.output.representation_id
            )
            assert manifest.test_only is True
        if manifest.production_acceptance is not None:
            expected = manifest.production_acceptance.expected
            assert expected.representation_id == manifest.output.representation_id
            assert expected.skeleton_id == manifest.output.skeleton_id
            assert manifest.test_only is False


def test_registry_representation_skeletons_and_adapter_output_profiles_resolve() -> (
    None
):
    representations = _registry_ids(REGISTRIES / "representations")
    skeletons = _registry_ids(REGISTRIES / "skeletons")

    for representation_id, path in representations.items():
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        skeleton_id = payload.get("skeleton_id")
        assert skeleton_id in skeletons, (
            f"representation {representation_id!r} references missing skeleton "
            f"{skeleton_id!r} in {path}"
        )

    adapters = _yaml_by_id(ADAPTER_ROOT, "*/adapter.yaml")
    for adapter_id, (adapter_path, adapter) in adapters.items():
        output_profile = adapter.get("output_profile")
        assert isinstance(output_profile, dict), (
            f"{adapter_path} has no output_profile mapping"
        )
        representation_id = output_profile.get("representation_id")
        skeleton_id = output_profile.get("skeleton_id")
        assert representation_id in representations, (
            f"adapter {adapter_id!r} output_profile.representation_id={representation_id!r} "
            "does not resolve to registries/representations"
        )
        assert skeleton_id in skeletons, (
            f"adapter {adapter_id!r} output_profile.skeleton_id={skeleton_id!r} "
            "does not resolve to registries/skeletons"
        )
        registered_output = yaml.safe_load(
            representations[representation_id].read_text(encoding="utf-8")
        )
        assert skeleton_id == registered_output["skeleton_id"], (
            f"adapter {adapter_id!r} output skeleton disagrees with representation "
            f"{representation_id!r}"
        )
        declared_shape = output_profile.get("frame_shape")
        if declared_shape is not None:
            normalized_shape = list(declared_shape)
            if normalized_shape and normalized_shape[0] == "T":
                normalized_shape = normalized_shape[1:]
            assert normalized_shape == registered_output["frame_shape"], (
                f"adapter {adapter_id!r} output shape disagrees with representation "
                f"{representation_id!r}"
            )
        for semantic_key in (
            "units",
            "rotation_representation",
            "rotation_layout",
        ):
            if semantic_key in output_profile:
                assert (
                    output_profile[semantic_key] == registered_output[semantic_key]
                ), (
                    f"adapter {adapter_id!r} output {semantic_key} disagrees with "
                    f"representation {representation_id!r}"
                )
        for value_path, declared_representation in _named_values(
            adapter,
            "representation_id",
        ):
            assert declared_representation in representations, (
                f"adapter {adapter_id!r} {value_path}={declared_representation!r} "
                "does not resolve to registries/representations"
            )
        for value_path, declared_skeleton in _named_values(adapter, "skeleton_id"):
            assert declared_skeleton in skeletons, (
                f"adapter {adapter_id!r} {value_path}={declared_skeleton!r} "
                "does not resolve to registries/skeletons"
            )


def test_models_and_adapter_declarations_cross_reference_each_other() -> None:
    representations = _registry_ids(REGISTRIES / "representations")
    catalog = ModelCatalog.load(PLUGIN_ROOT)
    manifests = {manifest.model.id: manifest for manifest in catalog.manifests()}
    adapters = _yaml_by_id(ADAPTER_ROOT, "*/adapter.yaml")

    for model_id, manifest in manifests.items():
        adapter_id = manifest.model.adapter_family
        assert adapter_id in adapters, (
            f"model {model_id!r} adapter_family={adapter_id!r} has no "
            "plugins/adapters/<id>/adapter.yaml declaration"
        )
        adapter_path, adapter = adapters[adapter_id]
        assert model_id in adapter.get("source_models", []), (
            f"{adapter_path} does not list source model {model_id!r}"
        )
        native_profile = adapter.get("native_profile")
        assert isinstance(native_profile, dict), (
            f"{adapter_path} has no native_profile mapping"
        )
        assert manifest.output.representation_id == native_profile.get(
            "representation_id"
        ), (
            f"model {model_id!r} output representation must be the Worker/native "
            f"carrier declared by adapter {adapter_id!r}"
        )
        adapter_declared_profile_ids = {
            value
            for _, value in _named_values(adapter, "representation_id")
            if isinstance(value, str)
        }
        for value_path, representation_id in _named_values(
            list(manifest.inputs), "representation_id"
        ):
            assert isinstance(representation_id, str) and representation_id, (
                f"model {model_id!r} inputs{value_path} must be a representation id"
            )
            if representation_id in representations:
                continue
            assert manifest.model.status is ModelSupportStatus.RUNNABLE_UPSTREAM, (
                f"non-runnable-upstream model {model_id!r} uses unregistered input "
                f"representation {representation_id!r}"
            )
            assert representation_id in adapter_declared_profile_ids, (
                f"runnable_upstream model {model_id!r} input representation "
                f"{representation_id!r} is neither globally registered nor declared by "
                f"its adapter in {adapter_path}"
            )

    for adapter_id, (adapter_path, adapter) in adapters.items():
        source_models = adapter.get("source_models")
        assert isinstance(source_models, list) and source_models, (
            f"{adapter_path} must declare at least one source model"
        )
        assert len(source_models) == len(set(source_models)), (
            f"{adapter_path} contains duplicate source_models"
        )
        for model_id in source_models:
            assert model_id in manifests, (
                f"adapter {adapter_id!r} references unknown source model {model_id!r}"
            )
            assert manifests[model_id].model.adapter_family == adapter_id


def test_manifest_runtime_variants_resolve_to_identical_registry_specs() -> None:
    runtime_files = _yaml_by_id(REGISTRIES / "runtimes")
    runtimes = {
        runtime_id: RuntimeSpec.model_validate(payload)
        for runtime_id, (_, payload) in runtime_files.items()
    }
    catalog = ModelCatalog.load(PLUGIN_ROOT)

    for manifest in catalog.manifests():
        for runtime in manifest.runtime_variants:
            assert runtime.id in runtimes, (
                f"model {manifest.model.id!r} runtime variant {runtime.id!r} does not "
                "resolve to registries/runtimes"
            )
            assert runtime.model_dump(mode="json") == runtimes[runtime.id].model_dump(
                mode="json"
            ), (
                f"model {manifest.model.id!r} embeds runtime {runtime.id!r} with a spec "
                "that differs from its registry declaration"
            )


def test_production_runtime_project_versions_match_their_build_metadata() -> None:
    catalog = ModelCatalog.load(PLUGIN_ROOT)

    for manifest in catalog.manifests():
        if manifest.production_acceptance is None:
            continue
        for runtime in manifest.runtime_variants:
            assert runtime.project_package is not None
            assert runtime.project_version is not None
            assert runtime.runtime_core_epoch == RUNTIME_CORE_EPOCH
            assert runtime.working_directory is not None
            project_path = REPO_ROOT / runtime.working_directory / "pyproject.toml"
            project = tomllib.loads(project_path.read_text(encoding="utf-8"))["project"]
            assert project["name"] == runtime.project_package, runtime.id
            assert project["version"] == runtime.project_version, runtime.id


def test_model_bundles_resolve_models_and_default_membership() -> None:
    model_ids = set(ModelCatalog.load(PLUGIN_ROOT).ids())
    bundles = _yaml_by_id(REGISTRIES / "bundles")

    for bundle_id, (bundle_path, bundle) in bundles.items():
        entries = bundle.get("models")
        assert isinstance(entries, list) and entries, (
            f"bundle {bundle_id!r} has no models"
        )
        referenced = [
            entry.get("model_id") for entry in entries if isinstance(entry, dict)
        ]
        assert len(referenced) == len(entries), (
            f"{bundle_path} has a malformed model entry"
        )
        assert len(referenced) == len(set(referenced)), (
            f"{bundle_path} has duplicate models"
        )
        assert set(referenced) <= model_ids, (
            f"{bundle_path} references unknown models: {sorted(set(referenced) - model_ids)}"
        )
        default_model_id = bundle.get("default_model_id")
        assert default_model_id in referenced, (
            f"{bundle_path} default_model_id={default_model_id!r} is not a bundle member"
        )


def test_canonical_package_names_have_no_parallel_source_tree() -> None:
    for forbidden in ("model-pool", "model-sdk", "motion-ir", "worker_sdk"):
        alias = REPO_ROOT / "packages" / forbidden
        assert not (alias / "pyproject.toml").exists(), (
            f"parallel package alias is forbidden: {alias}"
        )
        if alias.exists():
            assert not any(alias.rglob("*.py")), (
                f"parallel Python source tree is forbidden: {alias}"
            )
