from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, production_e2e_evidence_validator, real_e2e_validator
from .commands import doctor, generate, model, serve, setup, state, support, wizard

_LEGACY_COMMANDS = {"process", "build-demo"}


def _requires_explicit_virea_home(args: argparse.Namespace) -> bool:
    """Return whether a CLI invocation can create or access persistent data.

    ``VIREA_HOME`` owns model assets, isolated Runtimes, SQLite state, results,
    and logs.  Falling back to the operating system's application-data directory
    is reasonable for a small read-only probe, but it is unsafe as an implicit
    destination for model downloads.  Keep the pure catalog commands and an
    unrecorded ``doctor`` usable before a user has selected a data volume.
    """

    if args.command in {"setup", "generate", "serve", "support", "state"}:
        return True
    if args.command == "doctor":
        return bool(args.record)
    return args.command == "model" and args.model_command in {
        "install",
        "verify",
        "remove",
        "repair",
        "gc",
    }


def _has_explicit_virea_home(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "virea_home", None) or os.getenv("VIREA_HOME"))


def _require_explicit_virea_home(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if _requires_explicit_virea_home(args) and not _has_explicit_virea_home(args):
        parser.error(
            "persistent VIREA data needs an explicit location: pass "
            "--virea-home PATH or set VIREA_HOME to a directory on a "
            "volume with sufficient capacity; model assets are not stored "
            "implicitly in LOCALAPPDATA"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="virea", description="VIREA local motion generation"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser("setup", help="initialize user-local VIREA state")
    setup_parser.add_argument("--virea-home", default=None)
    setup_parser.set_defaults(func=setup.run)

    doctor_parser = sub.add_parser(
        "doctor", help="inspect machine capabilities without importing model code"
    )
    doctor_parser.add_argument("--virea-home", default=None)
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument("--record", action="store_true")
    doctor_parser.add_argument("--explain", action="store_true")
    doctor_parser.add_argument("--repair-plan", action="store_true")
    doctor_parser.set_defaults(func=doctor.run)

    model_parser = sub.add_parser("model", help="inspect the model plugin catalog")
    model_sub = model_parser.add_subparsers(dest="model_command", required=True)
    model_list = model_sub.add_parser("list")
    model_list.add_argument("--json", action="store_true")
    model_list.set_defaults(func=model.run)
    model_search = model_sub.add_parser("search")
    model_search.add_argument("query", nargs="?", default="")
    model_search.add_argument("--json", action="store_true")
    model_search.set_defaults(func=model.run)
    model_info = model_sub.add_parser("info")
    model_info.add_argument("model_id")
    model_info.set_defaults(func=model.run)
    model_install = model_sub.add_parser("install")
    model_install.add_argument("model_id")
    model_install.add_argument("--apply", action="store_true")
    model_install.add_argument("--accepted-license", action="store_true")
    model_install.add_argument("--execution-domain", default=None)
    model_install.add_argument("--runtime", dest="runtime_variant", default=None)
    model_install.add_argument("--resource-profile", default=None)
    model_install.add_argument(
        "--artifact-root",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="reuse one explicit external artifact directory without copying",
    )
    model_install.add_argument(
        "--artifact-revision",
        action="append",
        default=[],
        metavar="ID=REVISION",
        help="confirm the pinned manifest revision for an external artifact root",
    )
    model_install.add_argument(
        "--validation-prompt",
        default=None,
    )
    model_install.add_argument("--validation-seconds", type=float, default=None)
    model_install.add_argument("--validation-seed", type=int, default=None)
    model_install.add_argument("--validation-timeout", type=float, default=None)
    model_install.add_argument("--virea-home", default=None)
    model_install.set_defaults(func=model.run)
    model_verify = model_sub.add_parser("verify")
    model_verify.add_argument("model_id")
    model_verify.add_argument("--virea-home", default=None)
    model_verify.set_defaults(func=model.run)
    model_remove = model_sub.add_parser("remove")
    model_remove.add_argument("model_id")
    model_remove.add_argument("--apply", action="store_true")
    model_remove.add_argument("--virea-home", default=None)
    model_remove.set_defaults(func=model.run)
    model_repair = model_sub.add_parser("repair")
    model_repair.add_argument("model_id")
    model_repair.add_argument("--apply", action="store_true")
    model_repair.add_argument("--accepted-license", action="store_true")
    model_repair.add_argument("--execution-domain", default=None)
    model_repair.add_argument("--runtime", dest="runtime_variant", default=None)
    model_repair.add_argument("--resource-profile", default=None)
    model_repair.add_argument(
        "--artifact-root",
        action="append",
        default=[],
        metavar="ID=PATH",
    )
    model_repair.add_argument(
        "--artifact-revision",
        action="append",
        default=[],
        metavar="ID=REVISION",
    )
    model_repair.add_argument(
        "--validation-prompt",
        default=None,
    )
    model_repair.add_argument("--validation-seconds", type=float, default=None)
    model_repair.add_argument("--validation-seed", type=int, default=None)
    model_repair.add_argument("--validation-timeout", type=float, default=None)
    model_repair.add_argument("--virea-home", default=None)
    model_repair.set_defaults(func=model.run)
    model_gc = model_sub.add_parser("gc")
    model_gc_mode = model_gc.add_mutually_exclusive_group()
    model_gc_mode.add_argument("--apply", dest="dry_run", action="store_false")
    model_gc_mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    model_gc.set_defaults(dry_run=True)
    model_gc.add_argument("--older-than-hours", type=float, default=168.0)
    model_gc.add_argument("--virea-home", default=None)
    model_gc.set_defaults(func=model.run)
    model_bundle = model_sub.add_parser("bundle")
    model_bundle.add_argument("bundle_id", nargs="?", default=None)
    model_bundle.set_defaults(func=model.run)

    state_parser = sub.add_parser("state", help="inspect and migrate local state")
    state_sub = state_parser.add_subparsers(dest="state_command", required=True)
    state_inspect = state_sub.add_parser("inspect")
    state_inspect.add_argument("--virea-home", default=None)
    state_inspect.set_defaults(func=state.run)
    state_migrate = state_sub.add_parser("migrate")
    state_migrate.add_argument("--virea-home", default=None)
    state_migrate.set_defaults(func=state.run)
    state_gc = state_sub.add_parser("gc")
    state_gc_mode = state_gc.add_mutually_exclusive_group()
    state_gc_mode.add_argument("--apply", dest="dry_run", action="store_false")
    state_gc_mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    state_gc.set_defaults(dry_run=True)
    state_gc.add_argument("--older-than-hours", type=float, default=168.0)
    state_gc.add_argument("--virea-home", default=None)
    state_gc.set_defaults(func=state.run)

    generate_parser = sub.add_parser(
        "generate", help="run a model through the local worker protocol"
    )
    generate_parser.add_argument("--model", default=None)
    generate_parser.add_argument("--task", default="text_to_motion")
    generate_parser.add_argument("--prompt", default="")
    generate_parser.add_argument("--seconds", type=float, default=4.0)
    generate_parser.add_argument("--fps", type=float, default=20.0)
    generate_parser.add_argument("--seed", type=int, default=42)
    generate_parser.add_argument("--denoise-steps", type=int, default=None)
    generate_parser.add_argument("--idempotency-key", default=None)
    generate_parser.add_argument("--execution-domain", default=None)
    generate_parser.add_argument("--runtime", dest="runtime_variant", default=None)
    generate_parser.add_argument("--resource-profile", default=None)
    generate_parser.add_argument(
        "--timeout",
        type=float,
        default=1800.0,
        help="end-to-end wait and Worker inference timeout in seconds (max 7200)",
    )
    generate_parser.add_argument("--virea-home", default=None)
    generate_parser.set_defaults(func=generate.run)

    validate_parser = sub.add_parser(
        "validate-real-e2e",
        help=(
            "validate persisted real installation, generation, and artifact evidence"
        ),
    )
    validate_parser.add_argument("--virea-home", type=Path, required=True)
    validate_selector = validate_parser.add_mutually_exclusive_group()
    validate_selector.add_argument("--job-id")
    validate_selector.add_argument("--result-id")
    validate_parser.add_argument(
        "--expect",
        choices=("success", "cancelled", "recovered"),
        default="success",
    )
    validate_parser.add_argument("--plugin-root", type=Path, default=None)
    validate_parser.set_defaults(func=real_e2e_validator.run)

    browser_evidence_parser = sub.add_parser(
        "validate-production-e2e-evidence",
        help="bind real browser playback to one persisted production model chain",
    )
    browser_evidence_parser.add_argument("--virea-home", type=Path, required=True)
    browser_evidence_parser.add_argument("--observation", type=Path, required=True)
    browser_evidence_parser.add_argument("--output", type=Path, default=None)
    browser_evidence_parser.add_argument("--plugin-root", type=Path, default=None)
    browser_evidence_parser.set_defaults(func=production_e2e_evidence_validator.run)

    serve_parser = sub.add_parser(
        "serve", help="start the local control plane and compatibility preview API"
    )
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.add_argument(
        "--shutdown-on-stdin-eof",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    serve_parser.add_argument("--virea-home", default=None)
    serve_parser.add_argument(
        "--data-source",
        choices=("full", "demo"),
        default=None,
        help=(
            "deprecated compatibility option for legacy preview routes; "
            "prefer VIREA_DATA_SOURCE or a per-request data_source parameter"
        ),
    )
    serve_parser.set_defaults(func=serve.run)

    support_parser = sub.add_parser("support", help="emit a local diagnostic summary")
    support_parser.add_argument("--virea-home", default=None)
    support_parser.add_argument("--jobs", type=int, default=20)
    support_parser.set_defaults(func=support.run)
    return parser


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in _LEGACY_COMMANDS:
        from virea.cli import main as legacy_main

        legacy_main()
        return
    if len(sys.argv) == 1:
        raise SystemExit(wizard.run())
    parser = build_parser()
    args = parser.parse_args()
    _require_explicit_virea_home(parser, args)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
