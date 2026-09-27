"""Check action constraints through the official CPU representation, without a GPU model."""

import argparse
from pathlib import Path
from types import SimpleNamespace

import torch
from ardy.motion_rep import ArdyMotionRep
from ardy.skeleton import CoreSkeleton27
from spatial.plan import SpatialPlan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    skeleton = CoreSkeleton27()
    motion = ArdyMotionRep(
        skeleton, 20, stats_path=str(args.model_dir / "stats/motion")
    )
    local = torch.eye(3).expand(8, skeleton.nbjoints, 3, 3).clone()
    roots = torch.tensor([1.35, 1.0, 0.15]).expand(8, 3).clone()
    history = motion(local, roots, to_normalize=True).unsqueeze(0)
    engine = SimpleNamespace(
        model=SimpleNamespace(skeleton=skeleton, motion_rep=motion),
        fps=20,
        horizon=8,
        hip_height=1.0,
    )
    for kind, position in [
        ("move_to", {"z": 2.0, "x": 1.0, "y": 0.0}),
        ("reach", {"z": 0.4, "x": 1.0, "y": 0.98}),
        ("sit", {"z": 0.0, "x": 0.0, "y": 0.5}),
    ]:
        plan = SpatialPlan(engine, dict(kind=kind, position=position), [1.35, 0, 0.15])
        assert plan.target.tolist() == [
            position[axis] for axis in ("x", "y", "z")
        ] or all(
            abs(plan.target[i] - position[axis]) < 1e-6
            for i, axis in enumerate(("x", "y", "z"))
        )
        for generated in (0, plan.frames - 8):
            conditions = plan.constraints(generated, history)
            features, mask = motion.create_conditions_from_constraints_batched(
                conditions, torch.tensor([56]), True, "cpu"
            )
            assert torch.isfinite(features).all() and mask.any()
        if kind == "reach":
            assert {"Hips", "LeftFoot", "RightFoot", "RightHand"} == set(
                conditions[0].joint_names
            )
        print(kind, "native constraints passed")


if __name__ == "__main__":
    main()
