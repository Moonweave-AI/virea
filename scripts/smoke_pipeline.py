from __future__ import annotations

import argparse
import json
from typing import Any

from virea.data.registry import DatasetRegistry
from virea.paths import AVAILABLE_DATA_SOURCES
from virea.pipelines.processed_preview import ProcessedPreviewPipeline
from virea.pipelines.raw_preview import RawPreviewPipeline
from virea.reporting import sanitize_report_paths


def smoke_source(data_source: str, max_frames: int, persist: bool) -> dict[str, Any]:
    registry = DatasetRegistry.default(data_source=data_source)
    raw_pipeline = RawPreviewPipeline(registry)
    processed_pipeline = ProcessedPreviewPipeline(registry)
    reports: list[dict[str, Any]] = []

    for dataset in registry.keys():
        adapter = registry.adapter(dataset)
        samples = adapter.discover(limit=1)
        if not samples:
            reports.append(
                {
                    "dataset": dataset,
                    "status": "failed",
                    "reason": f"no sample found in configured {data_source} raw root",
                }
            )
            continue

        sample_id = samples[0].sample_id
        raw = raw_pipeline.preview(dataset, sample_id, max_frames=max_frames)
        processed = processed_pipeline.preview(dataset, sample_id, max_frames=max_frames, persist=persist)
        raw_passed = raw.quality.get("status") == "passed"
        processed_passed = processed.quality.get("status") == "passed"
        reports.append(
            {
                "dataset": dataset,
                "sample_id": sample_id,
                "status": "passed" if raw_passed and processed_passed else "failed",
                "raw_shape": list(raw.positions.shape),
                "processed_shape": list(processed.positions.shape),
                "raw_quality": raw.quality,
                "processed_quality": processed.quality,
                "files_path_base": "configured_processed_root",
                "files": sanitize_report_paths(
                    processed.files,
                    relative_base=registry.paths.processed_root,
                ),
            }
        )

    return sanitize_report_paths({
        "data_source": data_source,
        "raw_root": f"data-source/{data_source}/raw",
        "raw_root_status": "configured" if registry.paths.raw_root.exists() else "missing",
        "processed_root": f"data-source/{data_source}/processed",
        "processed_root_status": "configured" if registry.paths.processed_root.exists() else "missing",
        "max_frames": max_frames,
        "persist": persist,
        "reports": reports,
        "passed": all(item.get("status") == "passed" for item in reports),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Run raw/processed preview smoke checks.")
    parser.add_argument("--data-source", choices=[*AVAILABLE_DATA_SOURCES, "all"], default="demo")
    parser.add_argument("--max-frames", type=int, default=8)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()

    sources = list(AVAILABLE_DATA_SOURCES) if args.data_source == "all" else [args.data_source]
    report = {
        "schema_version": "virea.smoke_report.v0.1.0",
        "sources": [smoke_source(source, max_frames=args.max_frames, persist=args.persist) for source in sources],
    }
    report["passed"] = all(source_report["passed"] for source_report in report["sources"])
    print(json.dumps(sanitize_report_paths(report), ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
