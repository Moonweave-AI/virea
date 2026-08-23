from __future__ import annotations

import json

from virea_bootstrap.detector import detect_machine
from virea_bootstrap.reporting import record_machine_report
from virea_core.db import StateStore
from virea_core.paths import VireaPaths
from virea_model_pool import ModelCatalog, ModelPool

from ..common import plugin_root, registry_root, runtime_source_root


def run(args) -> int:
    reporter = getattr(args, "interactive_reporter", None)

    def progress(stage: str, message: str) -> None:
        if reporter is not None:
            reporter.progress(stage, message)

    progress("1/4", "Preparing the persistent directory layout...")
    paths = VireaPaths.discover(args.virea_home)
    paths.ensure_layout()
    # Resolve every product asset needed after setup now, so an incomplete
    # installation cannot be reported as successfully configured.
    registry_root()
    runtime_source_root()
    progress("2/4", "Synchronizing the local model catalog...")
    store = StateStore(paths)
    catalog = ModelCatalog.load(plugin_root())
    ModelPool(paths, store, catalog).sync_catalog()
    progress("3/4", "Detecting this device and its execution domains...")
    report = detect_machine(paths)
    progress("4/4", "Saving the reusable machine report...")
    record_machine_report(paths, report)
    payload = {
        "virea_home": str(paths.root),
        "database": str(paths.database),
        "models": sum(
            manifest.model.adapter_family != "fake-root-translation"
            for manifest in catalog.manifests()
        ),
        "machine_report": report.report_id,
    }
    if reporter is not None:
        reporter.result(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
