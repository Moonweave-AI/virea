from __future__ import annotations

import json

from virea_core.db import StateStore
from virea_core.paths import VireaPaths


def run(args) -> int:
    paths = VireaPaths.discover(args.virea_home)
    store = StateStore(paths)
    payload = {
        "schema_version": "virea.support_summary.v1.0.0",
        "virea_home": str(paths.root),
        "journal_mode": store.journal_mode(),
        "jobs": store.list_jobs(limit=args.jobs),
        "active_workers": [],
        "tokens": "not_collected",
        "prompts": "not_collected",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
