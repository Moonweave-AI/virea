"""Resident ARDY model with bounded native history and cached NF4 text embeddings."""

from collections import OrderedDict
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from scipy.spatial.transform import Rotation

# Correspondence is in normalized T-pose coordinates, with extra spine joints
# collapsed using global rotations (never discarded as local Euler channels).
VRM_CORE = {
    "hips": ("Hips", None),
    "spine": ("Spine", "hips"),
    "chest": ("Spine1", "spine"),
    "upperChest": ("Spine3", "chest"),
    "neck": ("Neck", "upperChest"),
    "head": ("Head", "neck"),
    **{
        side + vrm: (prefix + core, side + parent if parent else "upperChest")
        for side, prefix in [("left", "Left"), ("right", "Right")]
        for vrm, core, parent in [
            ("Shoulder", "Shoulder", None),
            ("UpperArm", "Arm", "Shoulder"),
            ("LowerArm", "ForeArm", "UpperArm"),
            ("Hand", "Hand", "LowerArm"),
        ]
    },
    **{
        side + vrm: (prefix + core, side + parent if parent else "hips")
        for side, prefix in [("left", "Left"), ("right", "Right")]
        for vrm, core, parent in [
            ("UpperLeg", "UpLeg", None),
            ("LowerLeg", "Leg", "UpperLeg"),
            ("Foot", "Foot", "LowerLeg"),
            ("Toes", "ToeBase", "Foot"),
        ]
    },
}


class SpatialEngine:
    def __init__(self, model_dir: Path, text_dir: Path, *, steps=10):
        from ardy.model.llm2vec import LLM2Vec
        from ardy.model.load_model import load_model

        self.steps = steps
        self.model = load_model(
            model_dir.name,
            checkpoints_dir=str(model_dir.parent),
            device="cuda",
            text_encoder=False,
        )
        self.encoder = LLM2Vec.from_pretrained(
            str(text_dir), device_map={"": "cuda"}, local_files_only=True
        )
        # Required by the original LLM2Vec prompt template selection.
        self.encoder.model.config._name_or_path = "meta-llama/Meta-Llama-3-8B-Instruct"
        self.encoder.model.eval()
        self.embeddings = OrderedDict()
        self.fps = self.model.motion_rep.fps
        self.horizon = self.model.gen_horizon_len
        joints = self.model.skeleton.neutral_joints.cpu().numpy()
        self.hip_height = float(-joints[:, 1].min())

    @torch.inference_mode()
    def encode(self, prompt):
        if prompt not in self.embeddings:
            value = self.encoder.encode(
                [prompt], batch_size=1, show_progress_bar=False, device="cuda"
            )
            self.embeddings[prompt] = value[:, None].to(
                device="cuda", dtype=torch.float32
            )
            if len(self.embeddings) > 64:
                self.embeddings.popitem(last=False)
        self.embeddings.move_to_end(prompt)
        return self.embeddings[prompt]

    @torch.inference_mode()
    def initial_history(self, pose, position, yaw=0):
        """Encode the actually rendered normalized pose, not a new model T-pose."""
        skel = self.model.skeleton
        global_vrm = {}
        for name, (_, parent) in VRM_CORE.items():
            local = Rotation.from_quat(pose.get(name, [0, 0, 0, 1])).as_matrix()
            global_vrm[name] = (
                global_vrm[parent]
                if parent
                else Rotation.from_euler("y", yaw).as_matrix()
            ) @ local
        global_core = []
        mapped = {core: global_vrm[name] for name, (core, _) in VRM_CORE.items()}
        for name, parent in skel.bone_order_names_with_parents:
            global_core.append(
                mapped.get(
                    name, global_core[skel.bone_index[parent]] if parent else np.eye(3)
                )
            )
        global_core = np.stack(global_core)
        local = global_core.copy()
        for index, (_, parent) in enumerate(skel.bone_order_names_with_parents):
            if parent:
                local[index] = (
                    global_core[skel.bone_index[parent]].T @ global_core[index]
                )
        matrices = torch.as_tensor(local, device="cuda", dtype=torch.float32)[
            None
        ].repeat(8, 1, 1, 1)
        roots = torch.tensor(
            [position[0], position[1] + self.hip_height, position[2]], device="cuda"
        )[None].repeat(8, 1)
        return self.model.motion_rep(matrices, roots, to_normalize=True).unsqueeze(0)

    @torch.inference_mode()
    def step(
        self,
        history,
        prompt,
        constraints=(),
        *,
        steps=None,
        guidance=2.0,
        foot_correction=True,
    ):
        started = perf_counter()
        m = self.model
        history = history[:, -40:]
        frames = history.shape[1] + self.horizon
        mask, observed = None, None
        if constraints:
            end = max(int(c.frame_indices.max()) + 1 for c in constraints)
            frames = max(frames, ((end + 3) // 4) * 4)
            observed, mask = m.motion_rep.create_conditions_from_constraints_batched(
                list(constraints), torch.tensor([frames], device="cuda"), True, "cuda"
            )
        motion = m.autoregressive_step(
            num_frames=frames,
            num_denoising_steps=steps or self.steps,
            cfg_weight=(2.0, guidance),
            motion_mask=mask,
            observed_motion=observed,
            text_feat=self.encode(prompt),
            text_pad_mask=torch.ones(1, 1, device="cuda", dtype=torch.bool),
            init_history_sequence=history,
        )
        if foot_correction:
            from ardy.constraints import FullBodyConstraintSet, Root2DConstraintSet
            from ardy.postprocess import post_process_motion

            # Freeze already executed history during contact correction. Feed the
            # corrected generated poses back into the next native model step.
            motion[:, : history.shape[1]] = history
            full = m.motion_rep.inverse(motion, is_normalized=True)
            h = history.shape[1]
            fixed = FullBodyConstraintSet(
                m.skeleton,
                torch.arange(h),
                full["posed_joints"][0, :h].cpu(),
                full["global_rot_mats"][0, :h].cpu(),
            )
            corrected = post_process_motion(
                full["local_rot_mats"],
                full["root_positions"],
                full["foot_contacts"],
                m.skeleton,
                constraint_lst=[
                    c for c in constraints if isinstance(c, Root2DConstraintSet)
                ]
                + [fixed],
            )
            motion = m.motion_rep(
                corrected["local_rot_mats"],
                corrected["root_positions"],
                to_normalize=True,
            )
            motion[:, :h] = history
        # Keep the last observed sample in the packet for interpolation across a
        # boundary. History is never stretched to the wall-clock generation time.
        sample = torch.cat((history[:, -1:], motion[:, -self.horizon :]), dim=1)
        output = m.motion_rep.inverse(sample, is_normalized=True)
        global_mats = output["global_rot_mats"][0].float().cpu().numpy()
        rotations = {}
        for name, (source, parent) in VRM_CORE.items():
            matrix = global_mats[:, m.skeleton.bone_index[source]]
            if parent:
                p = global_mats[:, m.skeleton.bone_index[VRM_CORE[parent][0]]]
                matrix = np.swapaxes(p, -1, -2) @ matrix
            rotations[name] = Rotation.from_matrix(matrix).as_quat().tolist()
        root = output["root_positions"][0].float().cpu().numpy()
        contacts = output["foot_contacts"][0].float().cpu().numpy()
        if not np.isfinite(root).all():
            raise ValueError("non-finite spatial motion")
        return motion[:, -40:], {
            "fps": self.fps,
            "seconds": self.horizon / self.fps,
            "root": root.tolist(),
            "rotations": rotations,
            "contacts": contacts.tolist(),
            "hip_height": self.hip_height,
            "generation_seconds": perf_counter() - started,
        }
