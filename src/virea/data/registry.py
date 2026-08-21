from __future__ import annotations

from importlib import import_module
from typing import Iterable

import yaml

from virea.data.adapters.base import BaseDatasetAdapter
from virea.data.types import DatasetRecord
from virea.paths import ProjectPaths, repo_root


def _import_object(path: str):
    module_name, _, attr = path.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid import path: {path}")
    module = import_module(module_name)
    return getattr(module, attr)


class DatasetRegistry:
    def __init__(self, records: dict[str, DatasetRecord], paths: ProjectPaths) -> None:
        self.records = records
        self.paths = paths
        self._adapters: dict[str, BaseDatasetAdapter] = {}

    @classmethod
    def default(
        cls, paths: ProjectPaths | None = None, data_source: str | None = None
    ) -> "DatasetRegistry":
        project_paths = paths or ProjectPaths(data_source=data_source)
        registry_path = repo_root() / "registries" / "datasets.yaml"
        with registry_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        records = {
            key: DatasetRecord.from_yaml(key, value)
            for key, value in payload.get("datasets", {}).items()
        }
        return cls(records=records, paths=project_paths)

    def keys(self) -> list[str]:
        return sorted(self.records)

    def iter_records(self) -> Iterable[DatasetRecord]:
        for key in self.keys():
            yield self.records[key]

    def adapter(self, dataset: str) -> BaseDatasetAdapter:
        if dataset not in self.records:
            raise KeyError(f"unknown dataset: {dataset}")
        if dataset not in self._adapters:
            record = self.records[dataset]
            adapter_cls = _import_object(record.adapter)
            raw_root = self.paths.raw_root / record.raw_dir
            self._adapters[dataset] = adapter_cls(record=record, raw_root=raw_root)
        return self._adapters[dataset]

    def to_dict(self) -> dict:
        return {
            "data_source": self.paths.data_source,
            "raw_root": self.paths.raw_root.as_posix(),
            "processed_root": self.paths.processed_root.as_posix(),
            "processing_version": self.paths.processing_version,
            "datasets": [record.to_dict() for record in self.iter_records()],
        }
