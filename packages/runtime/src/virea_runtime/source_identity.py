from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared backport.
    import tomli as tomllib

from virea_contracts.runtime import RuntimeSpec

from .backends.base import RuntimeBuildError, resolve_runtime_source

RUNTIME_SOURCE_IDENTITY_FILENAME = ".virea-runtime-source.json"
RUNTIME_SOURCE_IDENTITY_SCHEMA = "virea.runtime_source_identity.v1"

_PROJECT_METADATA_FILES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "MANIFEST.in",
    "README",
    "README.md",
    "README.rst",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
)
_IGNORED_SOURCE_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)


def _read_project(project_root: Path) -> dict[str, Any]:
    pyproject_path = project_root / "pyproject.toml"
    try:
        payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeBuildError(
            f"local Runtime project metadata is invalid: {pyproject_path}"
        ) from exc
    return payload


def local_runtime_projects(source: Path) -> tuple[tuple[str, Path], ...]:
    """Resolve the complete local-package closure consumed by ``uv sync``."""

    pending = [source.resolve(strict=True)]
    projects: dict[str, Path] = {}
    while pending:
        project_root = pending.pop()
        pyproject = _read_project(project_root)
        project_name = pyproject.get("project", {}).get("name")
        if not isinstance(project_name, str) or not project_name.strip():
            raise RuntimeBuildError(
                "local Runtime project has no package name: "
                f"{project_root / 'pyproject.toml'}"
            )
        project_name = project_name.strip()
        previous = projects.get(project_name)
        if previous is not None:
            if previous != project_root:
                raise RuntimeBuildError(
                    "local Runtime dependency closure repeats package name at "
                    f"different paths: {project_name}"
                )
            continue
        projects[project_name] = project_root

        sources = pyproject.get("tool", {}).get("uv", {}).get("sources", {})
        if not isinstance(sources, dict):
            continue
        for dependency_name, source_declaration in sources.items():
            declarations = (
                source_declaration
                if isinstance(source_declaration, list)
                else [source_declaration]
            )
            for declaration in declarations:
                if not isinstance(declaration, dict) or "path" not in declaration:
                    continue
                relative = declaration.get("path")
                if not isinstance(relative, str) or not relative.strip():
                    raise RuntimeBuildError(
                        f"local Runtime dependency {dependency_name!r} has no path"
                    )
                dependency_root = (project_root / relative).resolve(strict=False)
                if not (dependency_root / "pyproject.toml").is_file():
                    raise RuntimeBuildError(
                        "local Runtime dependency project is unavailable: "
                        f"{dependency_name} -> {dependency_root}"
                    )
                pending.append(dependency_root.resolve(strict=True))
    return tuple(sorted(projects.items()))


def _declared_source_roots(
    project_root: Path, pyproject: dict[str, Any]
) -> tuple[Path, ...]:
    setuptools = pyproject.get("tool", {}).get("setuptools", {})
    package_find = setuptools.get("packages", {}).get("find", {})
    where = package_find.get("where") if isinstance(package_find, dict) else None
    if isinstance(where, str):
        declarations = (where,)
    elif isinstance(where, list) and all(isinstance(item, str) for item in where):
        declarations = tuple(where)
    elif (project_root / "src").is_dir():
        declarations = ("src",)
    else:
        declarations = ()
    roots: list[Path] = []
    for declaration in declarations:
        candidate = (project_root / declaration).resolve(strict=False)
        try:
            candidate.relative_to(project_root)
        except ValueError as exc:
            raise RuntimeBuildError(
                "local Runtime package source escapes its project root: "
                f"{project_root} -> {candidate}"
            ) from exc
        if candidate.is_dir():
            roots.append(candidate)
    return tuple(dict.fromkeys(roots))


def _project_identity_files(
    project_name: str, project_root: Path
) -> tuple[tuple[str, Path], ...]:
    pyproject = _read_project(project_root)
    files: dict[str, Path] = {}
    for filename in _PROJECT_METADATA_FILES:
        candidate = project_root / filename
        if candidate.is_file():
            files[f"projects/{project_name}/{filename}"] = candidate
    for source_root in _declared_source_roots(project_root, pyproject):
        source_label = source_root.relative_to(project_root).as_posix()
        for candidate in source_root.rglob("*"):
            relative = candidate.relative_to(project_root)
            if any(
                part in _IGNORED_SOURCE_PARTS
                or part.endswith((".egg-info", ".dist-info"))
                for part in relative.parts
            ):
                continue
            if candidate.is_symlink():
                raise RuntimeBuildError(
                    "local Runtime source identity does not follow symlinks: "
                    f"{candidate}"
                )
            if candidate.is_file() and candidate.suffix not in {".pyc", ".pyo"}:
                files[
                    f"projects/{project_name}/{source_label}/"
                    f"{candidate.relative_to(source_root).as_posix()}"
                ] = candidate
    return tuple(sorted(files.items()))


def _digest_entries(entries: tuple[tuple[str, Path], ...]) -> str:
    digest = hashlib.sha256()
    for logical_path, path in entries:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RuntimeBuildError(
                f"cannot read Runtime source identity input: {path}"
            ) from exc
        encoded_path = logical_path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def runtime_source_identity(
    spec: RuntimeSpec,
    *,
    source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Return a path- and timestamp-independent identity for installed source."""

    source = resolve_runtime_source(spec, source_root=source_root)
    projects = (
        local_runtime_projects(source) if (source / "pyproject.toml").is_file() else ()
    )
    entries: dict[str, Path] = {}
    lockfile = (source / spec.lockfile).resolve(strict=True)
    entries[f"lock/{Path(spec.lockfile).as_posix()}"] = lockfile
    for project_name, project_root in projects:
        for logical_path, candidate in _project_identity_files(
            project_name, project_root
        ):
            previous = entries.get(logical_path)
            if previous is not None and previous != candidate:
                raise RuntimeBuildError(
                    f"Runtime source identity path collision: {logical_path}"
                )
            entries[logical_path] = candidate
    ordered_entries = tuple(sorted(entries.items()))
    return {
        "schema_version": RUNTIME_SOURCE_IDENTITY_SCHEMA,
        "runtime_id": spec.id,
        "project_package": spec.project_package,
        "project_version": spec.project_version,
        "runtime_core_epoch": spec.runtime_core_epoch,
        "sha256": _digest_entries(ordered_entries),
        "file_count": len(ordered_entries),
        "local_packages": [name for name, _root in projects],
    }


def runtime_source_identity_write_command(
    python_executable: str | Path,
    identity: dict[str, Any],
) -> tuple[str, ...]:
    """Build an atomic marker-write command executed by the new interpreter."""

    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    script = (
        "import json,os,pathlib,sys;"
        f"target=pathlib.Path(sys.prefix)/{RUNTIME_SOURCE_IDENTITY_FILENAME!r};"
        "temporary=target.with_name(target.name+'.'+str(os.getpid())+'.tmp');"
        "temporary.write_text(json.dumps(json.loads(sys.argv[1]),sort_keys=True,"
        "separators=(',',':')),encoding='utf-8');"
        "os.replace(temporary,target)"
    )
    return (str(python_executable), "-I", "-c", script, payload)
