from __future__ import annotations

import os
import posixpath
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from virea_contracts.execution import ExecutionDomainKind
from virea_contracts.machine import ExecutionDomainReport

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_WINDOWS_DRIVE_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def is_host_routed_wsl(domain: ExecutionDomainReport | None) -> bool:
    return bool(
        domain and domain.kind is ExecutionDomainKind.WSL and not domain.is_host
    )


def wrap_domain_command(
    domain: ExecutionDomainReport | None,
    argv: Sequence[str],
    *,
    working_directory: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Build shell-free argv for one concrete execution domain."""

    command = tuple(str(value) for value in argv)
    if not command:
        raise ValueError("execution-domain command cannot be empty")
    if not is_host_routed_wsl(domain):
        return command
    assert domain is not None
    if not domain.launcher_argv:
        raise ValueError(f"execution domain {domain.id} has no WSL launcher")
    wrapped = [*domain.launcher_argv]
    if working_directory:
        _require_posix_absolute(working_directory, label="WSL working directory")
        wrapped.extend(("--cd", working_directory))
    # ``wsl.exe ... --`` may still route the remaining text through the
    # distribution's login shell.  Values such as Python constraints contain
    # ``<``/``>`` and must remain literal argv, so force WSL's exec mode.
    wrapped.append("--exec")
    if environment:
        assignments: list[str] = []
        for name, value in environment.items():
            if not _ENVIRONMENT_NAME.fullmatch(name):
                raise ValueError(f"invalid environment name: {name!r}")
            if "\0" in value:
                raise ValueError(f"environment value for {name} contains NUL")
            assignments.append(f"{name}={value}")
        wrapped.extend(("env", *assignments))
    wrapped.extend(command)
    return tuple(wrapped)


def map_host_path_to_domain(
    domain: ExecutionDomainReport | None,
    path: str | Path,
    *,
    timeout: float = 10.0,
) -> str:
    """Translate a host path only when crossing from Windows into WSL."""

    raw_path = os.fspath(path)
    if is_host_routed_wsl(domain):
        assert domain is not None
        unc_path = _same_distribution_unc_path(domain, raw_path)
        if unc_path is not None:
            return unc_path
        # Tests and remote controllers may construct the WSL command on a
        # non-Windows host.  A Windows drive path is already absolute in the
        # source domain; resolving it with POSIX pathlib would incorrectly
        # prefix the current checkout (for example ``/repo/D:/jobs``).
        if _WINDOWS_DRIVE_ABSOLUTE_PATH.match(raw_path):
            wslpath_input = raw_path.replace("\\", "/")
        else:
            host_path = Path(raw_path).expanduser().resolve(strict=False)
            wslpath_input = str(host_path).replace("\\", "/")
    else:
        host_path = Path(raw_path).expanduser().resolve(strict=False)
        return str(host_path)
    assert domain is not None
    # ``wsl.exe`` parses the Windows command line before invoking the Linux
    # program.  An unquoted ``C:\\path\\...`` argv can therefore reach
    # ``wslpath`` as ``C:path...``.  Forward slashes preserve the Windows
    # drive path across that boundary and are accepted by wslpath.
    command = wrap_domain_command(domain, ("wslpath", "-a", wslpath_input))
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            f"cannot map host path into execution domain {domain.id}: {exc}"
        ) from exc
    translated = completed.stdout.strip()
    if completed.returncode != 0 or not translated:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise RuntimeError(f"wslpath failed in execution domain {domain.id}: {detail}")
    return _require_posix_absolute(translated, label="mapped WSL path")


def _same_distribution_unc_path(
    domain: ExecutionDomainReport, value: str
) -> str | None:
    r"""Map ``\\wsl.localhost\distro\...`` without sending it to wslpath."""

    if "\0" in value:
        raise ValueError("host path contains NUL")
    normalized = value.replace("/", "\\")
    match = re.match(
        r"^\\\\(?:wsl\.localhost|wsl\$)\\([^\\]+)(?:\\(.*))?$",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    observed_distribution = match.group(1)
    expected_distribution = domain.distribution or ""
    if observed_distribution.casefold() != expected_distribution.casefold():
        raise ValueError(
            "WSL UNC path belongs to a different distribution: "
            f"path={observed_distribution!r}, execution_domain={expected_distribution!r}"
        )
    remainder = match.group(2) or ""
    parts = [part for part in remainder.split("\\") if part not in {"", "."}]
    if ".." in parts:
        raise ValueError("WSL UNC path cannot traverse above the distribution root")
    return "/" + "/".join(parts)


def managed_domain_path(
    domain: ExecutionDomainReport | None,
    *,
    collection: str,
    name: str,
    native_path: str | Path,
) -> str | Path:
    """Return a domain-local managed path, never a mounted Windows runtime."""

    if not is_host_routed_wsl(domain):
        return Path(native_path).expanduser().resolve(strict=False)
    assert domain is not None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name):
        raise ValueError(f"unsafe managed path component: {name!r}")
    if not re.fullmatch(r"[a-z][a-z0-9-]*", collection):
        raise ValueError(f"unsafe managed collection: {collection!r}")
    home = _require_posix_absolute(domain.virea_home, label="domain VIREA_HOME")
    return posixpath.join(home, collection, name)


def domain_python_path(
    domain: ExecutionDomainReport | None, prefix: str | Path
) -> str | Path:
    if is_host_routed_wsl(domain):
        rendered = _require_posix_absolute(str(prefix), label="WSL runtime prefix")
        return posixpath.join(rendered, "bin", "python")
    target = Path(prefix)
    if domain and domain.platform.startswith("win-"):
        return target / "Scripts" / "python.exe"
    if domain is None and os.name == "nt" and target.drive:
        return target / "Scripts" / "python.exe"
    return target / "bin" / "python"


def _require_posix_absolute(value: str, *, label: str) -> str:
    if "\0" in value:
        raise ValueError(f"{label} contains NUL")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be an absolute non-traversing POSIX path")
    return path.as_posix()
