from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal


ProfileStatus = Literal["draft", "source_verified", "regression_verified", "release_ready"]
RootRotationSemantics = Literal["local_to_world", "world_operator", "not_applicable"]


@dataclass(frozen=True)
class DatasetProfile:
    """Resolved, serializable interpretation rules for one source representation.

    Skeleton topology and joint mappings remain domain constants in the motion
    package.  This record only contains dataset- and export-specific facts.
    """

    schema_version: str
    key: str
    dataset: str
    source_representation: str
    joint_system: str
    rotation_encoding: str
    rotation_space: str
    fps_fallback: float
    fps_fields: tuple[str, ...]
    world_basis: str
    source_up: str
    source_forward: str | None
    handedness: str
    unit: str
    unit_scale_to_meter: float
    validation_status: ProfileStatus
    root_rotation_semantics: RootRotationSemantics = "local_to_world"
    codec_source_profiles: tuple[str, ...] = ()
    rotation_6d_layout: str | None = None
    array_layout: dict[str, Any] = field(default_factory=dict)
    root_axes: tuple[int, int, int] = (0, 1, 2)
    translation_zeroed: bool = True
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fps_fields"] = list(self.fps_fields)
        payload["codec_source_profiles"] = list(self.codec_source_profiles)
        payload["root_axes"] = list(self.root_axes)
        payload["notes"] = list(self.notes)
        return payload


PROFILE_VERSION = "virea.dataset_profile.v1.0.0"


PROFILES: dict[str, DatasetProfile] = {
    "amass_smplh": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="amass_smplh",
        dataset="amass",
        source_representation="smplh_axis_angle_npz",
        joint_system="smplh_body22",
        rotation_encoding="axis_angle",
        rotation_space="parent_local",
        fps_fallback=60.0,
        fps_fields=("mocap_framerate", "mocap_frame_rate"),
        world_basis="z_up_to_y_up",
        source_up="+z",
        source_forward=None,
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="regression_verified",
        codec_source_profiles=("smplh_body22",),
        array_layout={"body_axis_angle": [0, 66], "translation_key": "trans"},
        notes=("Filename-derived semantics are not native AMASS annotations.",),
    ),
    "babel_amass": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="babel_amass",
        dataset="babel",
        source_representation="babel_annotations_over_amass_smplh",
        joint_system="smplh_body22",
        rotation_encoding="axis_angle",
        rotation_space="parent_local",
        fps_fallback=60.0,
        fps_fields=("mocap_framerate", "mocap_frame_rate"),
        world_basis="z_up_to_y_up",
        source_up="+z",
        source_forward=None,
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="source_verified",
        codec_source_profiles=("smplh_body22",),
        array_layout={"body_axis_angle": [0, 66], "annotation_time_unit": "seconds"},
    ),
    "beat_body22_converted": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="beat_body22_converted",
        dataset="beat",
        source_representation="beat_bvh_converted_axis_angle_npz",
        joint_system="body22",
        rotation_encoding="axis_angle",
        rotation_space="parent_local",
        fps_fallback=120.0,
        fps_fields=("fps", "framerate"),
        world_basis="identity_y_up",
        source_up="+y",
        source_forward="+z",
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="source_verified",
        codec_source_profiles=("beat_bvh_body22",),
        array_layout={"body_axis_angle": [0, 66], "upstream_raw": "120fps_bvh_z_up_y_forward"},
        notes=("The NPZ/TSV files are converted derivatives, not BEAT raw BVH/TXT.",),
    ),
    "grab_smplx55": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="grab_smplx55",
        dataset="grab",
        source_representation="smplx_fullpose_npz",
        joint_system="smplx55",
        rotation_encoding="axis_angle",
        rotation_space="parent_local",
        fps_fallback=120.0,
        fps_fields=("framerate", "fps"),
        world_basis="z_up_to_y_up",
        source_up="+z",
        source_forward=None,
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="source_verified",
        codec_source_profiles=("grab_smplx55",),
        array_layout={"fullpose": [0, 165], "contact_no_value": 0},
    ),
    "motionx_smplx322": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="motionx_smplx322",
        dataset="motionx",
        source_representation="motionx_smplx_322",
        joint_system="smplx53_normalized_to_smplx55",
        rotation_encoding="axis_angle",
        rotation_space="parent_local",
        fps_fallback=30.0,
        fps_fields=("fps",),
        world_basis="identity_y_up",
        source_up="+y",
        source_forward=None,
        handedness="right",
        unit="meter_or_export_specific",
        unit_scale_to_meter=1.0,
        validation_status="draft",
        codec_source_profiles=("motionx_smplx322",),
        array_layout={
            "root": [0, 3],
            "body": [3, 66],
            "hands": [66, 156],
            "jaw": [156, 159],
            "expression": [159, 209],
            "face_shape": [209, 309],
            "translation": [309, 312],
            "betas": [312, 322],
            "identity_eye_slots": [23, 24],
        },
        notes=("World basis/unit require per-sub-source visual regression before release.",),
    ),
    "humanml3d_263d": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="humanml3d_263d",
        dataset="humanml3d",
        source_representation="humanml3d_263d",
        joint_system="humanml3d_body22",
        rotation_encoding="root4_plus_ric63_positions",
        rotation_space="position_recovery",
        fps_fallback=20.0,
        fps_fields=("fps",),
        world_basis="identity_y_up",
        source_up="+y",
        source_forward="+z",
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="source_verified",
        root_rotation_semantics="not_applicable",
        codec_source_profiles=("humanml3d_263d",),
        array_layout={"root": [0, 4], "ric": [4, 67], "feature_dim": 263},
    ),
    "susu_official_columns_local": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="susu_official_columns_local",
        dataset="susuinteracts",
        source_representation="susu_body_hands_6d",
        joint_system="susu63_unique",
        rotation_encoding="rotation_6d_first_two_columns",
        rotation_space="parent_local",
        fps_fallback=20.0,
        fps_fields=("fps",),
        world_basis="identity_y_up",
        source_up="+y",
        source_forward=None,
        handedness="right",
        unit="meter",
        unit_scale_to_meter=1.0,
        validation_status="source_verified",
        codec_source_profiles=("susu_official_columns_local",),
        rotation_6d_layout="first_two_columns",
        array_layout={"root_translation": [0, 3], "body_6d": [3, 153], "hand_6d": [0, 120]},
    ),
    "susu_retarget_maya": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="susu_retarget_maya",
        dataset="susuinteracts",
        source_representation="susu_retarget_maya_6d_body_hands",
        joint_system="susu63_unique",
        rotation_encoding="rotation_6d_first_two_columns",
        rotation_space="parent_local",
        fps_fallback=20.0,
        fps_fields=("fps",),
        world_basis="neg_z_up_to_y_up",
        source_up="-z",
        source_forward=None,
        handedness="right",
        unit="meter_or_centimeter",
        unit_scale_to_meter=1.0,
        validation_status="draft",
        codec_source_profiles=("susu_retarget_maya_6d_body_hands",),
        rotation_6d_layout="first_two_columns",
        root_axes=(0, 2, 1),
        array_layout={"root_translation": [0, 3], "body_6d": [3, 153], "hand_6d": [0, 120]},
        notes=("Must be calibrated against matching positions/BVH before release.",),
    ),
    "susu_chonglu": DatasetProfile(
        schema_version=PROFILE_VERSION,
        key="susu_chonglu",
        dataset="susuinteracts",
        source_representation="susu_chonglu_6d_body_hands_positions",
        joint_system="susu63_unique",
        rotation_encoding="rotation_6d_first_two_columns",
        rotation_space="parent_local",
        fps_fallback=20.0,
        fps_fields=("fps",),
        world_basis="identity_y_up",
        source_up="+y",
        source_forward=None,
        handedness="right",
        unit="centimeter",
        unit_scale_to_meter=0.01,
        validation_status="draft",
        codec_source_profiles=("susu_chonglu_6d_body_hands_cm",),
        rotation_6d_layout="first_two_columns",
        root_axes=(0, 2, 1),
        array_layout={"root_translation": [0, 3], "body_6d": [3, 153], "hand_6d": [0, 120]},
        notes=("Positions are authoritative until rotation export is calibrated.",),
    ),
}

# Representation-specific profiles.  These deliberately remain separate even
# when datasets share a codec: the carrier layout, basis, units and evidence
# status are artifact facts, not properties of a generic SMPL family name.
PROFILES.update(
    {
        "amass_smpl_body22": replace(
            PROFILES["amass_smplh"],
            key="amass_smpl_body22",
            source_representation="smpl_or_smplh_body_axis_angle_npz",
            joint_system="smpl_body22",
            validation_status="source_verified",
            codec_source_profiles=("smplh_body22",),
            array_layout={"body_axis_angle": [0, 66], "translation_key": "trans"},
        ),
        "amass_smplh156": replace(
            PROFILES["amass_smplh"],
            key="amass_smplh156",
            source_representation="smplh_body_hands_axis_angle_npz",
            joint_system="smplh_body22_hands30",
            validation_status="source_verified",
            codec_source_profiles=("smplh_body22_hands30",),
            array_layout={
                "body_axis_angle": [0, 66],
                "hands_axis_angle": [66, 156],
                "translation_key": "trans",
            },
        ),
        "amass_smplx_stageii165": replace(
            PROFILES["amass_smplh"],
            key="amass_smplx_stageii165",
            source_representation="amass_stageii_smplx_fullpose_npz",
            joint_system="smplx55",
            world_basis="identity_y_up",
            source_up="+y",
            unit="meter",
            unit_scale_to_meter=1.0,
            validation_status="draft",
            codec_source_profiles=("amass_smplx_stageii165",),
            array_layout={"fullpose": [0, 165], "translation_key": "trans"},
            notes=("Stage-II SMPL-X basis remains fail-closed until representative source/VRM regression.",),
        ),
        "amass_humanact12_positions": replace(
            PROFILES["amass_smplh"],
            key="amass_humanact12_positions",
            source_representation="humanact12_joint_positions_npy",
            joint_system="humanact12_position_skeleton",
            rotation_encoding="none",
            rotation_space="position_fitting",
            fps_fallback=20.0,
            fps_fields=(),
            root_rotation_semantics="not_applicable",
            codec_source_profiles=("position_sequence",),
            validation_status="draft",
            array_layout={"positions": ["T", "J", 3]},
            notes=("HumanAct12 position basis and skeleton mapping require source regression.",),
        ),
        "babel_amass_smpl_body22": replace(
            PROFILES["babel_amass"],
            key="babel_amass_smpl_body22",
            source_representation="babel_annotations_over_amass_body_axis_angle",
            joint_system="smpl_body22",
            codec_source_profiles=("smplh_body22",),
            array_layout={"body_axis_angle": [0, 66], "annotation_time_unit": "seconds"},
        ),
        "babel_amass_smplh156": replace(
            PROFILES["babel_amass"],
            key="babel_amass_smplh156",
            source_representation="babel_annotations_over_amass_smplh156",
            joint_system="smplh_body22_hands30",
            codec_source_profiles=("smplh_body22_hands30",),
            array_layout={
                "body_axis_angle": [0, 66],
                "hands_axis_angle": [66, 156],
                "annotation_time_unit": "seconds",
            },
        ),
        "babel_amass_smplx_stageii165": replace(
            PROFILES["babel_amass"],
            key="babel_amass_smplx_stageii165",
            source_representation="babel_annotations_over_amass_stageii_smplx",
            joint_system="smplx55",
            world_basis="identity_y_up",
            source_up="+y",
            validation_status="draft",
            codec_source_profiles=("babel_amass_smplx_stageii165",),
            array_layout={"fullpose": [0, 165], "annotation_time_unit": "seconds"},
            notes=("Stage-II SMPL-X carrier basis remains fail-closed until source/VRM regression.",),
        ),
        "motionx_aist_smplx322": replace(
            PROFILES["motionx_smplx322"],
            key="motionx_aist_smplx322",
            source_representation="motionx_aist_smplx_322",
            unit="centimeter",
            unit_scale_to_meter=0.01,
            codec_source_profiles=("motionx_aist_smplx322",),
            notes=("AIST translation uses the audited 0.01 source-to-meter scale; basis remains draft.",),
        ),
        "susu_retarget_maya_rotation_only": replace(
            PROFILES["susu_retarget_maya"],
            key="susu_retarget_maya_rotation_only",
            source_representation="susu_retarget_maya_6d_body_hands_rotation_only",
            world_basis="identity_y_up",
            source_up="+y",
            root_axes=(0, 2, 1),
            notes=(
                "Rotation-only branch actually executes identity_y_up; 6D layout/space remains visually uncalibrated and fail-closed.",
            ),
        ),
        "susu_retarget_maya_positions": replace(
            PROFILES["susu_retarget_maya"],
            key="susu_retarget_maya_positions",
            source_representation="susu_retarget_maya_positions_with_6d_body_hands",
            unit="centimeter",
            unit_scale_to_meter=0.01,
            notes=("Position branch uses neg_z_up_to_y_up and remains draft pending source/VRM regression.",),
        ),
    }
)


DATASET_DEFAULT_PROFILE = {
    "amass": "amass_smpl_body22",
    "babel": "babel_amass_smpl_body22",
    "beat": "beat_body22_converted",
    "grab": "grab_smplx55",
    "motionx": "motionx_smplx322",
    "humanml3d": "humanml3d_263d",
    "susuinteracts": "susu_official_columns_local",
}


def profile_for(key: str) -> DatasetProfile:
    try:
        return PROFILES[key]
    except KeyError as exc:
        raise KeyError(f"unknown dataset profile: {key}") from exc


def profile_key_for_source(
    dataset: str,
    codec_key: str,
    sample_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    facts = metadata or {}
    explicit = str(facts.get("dataset_profile") or "")
    if explicit:
        return explicit
    if dataset == "amass":
        return {
            "smplh_body_hands": "amass_smplh156",
            "smplx_fullpose": "amass_smplx_stageii165",
            "position_sequence": "amass_humanact12_positions",
        }.get(codec_key, "amass_smpl_body22")
    if dataset == "babel":
        return {
            "smplh_body_hands": "babel_amass_smplh156",
            "smplx_fullpose": "babel_amass_smplx_stageii165",
        }.get(codec_key, "babel_amass_smpl_body22")
    if dataset == "motionx":
        sub_source = str(facts.get("sub_source") or "").casefold()
        return "motionx_aist_smplx322" if sub_source == "aist" else "motionx_smplx322"
    if dataset == "susuinteracts":
        has_positions = bool(facts.get("has_positions"))
        return {
            "susu_retarget_maya_6d_body_hands": (
                "susu_retarget_maya_positions" if has_positions else "susu_retarget_maya_rotation_only"
            ),
            "susu_chonglu_6d_body_hands_cm": "susu_chonglu",
        }.get(codec_key, "susu_official_columns_local")
    try:
        return DATASET_DEFAULT_PROFILE[dataset]
    except KeyError as exc:
        raise KeyError(f"no dataset profile for {dataset}/{codec_key}/{sample_id}") from exc


def profile_for_sample(dataset: str, sample_id: str = "", explicit_key: str | None = None) -> DatasetProfile:
    if explicit_key:
        return profile_for(explicit_key)
    normalized = sample_id.replace("\\", "/").lower()
    if dataset == "susuinteracts":
        if normalized.startswith("fbx_to_json_data_susu_retarget_maya/"):
            return profile_for("susu_retarget_maya_rotation_only")
        if normalized.startswith("fbx_to_json_data_susu_chonglu/"):
            return profile_for("susu_chonglu")
    try:
        return profile_for(DATASET_DEFAULT_PROFILE[dataset])
    except KeyError as exc:
        raise KeyError(f"no default dataset profile for {dataset}") from exc
