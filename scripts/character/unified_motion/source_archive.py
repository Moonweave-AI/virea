"""Pinned GitHub archives for machines without developer tooling."""

import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def checkout_archive(url, revision, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive = destination.with_suffix(".download.zip")
    stage = destination.with_name(destination.name + ".extracting")
    urllib.request.urlretrieve(
        url.removesuffix(".git") + f"/archive/{revision}.zip", archive
    )
    stage.mkdir(exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            relative = Path(*Path(info.filename).parts[1:])
            target = (stage / relative).resolve()
            if (
                not target.is_relative_to(stage.resolve())
                or (info.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("Unsafe upstream archive entry")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as incoming, target.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            hashes[relative.as_posix()] = digest(target)
    (stage / ".virea-source.json").write_text(
        json.dumps({"revision": revision, "sha256": hashes}), encoding="utf-8"
    )
    stage.replace(destination)
    archive.unlink()


def verify_archive(source, revision):
    receipt = json.loads((source / ".virea-source.json").read_text(encoding="utf-8"))
    if receipt["revision"] != revision or not receipt["sha256"]:
        raise ValueError("Upstream archive revision differs")
    for relative, expected in receipt["sha256"].items():
        path = (source / relative).resolve()
        if not path.is_relative_to(source.resolve()) or digest(path) != expected:
            raise ValueError(f"Upstream archive modified: {relative}")
