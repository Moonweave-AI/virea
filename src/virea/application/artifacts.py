"""Atomic, content-addressed performance artifacts with verified reads."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from virea_contracts.result import ArtifactRef


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def put(self, payload: bytes, *, media_type: str, name: str):
        digest = hashlib.sha256(payload).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / digest
        if not path.exists():
            with NamedTemporaryFile(dir=self.root, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            try:
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return ArtifactRef(
            name=name,
            uri=f"sha256:{digest}",
            media_type=media_type,
            byte_length=len(payload),
        ), digest

    def json(self, value, *, name):
        return self.put(
            json.dumps(
                value, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode(),
            media_type="application/json",
            name=name,
        )

    def read(self, reference: ArtifactRef, digest: str) -> bytes:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid artifact digest")
        if reference.uri != f"sha256:{digest}":
            raise ValueError("artifact reference and digest differ")
        path = (self.root / digest).resolve()
        if path.parent != self.root:
            raise ValueError("artifact is outside its store")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest or (
            reference.byte_length is not None and len(payload) != reference.byte_length
        ):
            raise ValueError("artifact integrity check failed")
        return payload
