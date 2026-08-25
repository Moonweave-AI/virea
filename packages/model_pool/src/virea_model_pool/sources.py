from __future__ import annotations

import shutil
import stat
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import redirect_stderr
from dataclasses import dataclass
from io import TextIOBase
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .manifest import ArchiveExtractionSpec, ArtifactSource


class ArtifactFetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArtifactTransferProgress:
    """A renderer-neutral snapshot of one model-artifact transfer."""

    artifact_id: str
    completed_bytes: int
    total_bytes: int | None
    bytes_per_second: float | None
    phase: str = "download"
    done: bool = False


ArtifactProgressCallback = Callable[[ArtifactTransferProgress], None]


class _DependencyProgressStream(TextIOBase):
    """Drop known dependency progress frames while preserving real stderr."""

    _MARKERS = (
        "Downloading bytes:",
        "Download complete:",
        "Reconstructing (incomplete total...):",
        "Reconstruction complete:",
    )

    def __init__(self, wrapped: Any) -> None:
        self._wrapped = wrapped
        self._discard_progress_whitespace = False
        self._lock = threading.RLock()

    def write(self, value: str) -> int:
        text = str(value)
        with self._lock:
            is_file_progress = "Fetching " in text and " files:" in text
            if is_file_progress or any(marker in text for marker in self._MARKERS):
                self._discard_progress_whitespace = True
                return len(text)
            if self._discard_progress_whitespace and not text.strip():
                return len(text)
            self._discard_progress_whitespace = False
            return self._wrapped.write(text)

    def flush(self) -> None:
        self._wrapped.flush()

    def isatty(self) -> bool:
        isatty = getattr(self._wrapped, "isatty", None)
        return bool(isatty()) if callable(isatty) else False

    def fileno(self) -> int:
        return int(self._wrapped.fileno())


def _snapshot_progress_class(
    artifact_id: str,
    progress: ArtifactProgressCallback | None,
) -> type:
    """Create a silent Hugging Face progress adapter scoped to one download.

    Hugging Face renders progress directly on stderr.  That output competes with
    VIREA's live terminal region and turns carriage-return refreshes into hundreds
    of retained lines on some Windows terminals and redirected streams.  Supplying
    a custom tqdm class keeps the dependency silent and forwards only structured
    snapshots to VIREA's own renderer.
    """

    try:
        from huggingface_hub.utils import tqdm as huggingface_tqdm
    except ImportError as exc:  # pragma: no cover - guarded by the caller import
        raise ArtifactFetchError(
            "install virea-model-pool[huggingface] to fetch Hugging Face artifacts"
        ) from exc

    class VireaSnapshotProgress(huggingface_tqdm):
        """Tqdm-compatible adapter that never writes its own terminal lines."""

        def __init__(
            self,
            iterable: Iterable[Any] | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            self._virea_description = str(kwargs.get("desc", ""))
            self._virea_started_at = time.monotonic()
            self._virea_initial = int(kwargs.get("initial", 0) or 0)
            self._virea_last_emitted_at = 0.0
            self._virea_closed = False
            self._virea_lock = threading.RLock()
            # `disable=True` is deliberate and local to this snapshot call.  It
            # is reliable even when a user explicitly enabled HF progress bars.
            kwargs["disable"] = True
            super().__init__(iterable, *args, **kwargs)

        def __iter__(self) -> Iterator[Any]:
            if self.iterable is None:
                return
            for value in self.iterable:
                yield value
                self.update(1)

        def update(self, n: int | float | None = 1) -> None:
            increment = max(0, int(n or 0))
            with self._virea_lock:
                # Disabled tqdm intentionally does not advance `n`, so the
                # adapter owns this counter while preserving tqdm's public shape.
                self.n += increment
                self._virea_emit(done=False)

        def refresh(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            with self._virea_lock:
                self._virea_emit(done=False)

        def set_description(
            self,
            desc: str | None = None,
            refresh: bool = True,
        ) -> None:
            del refresh
            with self._virea_lock:
                previous = self._virea_description
                completed = str(desc or "")
                if (
                    previous == "Downloading bytes" and completed == "Download complete"
                ) or (
                    previous.startswith("Reconstructing")
                    and completed == "Reconstruction complete"
                ):
                    self._virea_emit(done=True)
                self._virea_description = completed

        def set_postfix_str(self, *args: Any, **kwargs: Any) -> None:
            # Rate is calculated from the structured byte counter below.  Never
            # forward dependency-owned terminal formatting.
            del args, kwargs

        def close(self) -> None:
            with self._virea_lock:
                if not self._virea_closed:
                    self._virea_emit(done=True)
                    self._virea_closed = True
            super().close()

        def _virea_emit(self, *, done: bool) -> None:
            if progress is None:
                return
            if self._virea_description == "Downloading bytes":
                phase = "download"
                total: int | None = None
            elif self._virea_description.startswith("Reconstructing"):
                phase = "reconstruction"
                raw_total = getattr(self, "total", None)
                total = max(0, int(raw_total)) if raw_total is not None else None
            else:
                return
            now = time.monotonic()
            # The terminal renderer has its own slower log-mode limiter.  This
            # small guard also prevents callback pressure from download threads.
            if not done and now - self._virea_last_emitted_at < 0.1:
                return
            completed = max(0, int(self.n))
            elapsed = max(0.0, now - self._virea_started_at)
            transferred = max(0, completed - self._virea_initial)
            rate = transferred / elapsed if elapsed > 0 and transferred > 0 else None
            progress(
                ArtifactTransferProgress(
                    artifact_id=artifact_id,
                    completed_bytes=completed,
                    # Xet network bytes have no honest denominator; reconstructed
                    # local bytes do expose the dependency's monotonic total.
                    total_bytes=total,
                    bytes_per_second=rate,
                    phase=phase,
                    done=done,
                )
            )
            self._virea_last_emitted_at = now

    VireaSnapshotProgress.__name__ = "VireaSnapshotProgress"
    return VireaSnapshotProgress


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
    progress: ArtifactProgressCallback | None = None,
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
        # The custom tqdm class is the primary integration.  The stderr filter
        # is a narrow compatibility boundary for Hub/Xet versions that create
        # an internal reconstruction/file bar without honoring `tqdm_class`.
        with redirect_stderr(_DependencyProgressStream(sys.stderr)):
            snapshot_download(
                repo_id=source.repository or "",
                revision=source.revision,
                allow_patterns=list(source.allow_patterns) or None,
                local_dir=destination,
                cache_dir=cache_dir,
                tqdm_class=_snapshot_progress_class(source.id, progress),
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
