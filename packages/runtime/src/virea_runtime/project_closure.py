from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared backport.
    import tomli as tomllib

from .backends.base import RuntimeBuildError


def _read_project(project_root: Path) -> dict[str, Any]:
    pyproject_path = project_root / "pyproject.toml"
    try:
        return tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeBuildError(
            f"local Runtime project metadata is invalid: {pyproject_path}"
        ) from exc


def local_runtime_projects(source: Path) -> tuple[tuple[str, Path], ...]:
    """Resolve local projects that ``uv sync`` must refresh together."""

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
