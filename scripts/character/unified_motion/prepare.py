"""Download only inference assets from pinned official releases; write worker settings.

Run with the selected worker's Python environment. Existing files are verified,
never silently replaced. Model and training-dataset licenses remain applicable.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .provenance import verify_source

SOURCES = {
    "motioncraft": (
        "https://github.com/cure-lab/MotionCraft.git",
        "a72b1327b5ffefa4f1a9e3ffa2427b9b83f840f9",
    ),
    "syntalker": (
        "https://github.com/RobinWitch/SynTalker.git",
        "4301ada4d5affe6a77beaf5f8e19bc1904d3ea41",
    ),
}
ST_REVISION = "e47ee9ed19f1043fed46d8bd3be7d57dcbb75f87"
ST_FILES = {
    "ckpt/beatx_1-30_amass_h3d_diffusion/last_600.bin": "7ebef33ac1f131420de05565cd9927313446eadc3bd5a2ab4cc436a09da368bf",
    "ckpt/beatx_1-30_amass_h3d_rvqvae/RVQVAE_hands/net_300000.pth": "19cc2cbb68371a91c4107dce073d25feda56af1acc2b8ce938120738d423c8d6",
    "ckpt/beatx_1-30_amass_h3d_rvqvae/RVQVAE_lower/net_300000.pth": "8de38c6be9c927a5d6df1c4e03489d704b961cf6f4777dcf31379381192cfcfe",
    "ckpt/beatx_1-30_amass_h3d_rvqvae/RVQVAE_upper/net_300000.pth": "25657855dace8008f769fd6675fdd595a7a3464a0b4ea1def294ed171bc55ca2",
    "ckpt/beatx_1-30_amass_h3d_tmr/text_epoch=299.ckpt": "e8ac085ed2edf47ed6f20b3ae5ec8c89b98e90237315663f8c17c9f69934b3ed",
    "ckpt/distilbert-base-uncased/pytorch_model.bin": "1df15ef6ca103a52df977eec51dd1058d5f6a2fdf5b3ae5d2e7fc225e9801143",
}


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checkout(backend, destination):
    url, revision = SOURCES[backend]
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--no-checkout",
                "--filter=blob:none",
                url,
                str(destination),
            ],
            check=True,
            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        )
        subprocess.run(
            ["git", "-C", str(destination), "checkout", "--detach", revision],
            check=True,
            env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"},
        )
    verify_source(destination, revision)


def prepare(backend, root, device):
    root.mkdir(parents=True, exist_ok=True)
    source = root / (
        "motioncraft-source/source" if backend == "motioncraft" else "source"
    )
    checkout(backend, source)
    if backend == "syntalker":
        from huggingface_hub import snapshot_download

        assets = root / "assets"
        snapshot_download(
            "robinwitch/SynTalker",
            revision=ST_REVISION,
            local_dir=assets,
            allow_patterns=[
                *ST_FILES,
                "ckpt/distilbert-base-uncased/*.json",
                "ckpt/distilbert-base-uncased/vocab.txt",
            ],
            max_workers=4,
        )
        for relative, expected in ST_FILES.items():
            if sha256(assets / relative) != expected:
                raise ValueError(f"Official asset hash mismatch: {relative}")
        shutil.copytree(source / "mean_std", assets / "mean_std", dirs_exist_ok=True)
        settings = dict(
            backend=backend, source=str(source), assets=str(assets), device=device
        )
        files = list(ST_FILES) + [
            str(p.relative_to(assets)) for p in (assets / "mean_std").glob("*.npy")
        ]
        receipt = dict(
            source_revision=SOURCES[backend][1],
            weights_revision=ST_REVISION,
            sha256={f: sha256(assets / f) for f in files},
        )
    else:
        import gdown

        checkpoints = root / "motioncraft-task-checkpoints"
        weight = (
            checkpoints / "S2G_t2m_no_face_loss_l8_latentdim128_ffsize512/epoch_24.pth"
        )
        weight.parent.mkdir(parents=True, exist_ok=True)
        if not weight.exists():
            temporary = weight.with_suffix(".download")
            if not gdown.download(
                id="1oyL8sSrIf2Hz3PUMmrMAyt-bVvqFkLpL",
                output=str(temporary),
                quiet=False,
            ):
                raise RuntimeError(
                    "Official S2G download failed; see MotionCraft release instructions"
                )
            temporary.replace(weight)
        text_weight = (
            checkpoints / "t2m_no_face_loss_l4_latentdim128_ffsize512/epoch_12.pth"
        )
        text_weight.parent.mkdir(parents=True, exist_ok=True)
        if not text_weight.exists():
            temporary = text_weight.with_suffix(".download")
            if not gdown.download(
                id="1wexWc5TQ_ixQ6SsEwrgGOCmdghjUZWt8",
                output=str(temporary),
                quiet=False,
            ):
                raise RuntimeError(
                    "Official T2M download failed; see MotionCraft release instructions"
                )
            temporary.replace(text_weight)
        clip = root / "openai-clip-vit-b32/ViT-B-32.pt"
        clip.parent.mkdir(parents=True, exist_ok=True)
        expected = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"
        if not clip.exists():
            temporary = clip.with_suffix(".download")
            urllib.request.urlretrieve(
                f"https://openaipublic.azureedge.net/clip/models/{expected}/ViT-B-32.pt",
                temporary,
            )
            temporary.replace(clip)
        if sha256(clip) != expected:
            raise ValueError("CLIP checkpoint hash mismatch")
        settings = dict(
            backend=backend,
            memory_strategy="cpu" if device == "cpu" else "cuda_full",
            artifacts={
                "motioncraft-source": str(source.parent),
                "motioncraft-task-checkpoints": str(checkpoints),
                "openai-clip-vit-b32": str(clip.parent),
            },
        )
        receipt = dict(
            source_revision=SOURCES[backend][1],
            weights_source={
                "S2G": "google-drive:1oyL8sSrIf2Hz3PUMmrMAyt-bVvqFkLpL",
                "T2M": "google-drive:1wexWc5TQ_ixQ6SsEwrgGOCmdghjUZWt8",
            },
            sha256={
                "S2G": sha256(weight),
                "T2M": sha256(text_weight),
                "CLIP": sha256(clip),
            },
            note="Task checkpoint SHA256 values are local receipts, not upstream-published checksums",
        )
    (root / "asset-receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    output = root / "worker.json"
    output.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=SOURCES)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    prepare(args.backend, args.root.resolve(), args.device)


if __name__ == "__main__":
    main()
