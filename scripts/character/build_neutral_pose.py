"""Derive a local relaxed posture from the installed, licensed SuSu idle capture."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from virea_compat.model_adapters import susu_body_hands_to_motion_ir

IDLE = "source/motion_generation/meta/xiu_joint_quat_vecs/Daiji_A_001_V001.npy"
IDLE_SHA256 = "a9af9015fcfada4548df7f8f52d136733e44ab2388f46ae16d63910c444c682e"


def build(home: Path) -> Path:
    candidates = []
    for manifest in sorted(
        (home / "model-store/snapshots").glob("*/internal-artifact-roots.json"),
        reverse=True,
    ):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for item in data.get("artifacts", []):
            if item["id"] == "sentiavatar-source":
                candidates.append(home / item["asset_locator"] / IDLE)
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError(
            "Install SentiAvatar source assets before preparing its idle posture"
        )
    if hashlib.sha256(source.read_bytes()).hexdigest() != IDLE_SHA256:
        raise ValueError("idle capture differs from the pinned source")
    # The pinned dictionary is pickle-based. Check its exact bytes before decoding.
    captured = np.load(source, allow_pickle=True).item()
    body = captured["body"].copy()
    body[:, :3] = (
        0  # Capture roots are absolute; this reference contains no locomotion.
    )
    converted = susu_body_hands_to_motion_ir(
        body,
        captured["left"],
        captured["right"],
        body_mean=np.zeros(153),
        body_std=np.ones(153),
        checkpoint_id="pinned-neutral-reference",
        hands_are_denormalized=True,
    )
    rotations = converted.canonical211[:, 3:].reshape(-1, 52, 4).astype(float)
    rotations *= np.where((rotations * rotations[:1]).sum(-1, keepdims=True) < 0, -1, 1)
    pose = rotations.mean(0)
    pose /= np.linalg.norm(pose, axis=-1, keepdims=True)
    output = home / "characters/neutral-pose.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "source": "SentiAvatar@71c61b05a0609a41c17aa146c9f4ee7778ebc649 / Daiji_A_001_V001.npy",
                "license": "SentiPulse Non-Commercial Source License v1.0",
                "licensor": "Shandong SentiPulse Technology Development Co., Ltd.",
                "modification": "Mean of 59 idle frames retargeted to VRM normalized humanoid rotations; no root displacement.",
                "rotations": {
                    name: np.round(row, 7).tolist()
                    for name, row in zip(
                        converted.motion_ir.actors[0].joint_names, pose, strict=True
                    )
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output.parent / "neutral-pose.LICENSE").write_bytes(
        source.parents[3].joinpath("LICENSE").read_bytes()
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    print(build(parser.parse_args().home.resolve()))
