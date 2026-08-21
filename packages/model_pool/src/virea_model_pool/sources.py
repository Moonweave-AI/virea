from __future__ import annotations

import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .manifest import ArchiveExtractionSpec, ArtifactSource


class ArtifactFetchError(RuntimeError):
    pass


def _archive_member_path(name: str, *, strip_components: int) -> Path | None:
    normalized = name.replace("\\", "/")
    source = PurePosixPath(normalized)
    if (
        source.is_absolute()
        or ".." in source.parts
        or any(":" in part for part in source.parts)
    ):
        raise ArtifactFetchError(f"archive member path is unsafe: {name!r}")
    parts = tuple(part for part in source.parts if part not in {"", "."})
    if len(parts) <= strip_components:
        return None
    return Path(*parts[strip_components:])


def _extract_zip(archive: Path, destination: Path, *, strip_components: int) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in bundle.infolist():
            relative = _archive_member_path(
                info.filename, strip_components=strip_components
            )
            if relative is None:
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArtifactFetchError(
                    f"archive symbolic links are unsupported: {info.filename!r}"
                )
            members.append((info, relative))
        for info, relative in members:
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _extract_tar(archive: Path, destination: Path, *, strip_components: int) -> None:
    with tarfile.open(archive, mode="r:*") as bundle:
        members: list[tuple[tarfile.TarInfo, Path]] = []
        for info in bundle.getmembers():
            relative = _archive_member_path(
                info.name, strip_components=strip_components
            )
            if relative is None:
                continue
            if not (info.isdir() or info.isfile()):
                raise ArtifactFetchError(
                    f"archive member type is unsupported: {info.name!r}"
                )
            members.append((info, relative))
        for info, relative in members:
            target = destination / relative
            if info.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(info)
            if source is None:
                raise ArtifactFetchError(
                    f"archive member could not be read: {info.name!r}"
                )
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _extract_archive(destination: Path, spec: ArchiveExtractionSpec) -> None:
    root = destination.resolve(strict=True)
    archive = (root / spec.path).resolve(strict=True)
    try:
        archive.relative_to(root)
    except ValueError as exc:
        raise ArtifactFetchError("declared archive escaped its artifact root") from exc
    if not archive.is_file():
        raise ArtifactFetchError(f"declared archive is missing: {spec.path}")
    final_destination = (root / spec.destination).resolve(strict=False)
    try:
        final_destination.relative_to(root)
    except ValueError as exc:
        raise ArtifactFetchError(
            "archive destination escaped its artifact root"
        ) from exc
    final_destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".virea-unpack-", dir=root) as temporary:
        extraction_root = Path(temporary)
        if spec.format == "zip":
            _extract_zip(
                archive,
                extraction_root,
                strip_components=spec.strip_components,
            )
        else:
            _extract_tar(
                archive,
                extraction_root,
                strip_components=spec.strip_components,
            )
        for child in extraction_root.iterdir():
            target = final_destination / child.name
            if target.exists():
                raise ArtifactFetchError(
                    f"archive extraction would overwrite an existing path: {target}"
                )
            shutil.move(str(child), target)
    if spec.remove_archive:
        archive.unlink()


def fetch_source(
    source: ArtifactSource,
    destination: Path,
    *,
    cache_dir: Path | None = None,
) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    if source.kind == "manual":
        raise ArtifactFetchError(
            f"artifact {source.id} requires manual placement; no automatic source is declared"
        )
    if source.kind == "local":
        origin = Path(source.local_path or "").expanduser().resolve(strict=False)
        if not origin.exists():
            raise ArtifactFetchError(f"local artifact source does not exist: {origin}")
        if origin.is_dir():
            for child in origin.iterdir():
                target = destination / child.name
                if child.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=False)
                else:
                    shutil.copy2(child, target)
        else:
            shutil.copy2(origin, destination / origin.name)
    elif source.kind == "https":
        url = source.url or ""
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ArtifactFetchError(
                "HTTPS artifact source must use an absolute https URL"
            )
        if parsed.username is not None or parsed.password is not None:
            raise ArtifactFetchError(
                "HTTPS artifact source URL must not contain credentials"
            )
        filename = Path(parsed.path).name or f"{source.id}.download"
        target = destination / filename
        temporary = target.with_suffix(target.suffix + ".part")
        with (
            urllib.request.urlopen(url, timeout=60) as response,
            temporary.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle)
        temporary.replace(target)
    elif source.kind == "huggingface":
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise ArtifactFetchError(
                "install virea-model-pool[huggingface] to fetch Hugging Face artifacts"
            ) from exc
        snapshot_download(
            repo_id=source.repository or "",
            revision=source.revision,
            allow_patterns=list(source.allow_patterns) or None,
            local_dir=destination,
            cache_dir=cache_dir,
        )
    else:
        raise ArtifactFetchError(f"unsupported source kind: {source.kind}")
    for extraction in source.unpack:
        _extract_archive(destination, extraction)
    files = sorted(path for path in destination.rglob("*") if path.is_file())
    validate_source_files(source, destination, files)
    return files


def validate_source_files(
    source: ArtifactSource,
    destination: Path,
    files: list[Path] | None = None,
) -> None:
    candidates = files or sorted(
        path for path in destination.rglob("*") if path.is_file()
    )
    relative = {path.relative_to(destination).as_posix(): path for path in candidates}
    missing = [name for name in source.expected_files if name not in relative]
    if missing:
        raise ArtifactFetchError(
            f"artifact {source.id} is missing expected files: {missing}"
        )
    if source.expected_total_bytes is not None:
        total = sum(path.stat().st_size for path in candidates)
        if total != source.expected_total_bytes:
            raise ArtifactFetchError(
                f"artifact {source.id} size mismatch: expected "
                f"{source.expected_total_bytes}, got {total}"
            )
