from __future__ import annotations

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithoutTestWorkers(build_py):
    """Keep test Workers in source checkouts but out of distributable wheels."""

    def run(self) -> None:
        super().run()
        if getattr(self, "editable_mode", False):
            return
        package_root = Path(self.build_lib).resolve() / "virea_model_sdk"
        for module_name in ("fake.py", "fake_worker.py"):
            (package_root / module_name).unlink(missing_ok=True)


setup(cmdclass={"build_py": BuildPyWithoutTestWorkers})
