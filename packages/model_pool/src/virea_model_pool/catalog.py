from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import ValidationError

from .manifest import ModelPluginManifest


class CatalogError(ValueError):
    pass


class ModelCatalog:
    def __init__(self, manifests: Iterable[ModelPluginManifest]) -> None:
        items = tuple(manifests)
        by_id: dict[str, ModelPluginManifest] = {}
        for manifest in items:
            model_id = manifest.model.id
            if model_id in by_id:
                raise CatalogError(f"duplicate model plugin id: {model_id}")
            by_id[model_id] = manifest
        self._manifests = items
        self._by_id = by_id

    @classmethod
    def load(cls, root: str | Path) -> ModelCatalog:
        base = Path(root)
        if not base.is_dir():
            raise CatalogError(f"model catalog directory does not exist: {base}")
        files = sorted(base.glob("*/manifest.yaml"))
        if not files:
            raise CatalogError(f"model catalog contains no manifests: {base}")
        manifests: list[ModelPluginManifest] = []
        errors: list[str] = []
        for path in files:
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                manifests.append(ModelPluginManifest.model_validate(raw))
            except (OSError, yaml.YAMLError, ValidationError, TypeError) as exc:
                errors.append(f"{path}: {exc}")
        if errors:
            raise CatalogError("invalid model catalog:\n" + "\n".join(errors))
        return cls(manifests)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def get(self, model_id: str) -> ModelPluginManifest:
        try:
            return self._by_id[model_id]
        except KeyError as exc:
            raise KeyError(f"unknown model plugin: {model_id}") from exc

    def manifests(self) -> tuple[ModelPluginManifest, ...]:
        return self._manifests
