from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Literal

from virea.data.registry import DatasetRegistry
from virea.data.types import SampleRef
from virea.pipelines.artifacts import artifact_paths
from virea.pipelines.artifacts import motion_uid
from virea.pipelines.processing import ProcessingPipeline
from virea.reporting import sanitize_report_paths


@dataclass(frozen=True)
class ProcessingTask:
    dataset: str
    sample_id: str


@dataclass
class ProcessingResult:
    task: ProcessingTask
    status: Literal["passed", "failed", "skipped"]
    elapsed_sec: float
    frame_count: int = 0
    joint_count: int = 0
    files: dict[str, str] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class BatchReport:
    schema_version: str = "virea.batch_report.v0.1.0"
    data_source: str = ""
    processed_root: str = ""
    workers: int = 1
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_sec: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return sanitize_report_paths({
            "schema_version": self.schema_version,
            "data_source": self.data_source,
            "processed_root": self.processed_root,
            "workers": self.workers,
            "total": self.total,
            "processed": self.processed,
            "skipped": self.skipped,
            "failed": self.failed,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "passed": self.failed == 0,
            "items": self.items,
        })


def _worker_process_sample(payload: dict[str, Any]) -> dict[str, Any]:
    """Top-level worker for ProcessPoolExecutor (must be picklable)."""
    data_source = str(payload["data_source"])
    dataset = str(payload["dataset"])
    sample_id = str(payload["sample_id"])
    max_frames = payload.get("max_frames")
    skip_existing = bool(payload.get("skip_existing", False))
    force = bool(payload.get("force", False))

    try:
        registry = DatasetRegistry.default(data_source=data_source)
        pipeline = ProcessingPipeline(registry)
        adapter = registry.adapter(dataset)
        clip = adapter.load(sample_id, max_frames=max_frames)
        frame_count = int(
            clip.sample.frame_count
            or next(
                (int(v.shape[0]) for v in clip.motion.values() if hasattr(v, "shape") and len(v.shape) >= 1),
                1,
            )
        )
        if max_frames:
            frame_count = min(frame_count, int(max_frames))
        uid = motion_uid(dataset, sample_id, frame_count)
        paths = artifact_paths(registry.paths.processed_root, registry.paths.processing_version, dataset, uid)
        if skip_existing and not force and paths.exists():
            valid, _errors = pipeline.validate_existing(clip, paths)
            if valid:
                quality: dict[str, Any] = {}
                if paths.quality_report.exists():
                    try:
                        quality = json.loads(paths.quality_report.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                return {
                    "dataset": dataset,
                    "sample_id": sample_id,
                    "status": "skipped",
                    "frame_count": frame_count,
                    "quality": quality,
                    "files": {
                        "source_snapshot": paths.source_snapshot.relative_to(registry.paths.processed_root).as_posix(),
                        "canonical_manifest": paths.canonical_manifest.relative_to(registry.paths.processed_root).as_posix(),
                    },
                    "elapsed_sec": 0.0,
                }

        start = perf_counter()
        output = pipeline.process(dataset, sample_id, max_frames=max_frames)
        files = pipeline.persist(output)
        elapsed = perf_counter() - start
        return {
            "dataset": dataset,
            "sample_id": sample_id,
            "status": "passed",
            "frame_count": int(output.canonical.positions.shape[0]),
            "joint_count": len(output.canonical.joint_names),
            "quality": output.quality,
            "files": files,
            "elapsed_sec": round(elapsed, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "dataset": dataset,
            "sample_id": sample_id,
            "status": "failed",
            "error": sanitize_report_paths(str(exc)),
            "elapsed_sec": 0.0,
        }


class BatchPipeline:
    def __init__(self, registry: DatasetRegistry) -> None:
        self.registry = registry

    def collect_tasks(
        self,
        datasets: list[str] | None = None,
        query: str = "",
        limit_per_dataset: int | None = None,
    ) -> list[ProcessingTask]:
        keys = datasets or self.registry.keys()
        limit = limit_per_dataset if limit_per_dataset and limit_per_dataset > 0 else 1_000_000_000
        tasks: list[ProcessingTask] = []
        for dataset in keys:
            for sample in self.registry.adapter(dataset).discover(limit=limit, query=query):
                tasks.append(ProcessingTask(dataset=dataset, sample_id=sample.sample_id))
        return tasks

    def run(
        self,
        tasks: list[ProcessingTask],
        workers: int = 1,
        max_frames: int | None = None,
        continue_on_error: bool = True,
        skip_existing: bool = True,
        force: bool = False,
        on_progress: Callable[[ProcessingResult], None] | None = None,
    ) -> BatchReport:
        start = perf_counter()
        report = BatchReport(
            data_source=self.registry.paths.data_source,
            processed_root=".",
            workers=max(1, workers),
            total=len(tasks),
        )

        payloads = [
            {
                "data_source": self.registry.paths.data_source,
                "dataset": task.dataset,
                "sample_id": task.sample_id,
                "max_frames": max_frames,
                "skip_existing": skip_existing,
                "force": force,
            }
            for task in tasks
        ]

        if workers <= 1:
            for index, payload in enumerate(payloads, start=1):
                item = _worker_process_sample(payload)
                self._accumulate(report, item)
                if on_progress:
                    on_progress(self._item_to_result(tasks[index - 1], item))
                if item["status"] == "failed" and not continue_on_error:
                    break
        else:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_worker_process_sample, payload): (index, task)
                    for index, (payload, task) in enumerate(zip(payloads, tasks), start=1)
                }
                for future in as_completed(future_map):
                    index, task = future_map[future]
                    item = future.result()
                    self._accumulate(report, item)
                    if on_progress:
                        on_progress(self._item_to_result(task, item))
                    if item["status"] == "failed" and not continue_on_error:
                        for pending in future_map:
                            if not pending.done():
                                pending.cancel()
                        break

        report.elapsed_sec = perf_counter() - start
        return report

    @staticmethod
    def _accumulate(report: BatchReport, item: dict[str, Any]) -> None:
        report.items.append(item)
        status = item.get("status")
        if status == "passed":
            report.processed += 1
        elif status == "skipped":
            report.skipped += 1
        else:
            report.failed += 1

    @staticmethod
    def _item_to_result(task: ProcessingTask, item: dict[str, Any]) -> ProcessingResult:
        return ProcessingResult(
            task=task,
            status=item.get("status", "failed"),
            elapsed_sec=float(item.get("elapsed_sec", 0.0)),
            frame_count=int(item.get("frame_count", 0)),
            joint_count=int(item.get("joint_count", 0)),
            files=dict(item.get("files", {})),
            quality=dict(item.get("quality", {})),
            error=item.get("error"),
        )

    def run_from_samples(
        self,
        samples_by_dataset: dict[str, list[SampleRef]],
        **kwargs: Any,
    ) -> BatchReport:
        tasks = [
            ProcessingTask(dataset=dataset, sample_id=sample.sample_id)
            for dataset, samples in samples_by_dataset.items()
            for sample in samples
        ]
        return self.run(tasks, **kwargs)


def default_worker_count() -> int:
    count = os.cpu_count() or 4
    return max(1, min(count, 16))
