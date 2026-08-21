from __future__ import annotations

import json
import zipfile
from pathlib import Path

from virea_bootstrap.detector import detect_machine
from virea_core.db import StateStore
from virea_core.ids import new_ulid
from virea_core.paths import VireaPaths

from .logging import redact


def build_support_bundle(
    paths: VireaPaths,
    *,
    max_jobs: int = 100,
    include_log_tails: bool = True,
) -> Path:
    """Create a local diagnostic bundle without prompts, tokens, or raw assets."""

    store = StateStore(paths)
    report = detect_machine(paths).model_dump(mode="json")
    jobs = store.list_jobs(limit=max_jobs)
    for job in jobs:
        job.pop("request_json", None)
        job["events"] = store.job_events(job["id"])
    bundle_id = new_ulid()
    target = paths.support_bundles / f"support-{bundle_id}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "summary.json",
            json.dumps(
                redact(
                    {
                        "schema_version": "virea.support_bundle.v1.0.0",
                        "bundle_id": bundle_id,
                        "machine": report,
                        "journal_mode": store.journal_mode(),
                        "jobs": jobs,
                    }
                ),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
        )
        if include_log_tails and paths.logs.exists():
            for log in sorted(paths.logs.rglob("*.log")):
                try:
                    payload = log.read_text(encoding="utf-8", errors="replace")[
                        -64_000:
                    ]
                except OSError:
                    continue
                relative = log.relative_to(paths.logs).as_posix()
                archive.writestr(f"logs/{relative}", payload)
    return target
