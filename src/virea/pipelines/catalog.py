from __future__ import annotations

from collections import Counter
from pathlib import Path

from virea.data.registry import DatasetRegistry
from virea.reporting import sanitize_report_paths


class CatalogPipeline:
    def __init__(self, registry: DatasetRegistry) -> None:
        self.registry = registry

    def summary(self) -> dict:
        data_source = str(self.registry.paths.data_source)
        raw_root_token = f"data-source/{data_source}/raw"
        processed_root_token = f"data-source/{data_source}/processed"
        datasets = []
        for record in self.registry.iter_records():
            root = self.registry.paths.raw_root / record.raw_dir
            extensions: Counter[str] = Counter()
            top_dirs: Counter[str] = Counter()
            file_count = 0
            if root.exists():
                for path in root.rglob("*"):
                    if not path.is_file():
                        continue
                    file_count += 1
                    extensions[path.suffix.lower() or "<none>"] += 1
                    try:
                        top_dirs[path.relative_to(root).parts[0]] += 1
                    except Exception:
                        top_dirs["."] += 1
            datasets.append(
                {
                    **record.to_dict(),
                    "raw_root": Path(record.raw_dir).as_posix(),
                    "raw_path_base": raw_root_token,
                    "exists": root.exists(),
                    "file_count": file_count,
                    "extensions": dict(extensions.most_common(16)),
                    "top_dirs": dict(top_dirs.most_common(16)),
                }
            )
        return sanitize_report_paths({
            "data_source": data_source,
            "raw_root": raw_root_token,
            "raw_root_status": "configured" if self.registry.paths.raw_root.exists() else "missing",
            "processed_root": processed_root_token,
            "processed_root_status": "configured" if self.registry.paths.processed_root.exists() else "missing",
            "datasets": datasets,
        })
