# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["zstandard==0.25.0"]
# ///
"""Extract official runtime archives with traversal/link checks."""

import sys
import tarfile
import zipfile
from pathlib import Path


def unpack(archive, destination):
    destination = destination.resolve()
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source:
            for info in source.infolist():
                target = (destination / info.filename).resolve()
                if (
                    not target.is_relative_to(destination)
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe archive entry")
            source.extractall(destination)
    elif archive.suffix == ".zst":
        import zstandard

        temporary = archive.with_suffix(".tar")
        with archive.open("rb") as source, temporary.open("wb") as target:
            zstandard.ZstdDecompressor().copy_stream(source, target)
        try:
            with tarfile.open(temporary) as source:
                source.extractall(destination, filter="data")
        finally:
            temporary.unlink()
    else:
        with tarfile.open(archive) as source:
            source.extractall(destination, filter="data")


if __name__ == "__main__":
    unpack(Path(sys.argv[1]), Path(sys.argv[2]))
