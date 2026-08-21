from __future__ import annotations

import json

from virea_core import StateStore, VireaPaths

from ..retention import retention_report


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def run(args) -> int:
    paths = VireaPaths.discover(args.virea_home)
    store = StateStore(paths)
    if args.state_command == "migrate":
        store.migrate()
        with store.connect() as connection:
            versions = [
                dict(row)
                for row in connection.execute(
                    "SELECT version, applied_at FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
        _emit({"database": str(paths.database), "migrations": versions})
        return 0

    with store.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        counts = {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in sorted(tables)
            if not table.startswith("sqlite_")
        }
    if args.state_command == "inspect":
        _emit(
            {
                "virea_home": str(paths.root),
                "database": str(paths.database),
                "journal_mode": store.journal_mode(),
                "tables": counts,
            }
        )
        return 0
    if args.state_command == "gc":
        report = retention_report(
            paths,
            store,
            dry_run=args.dry_run,
            older_than_hours=args.older_than_hours,
        )
        _emit(report)
        return 2 if report["failures"] else 0
    raise ValueError(f"unsupported state command: {args.state_command}")
