from __future__ import annotations

import os
from collections.abc import Mapping

# These variables can make an explicitly selected interpreter load the parent
# process's standard library or site paths.  uv-managed Windows launchers set
# PYTHONHOME and UV_INTERNAL__PYTHONHOME for their own interpreter, so both must
# be removed before launching a different isolated runtime Python.
_FOREIGN_PYTHON_ENVIRONMENT = frozenset(
    {
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONPLATLIBDIR",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "UV_INTERNAL__PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT",
        "VIRTUAL_ENV",
        "__PYVENV_LAUNCHER__",
    }
)


def sanitized_python_environment(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment safe for an explicitly selected Python runtime."""

    environment = dict(os.environ if source is None else source)
    for name in tuple(environment):
        if name.upper() in _FOREIGN_PYTHON_ENVIRONMENT:
            environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONUTF8"] = "1"
    return environment
