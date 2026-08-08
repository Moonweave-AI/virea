from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import uvicorn

from virea.data.registry import DatasetRegistry
from virea.paths import AVAILABLE_DATA_SOURCES, ProjectPaths
from virea.pipelines.batch import BatchPipeline, default_worker_count


def _registry(data_source: str) -> DatasetRegistry:
    return DatasetRegistry.default(data_source=data_source)


# ---------------------------------------------------------------------------
# Quality report formatting
# ---------------------------------------------------------------------------


def _format_quality_table(quality: dict, sample_id: str = "") -> str:
    """Format a quality report dict as a human-readable error table."""
    lines: list[str] = []
    if sample_id:
        lines.append(f"  Sample: {sample_id}")
    lines.append(f"  Status: {quality.get('status', 'unknown')} | "
                 f"Frames: {quality.get('frame_count', '?')} | "
                 f"Joints: {quality.get('joint_count', '?')}")
    bbox_min = quality.get("bbox_min", [])
    bbox_max = quality.get("bbox_max", [])
    if bbox_min and bbox_max:
        lines.append(f"  BBox: [{', '.join(f'{v:.3f}' for v in bbox_min)}]"
                     f" -> [{', '.join(f'{v:.3f}' for v in bbox_max)}]")

    gc = quality.get("ground_contact")
    if gc and gc.get("total_frames"):
        lines.append("")
        lines.append("  [Ground Contact]")
        lines.append(f"    Floating:    {gc['floating_frames']:>5}/{gc['total_frames']} "
                     f"({gc['floating_ratio'] * 100:5.1f}%)")
        lines.append(f"    Penetrating: {gc['penetrating_frames']:>5}/{gc['total_frames']} "
                     f"({gc['penetrating_ratio'] * 100:5.1f}%)")
        lines.append(f"    Foot height: [{gc.get('min_foot_height_m', 0):.4f}m, "
                     f"{gc.get('max_foot_height_m', 0):.4f}m]")

    vel = quality.get("velocity")
    if vel and vel.get("mean_speed_m_s") is not None:
        lines.append("")
        lines.append("  [Velocity]")
        lines.append(f"    Mean speed: {vel['mean_speed_m_s']:.3f} m/s | "
                     f"Max: {vel['max_speed_m_s']:.3f} m/s")
        if vel.get("mean_accel_m_s2") is not None:
            lines.append(f"    Mean accel: {vel['mean_accel_m_s2']:.3f} m/s2 | "
                         f"Max: {vel['max_accel_m_s2']:.3f} m/s2")
        else:
            lines.append("    Acceleration: insufficient frames (requires at least 3)")
        lines.append(f"    Jittery joints: {vel['jittery_joints']} "
                     f"(threshold: {vel['jitter_threshold_m_s']} m/s)")

    rde = quality.get("retarget_direction_error")
    if rde:
        lines.append("")
        if rde.get("status") == "incompatible_shapes":
            lines.append(f"  [Retarget] incompatible shapes "
                         f"{rde.get('source_shape')} vs {rde.get('target_shape')}")
        else:
            lines.append("  === RETARGET QUALITY ===")
            lines.append("  [Per-Bone Direction Error (rotation preservation)]")
            max_pct = rde.get('max_as_pct_of_full_rotation', 0)
            mean_pct = rde.get('overall_mean_deg', 0) / 360.0 * 100.0
            lines.append(f"    Mean: {rde.get('overall_mean_rad', 0):.6f} rad "
                         f"({rde.get('overall_mean_deg', 0):.4f} deg, {mean_pct:.4f}%)")
            lines.append(f"    Max:  {rde.get('overall_max_rad', 0):.6f} rad "
                         f"({rde.get('overall_max_deg', 0):.4f} deg, {max_pct:.4f}%)")

    per_bone = quality.get("per_bone_direction_errors")
    if per_bone:
        lines.append("")
        lines.append("  [Per-Bone Direction Errors] (sorted by max)")
        lines.append(f"  {'Bone':<22} {'Mean(rad)':>11} {'Max(rad)':>11} {'Std(rad)':>11} {'MaxDeg':>8}")
        lines.append(f"  {'-' * 68}")
        for be in per_bone[:22]:
            lines.append(
                f"  {be['bone']:<22} "
                f"{be['mean_rad']:>11.6f} "
                f"{be['max_rad']:>11.6f} "
                f"{be['std_rad']:>11.6f} "
                f"{be['max_deg']:>8.4f}"
            )

    return "\n".join(lines)


def _print_quality(quality: dict, sample_id: str = "") -> None:
    print(f"\n{'=' * 70}")
    print(_format_quality_table(quality, sample_id))
    print(f"{'=' * 70}\n")


# ---------------------------------------------------------------------------
# Dataset-level aggregate quality report
# ---------------------------------------------------------------------------


def _aggregate_dataset_quality(items: list[dict[str, Any]]) -> str:
    """Produce a per-dataset aggregate error table + top-10 worst samples."""
    passed_items = [it for it in items if it.get("quality") and it["quality"].get("status")]
    if not passed_items:
        return "  (no samples with quality data)"

    all_per_bone: dict[str, list[dict]] = {}
    sample_max_dir_errors: list[tuple[float, str]] = []
    velocities: list[dict] = []
    ground_contacts: list[dict] = []
    symmetries: list[float] = []
    direction_summaries: list[dict] = []

    for it in passed_items:
        q = it["quality"]
        sample_id = it.get("sample_id", "?")
        per_bone = q.get("per_bone_direction_errors", [])
        for be in per_bone:
            all_per_bone.setdefault(be["bone"], []).append(be)

        rde = q.get("retarget_direction_error", {})
        if rde and rde.get("overall_max_rad") is not None:
            direction_summaries.append(rde)
            sample_max_dir_errors.append((rde["overall_max_rad"], sample_id))

        vel = q.get("velocity")
        if vel and vel.get("mean_speed_m_s") is not None:
            velocities.append(vel)
        gc = q.get("ground_contact")
        if gc and gc.get("total_frames"):
            ground_contacts.append(gc)
        sym = q.get("symmetry")
        if sym and sym.get("max_asymmetry") is not None:
            symmetries.append(sym["max_asymmetry"])

    lines: list[str] = []
    lines.append(f"  Samples processed: {len(passed_items)}")

    if direction_summaries:
        import math
        lines.append("")
        lines.append("  === RETARGET QUALITY (rotation/direction preservation) ===")
        avg_mean_rad = sum(d["overall_mean_rad"] for d in direction_summaries) / len(direction_summaries)
        worst_max_rad = max(d["overall_max_rad"] for d in direction_summaries)
        avg_mean_pct = math.degrees(avg_mean_rad) / 360.0 * 100.0
        worst_max_pct = math.degrees(worst_max_rad) / 360.0 * 100.0
        lines.append("")
        lines.append("  [Per-Bone Direction Error]")
        lines.append(f"    Avg mean: {avg_mean_rad:.6f} rad ({math.degrees(avg_mean_rad):.4f} deg, {avg_mean_pct:.4f}%)")
        lines.append(f"    Global max: {worst_max_rad:.6f} rad ({math.degrees(worst_max_rad):.4f} deg, {worst_max_pct:.4f}%)")
        lines.append("")
        lines.append("  === SOURCE MOTION CHARACTERISTICS (inherent data properties) ===")

    if ground_contacts:
        avg_float = sum(gc["floating_ratio"] for gc in ground_contacts) / len(ground_contacts)
        avg_pen = sum(gc["penetrating_ratio"] for gc in ground_contacts) / len(ground_contacts)
        lines.append("")
        lines.append("  [Ground Contact]")
        lines.append(f"    Avg floating ratio:    {avg_float * 100:.2f}%")
        lines.append(f"    Avg penetrating ratio: {avg_pen * 100:.2f}%")

    if velocities:
        avg_speed = sum(v["mean_speed_m_s"] for v in velocities) / len(velocities)
        max_speed = max(v["max_speed_m_s"] for v in velocities)
        total_jittery = sum(v["jittery_joints"] for v in velocities)
        lines.append("")
        lines.append("  [Velocity]")
        lines.append(f"    Avg mean speed: {avg_speed:.3f} m/s | Global max: {max_speed:.3f} m/s")
        lines.append(f"    Total jittery joints across all samples: {total_jittery}")

    if symmetries:
        avg_sym = sum(symmetries) / len(symmetries)
        max_sym = max(symmetries)
        lines.append("")
        lines.append(f"  [Symmetry (source motion L/R asymmetry)]")
        lines.append(f"    Avg max asymmetry: {avg_sym * 100:.2f}% | Worst: {max_sym * 100:.2f}%")

    if all_per_bone:
        lines.append("")
        lines.append("  [Per-Bone Direction Errors - averaged across all samples]")
        lines.append(f"  {'Bone':<36} {'AvgMean(rad)':>13} {'AvgMax(rad)':>13} {'AvgMaxDeg':>10}")
        lines.append(f"  {'-' * 76}")
        aggregated = []
        for bone, entries in all_per_bone.items():
            n = len(entries)
            avg_mean = sum(e["mean_rad"] for e in entries) / n
            avg_max = sum(e["max_rad"] for e in entries) / n
            avg_max_deg = sum(e["max_deg"] for e in entries) / n
            aggregated.append((bone, avg_mean, avg_max, avg_max_deg))
        aggregated.sort(key=lambda x: x[2], reverse=True)
        for bone, avg_mean, avg_max, avg_max_deg in aggregated[:22]:
            lines.append(
                f"  {bone:<36} "
                f"{avg_mean:>13.6f} "
                f"{avg_max:>13.6f} "
                f"{avg_max_deg:>10.4f}"
            )
        if len(aggregated) > 22:
            lines.append(f"  ... {len(aggregated) - 22} more bones")

    if sample_max_dir_errors:
        lines.append("")
        import math
        lines.append("  [Top-10 Worst Samples by max bone direction error]")
        lines.append(f"  {'#':<4} {'MaxErr(rad)':>12} {'MaxErr(deg)':>12}  {'Sample ID'}")
        lines.append(f"  {'-' * 72}")
        sample_max_dir_errors.sort(key=lambda x: x[0], reverse=True)
        for rank, (err, sid) in enumerate(sample_max_dir_errors[:10], 1):
            lines.append(f"  {rank:<4} {err:>12.6f} {math.degrees(err):>12.4f}  {sid}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI: process command
# ---------------------------------------------------------------------------


def _resolve_source_interactive(args: argparse.Namespace) -> str:
    """Resolve data source: use --data-source if given, otherwise prompt."""
    if args.data_source:
        return args.data_source
    sources = ProjectPaths.available_sources()
    print(f"\n{'-' * 60}")
    print("  Select data source")
    print(f"{'-' * 60}")
    for i, key in enumerate(AVAILABLE_DATA_SOURCES, 1):
        info = sources[key]
        mark = "[OK]" if info.get("exists") else "[--]"
        print(f"  {i}. {mark} {key:6s}: {info.get('label', '')}")
        print(f"                    {info.get('raw_root', 'N/A')}")
    print(f"{'-' * 60}")
    raw = input("  Enter 1 or 2 [1=full]: ").strip()
    if raw == "2":
        return "demo"
    return "full"


def _cmd_process(args: argparse.Namespace) -> None:
    source = _resolve_source_interactive(args)
    paths = ProjectPaths(data_source=source)

    if not paths.raw_root.exists():
        custom = input(f"  raw_root not found: {paths.raw_root}\n  Enter path (or empty to abort): ").strip()
        if not custom:
            raise SystemExit("Aborted: data root not found.")
        os.environ["VIREA_RAW_ROOT"] = custom
        paths = ProjectPaths(data_source=source)

    print(f"\n  Data source: {source}")
    print(f"  Raw root:    {paths.raw_root}")
    print(f"  Processed:   {paths.processed_root}")
    paths.processed_root.mkdir(parents=True, exist_ok=True)

    os.environ["VIREA_RAW_ROOT"] = str(paths.raw_root)
    os.environ["VIREA_PROCESSED_ROOT"] = str(paths.processed_root)

    registry = _registry(source)
    batch = BatchPipeline(registry)
    datasets_filter = args.datasets or None
    limit = args.limit_per_dataset if args.limit_per_dataset and args.limit_per_dataset > 0 else 1_000_000_000
    tasks = batch.collect_tasks(datasets=datasets_filter, query=args.query, limit_per_dataset=limit)
    workers = args.workers if args.workers > 0 else default_worker_count()

    legacy_pickle_datasets = {task.dataset for task in tasks} & {"grab", "susuinteracts"}
    if legacy_pickle_datasets and os.getenv("VIREA_ALLOW_TRUSTED_RAW_PICKLE", "").strip() != "1":
        names = ", ".join(sorted(legacy_pickle_datasets))
        print(
            f"\n  Safety: {names} uses legacy NumPy object containers, so loading is disabled by default.\n"
            "  For locally verified data only, set VIREA_ALLOW_TRUSTED_RAW_PICKLE=1 and rerun;\n"
            "  keep this disabled on public/remote services and migrate the data before distribution."
        )

    total_tasks = len(tasks)
    print(f"\n  Tasks: {total_tasks} | Workers: {workers} | "
          f"Skip existing: {args.skip_existing} | Max frames: {args.max_frames or 'all'}")
    print(f"{'=' * 70}")

    progress_state = {"done": 0, "ok": 0, "skip": 0, "fail": 0, "last_id": ""}

    def on_progress(result) -> None:
        progress_state["done"] += 1
        if result.status == "passed":
            progress_state["ok"] += 1
        elif result.status == "skipped":
            progress_state["skip"] += 1
        else:
            progress_state["fail"] += 1
        progress_state["last_id"] = result.task.sample_id
        done = progress_state["done"]
        pct = done * 100 // max(total_tasks, 1)
        bar_len = 30
        filled = bar_len * done // max(total_tasks, 1)
        bar = "#" * filled + "-" * (bar_len - filled)
        short_id = result.task.sample_id[-40:] if len(result.task.sample_id) > 40 else result.task.sample_id
        print(
            f"\r  [{bar}] {pct:3d}% ({done}/{total_tasks}) "
            f"ok={progress_state['ok']} skip={progress_state['skip']} fail={progress_state['fail']} "
            f"| {short_id}",
            end="", flush=True,
        )

    report = batch.run(
        tasks,
        workers=workers,
        max_frames=args.max_frames,
        continue_on_error=True,
        skip_existing=args.skip_existing,
        force=args.force,
        on_progress=on_progress,
    )
    print()  # newline after progress bar
    report_dict = report.to_dict()

    # Group results by dataset
    by_dataset: dict[str, list[dict]] = {}
    for item in report_dict.get("items", []):
        ds = item.get("dataset", "unknown")
        by_dataset.setdefault(ds, []).append(item)

    # Print per-dataset aggregate summary tables
    print(f"\n{'=' * 70}")
    print(f"  PROCESSING COMPLETE")
    print(f"  Processed: {report_dict['processed']} | "
          f"Skipped: {report_dict['skipped']} | "
          f"Failed: {report_dict['failed']} | "
          f"Elapsed: {report_dict['elapsed_sec']:.1f}s")
    print(f"{'=' * 70}")

    for ds_name, ds_items in sorted(by_dataset.items()):
        n_ok = sum(1 for it in ds_items if it.get("status") == "passed")
        n_skip = sum(1 for it in ds_items if it.get("status") == "skipped")
        n_fail = sum(1 for it in ds_items if it.get("status") == "failed")
        print(f"\n{'=' * 70}")
        print(f"  Dataset: {ds_name}")
        print(f"  Total: {len(ds_items)} | OK: {n_ok} | Skipped: {n_skip} | Failed: {n_fail}")
        print(f"{'-' * 70}")
        print(_aggregate_dataset_quality(ds_items))
        failed = [it for it in ds_items if it.get("status") == "failed"]
        if failed:
            print(f"\n  [Failed samples]")
            for it in failed[:10]:
                print(f"    {it['sample_id']}: {it.get('error', 'unknown error')}")
        print(f"{'=' * 70}")

    # Save JSON report
    report_path = paths.processed_root / "processing-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Full JSON report: {report_path}")


# ---------------------------------------------------------------------------
# CLI: serve command
# ---------------------------------------------------------------------------


def _cmd_serve(args: argparse.Namespace) -> None:
    source = args.data_source or "demo"
    host = args.host or os.getenv("VIREA_SERVE_HOST") or None
    env_port = os.getenv("VIREA_SERVE_PORT")
    port = args.port or (int(env_port) if env_port else None)
    paths = ProjectPaths(data_source=source)
    print(f"\n  Data source: {source}")
    print(f"  Raw root:    {paths.raw_root} {'(OK)' if paths.raw_root.exists() else '(NOT FOUND)'}")
    print(f"  Processed:   {paths.processed_root}")
    if host and port:
        print(f"  Server:      http://{host}:{port}")
    else:
        print("  Server:      uvicorn default bind")
    print()
    os.environ["VIREA_DATA_SOURCE"] = source
    run_kwargs: dict[str, Any] = {"reload": args.reload}
    if host:
        run_kwargs["host"] = host
    if port:
        run_kwargs["port"] = port
    uvicorn.run("virea.server.app:app", **run_kwargs)


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def _cmd_build_demo(args: argparse.Namespace) -> None:
    from virea.demo import build_demo_dataset
    print(f"\n  Building demo dataset ({args.samples_per_dataset} samples/dataset)...")
    manifest = build_demo_dataset(
        max_rows=args.samples_per_dataset,
        overwrite=args.overwrite,
        samples_per_dataset=args.samples_per_dataset,
    )
    n_files = len(manifest.get("copied_files", []))
    print(f"\n  Done. Copied {n_files} files to {manifest.get('demo_raw_root', '?')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="virea",
        description="VIREA Motion Data Infrastructure",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- process ---
    proc = sub.add_parser(
        "process",
        help="Batch process raw motion data. Outputs per-dataset retarget error tables.",
    )
    proc.add_argument(
        "--data-source", choices=AVAILABLE_DATA_SOURCES, default="",
        help="Data source: 'full' (external drive) or 'demo' (local fixture). "
             "If omitted, prompts interactively.",
    )
    proc.add_argument("--datasets", nargs="*", default=[], help="Datasets to process (default: all).")
    proc.add_argument("--query", default="", help="Optional sample ID filter.")
    proc.add_argument("--limit-per-dataset", type=int, default=0, help="Max samples per dataset (0=all).")
    proc.add_argument("--max-frames", type=int, default=None, help="Frame cap per clip (omit for full).")
    proc.add_argument("--workers", type=int, default=0, help="Parallel workers (0=auto).")
    proc.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    proc.add_argument("--force", action="store_true", help="Reprocess even if artifacts exist.")
    proc.set_defaults(func=_cmd_process)

    # --- serve ---
    srv = sub.add_parser(
        "serve",
        help="Start the visualization web server for previewing raw/processed motion.",
    )
    srv.add_argument(
        "--data-source", choices=AVAILABLE_DATA_SOURCES, default="demo",
        help="Data source for the viewer (default: demo).",
    )
    srv.add_argument("--host", default="", help="Bind host. Can also be set with VIREA_SERVE_HOST.")
    srv.add_argument("--port", type=int, default=None, help="Bind port. Can also be set with VIREA_SERVE_PORT.")
    srv.add_argument("--reload", action="store_true")
    srv.set_defaults(func=_cmd_serve)

    # --- build-demo ---
    demo = sub.add_parser(
        "build-demo",
        help="Build demo dataset (100 samples/dataset) from full source.",
    )
    demo.add_argument("--samples-per-dataset", type=int, default=100)
    demo.add_argument("--overwrite", action="store_true")
    demo.set_defaults(func=_cmd_build_demo)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
