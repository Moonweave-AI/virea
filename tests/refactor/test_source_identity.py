from __future__ import annotations

from pathlib import PurePosixPath

import virea_contracts.source_identity as source_identity_module
from virea_contracts.source_identity import (
    content_tree_identity,
    distribution_source_identities,
)


def test_content_tree_identity_is_order_and_host_path_independent() -> None:
    forward = content_tree_identity(
        (("package\\worker.py", b"worker"), ("package/data.bin", b"data"))
    )
    reverse = content_tree_identity(
        (("package/data.bin", b"data"), ("package/worker.py", b"worker"))
    )

    assert forward == reverse
    assert forward["file_count"] == 2
    assert len(forward["sha256"]) == 64


def test_distribution_identity_hashes_only_installed_package_content(
    tmp_path, monkeypatch
) -> None:
    package = tmp_path / "package"
    metadata = tmp_path / "demo-1.0.dist-info"
    cache = package / "__pycache__"
    package.mkdir()
    metadata.mkdir()
    cache.mkdir()
    package.joinpath("__init__.py").write_bytes(b"installed")
    metadata.joinpath("METADATA").write_bytes(b"volatile metadata")
    cache.joinpath("worker.pyc").write_bytes(b"compiled")

    class Distribution:
        files = (
            PurePosixPath("package/__init__.py"),
            PurePosixPath("demo-1.0.dist-info/METADATA"),
            PurePosixPath("package/__pycache__/worker.pyc"),
            PurePosixPath("../../../Scripts/demo.exe"),
        )

        @staticmethod
        def locate_file(path):
            return tmp_path / str(path)

    monkeypatch.setattr(
        source_identity_module.metadata,
        "distribution",
        lambda _package_name: Distribution(),
    )

    observed = distribution_source_identities(["demo"])

    assert observed == {
        "demo": content_tree_identity((("package/__init__.py", b"installed"),))
    }
