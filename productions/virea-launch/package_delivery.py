"""Check and package only the explicit VIREA delivery allowlist; never render.

Default: CPU-only preflight. --snapshot-inputs records the final render inputs.
--build requires completed export/VR/parity reviews. It never overwrites a package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import shutil
import stat
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "delivery-manifest.json"
DENIED_PARTS = {
    "node_modules",
    ".git",
    ".venv-asr",
    ".virea-runtime",
    "unused-takes",
    "cache",
    ".render-public",
    "dist",
}
DENIED_SUFFIXES = {
    ".vrm",
    ".vrma",
    ".glb",
    ".gltf",
    ".log",
    ".pfx",
    ".pem",
    ".key",
    ".ttc",
}
TEXT_SUFFIXES = {".md", ".json", ".ts", ".tsx", ".mjs", ".py", ".css", ".html", ".txt"}
SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_-]{24,}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{25,}\b",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in ("..", ".") for part in path.parts)
        or ":" in value
        or "\\" in value
    ):
        raise ValueError(f"Not a contained relative path: {value}")
    if (
        set(path.parts) & DENIED_PARTS
        or path.suffix.lower() in DENIED_SUFFIXES
        or path.name.startswith(".env")
    ):
        raise ValueError(f"Excluded delivery path: {value}")
    return path


def source_path(value: str) -> Path:
    relative = safe_relative(value)
    path = ROOT.joinpath(*relative.parts)
    path.resolve().relative_to(ROOT.resolve())
    for part in (path, *path.parents):
        if part == ROOT:
            break
        if part.exists() and (
            part.is_symlink()
            or getattr(part.lstat(), "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise ValueError(
                f"Package source must be a real file, not a junction/symlink: {value}"
            )
    return path


def inspect(manifest: dict) -> tuple[list[dict], list[str]]:
    rows, errors, destinations = [], [], set()
    for entry in manifest["files"]:
        target = str(safe_relative(entry["destination"]))
        if target.casefold() in destinations:
            raise ValueError(f"Duplicate package destination: {target}")
        destinations.add(target.casefold())
        source = source_path(entry["source"])
        if not source.is_file():
            errors.append(f"Missing file: {entry['source']}")
            continue
        if source.suffix.lower() in TEXT_SUFFIXES:
            contents = source.read_text(encoding="utf-8-sig")
            if any(re.search(pattern, contents) for pattern in SECRET_PATTERNS):
                errors.append(
                    f"Credential-like content requires review: {entry['source']}"
                )
                continue
        rows.append({**entry, "bytes": source.stat().st_size, "sha256": digest(source)})
    allowed = {entry["destination"] for entry in manifest["files"]}
    for entry in manifest["files"]:
        if (
            entry.get("role") != "delivery_doc"
            or not source_path(entry["source"]).is_file()
        ):
            continue
        text = source_path(entry["source"]).read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if link.startswith(("https:", "http:", "mailto:", "#")):
                continue
            target = posixpath.normpath(
                posixpath.join(
                    posixpath.dirname(entry["destination"]), link.split("#", 1)[0]
                )
            )
            if target not in allowed:
                errors.append(
                    f"Delivery documentation link is not packaged: {entry['destination']} -> {link}"
                )
    return rows, errors


def review_errors(manifest: dict, rows: list[dict]) -> list[str]:
    errors = []
    report_path = ROOT / "validation/export-validation.json"
    if not report_path.exists():
        return ["Final export validation is pending: validation/export-validation.json"]
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    identities = {entry["source"]: entry["sha256"] for entry in rows}
    if report.get("status") != "passed":
        errors.append("Final export validation has not passed")
    exports = {entry["edition"]: entry for entry in report.get("exports", [])}
    for entry in (item for item in manifest["files"] if item.get("role") == "film"):
        result = exports.get(entry["edition"], {})
        if result.get("status") != "passed" or result.get("sha256") != identities.get(
            entry["source"]
        ):
            errors.append(
                f"Export acceptance/hash missing or stale: {entry['edition']}"
            )
        expected = manifest["expected_video"]
        if any(
            result.get("video", {}).get(key) != value for key, value in expected.items()
        ):
            errors.append(
                f"Export video metadata does not match the delivery contract: {entry['edition']}"
            )
        if (
            result.get("full_decode") != "passed"
            or result.get("visual_review") != "passed"
        ):
            errors.append(f"Decode/visual review incomplete: {entry['edition']}")
        if result.get("captions") != "passed":
            errors.append(f"Caption review incomplete: {entry['edition']}")
        audio = result.get("audio", {})
        if audio.get("status") != "passed":
            errors.append(f"Mixed-audio check incomplete: {entry['edition']}")
        elif entry["edition"] == "silent":
            if not (
                audio.get("stream_count") == 0 or audio.get("all_samples_zero") is True
            ):
                errors.append("Silent edition has not been proven silent")
        elif audio.get("true_peak_dbtp") is None or audio["true_peak_dbtp"] >= 0:
            errors.append(f"Mixed-audio peak is missing or clips: {entry['edition']}")
    snapshot_path = ROOT / "validation/render-inputs.json"
    if not snapshot_path.exists():
        errors.append("Render-input snapshot is missing")
    else:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        current = {
            row["source"]: row["sha256"] for row in rows if row.get("render_input")
        }
        if snapshot.get("files") != current or report.get(
            "render_inputs_sha256"
        ) != digest(snapshot_path):
            errors.append(
                "Final render-input snapshot is stale or not attached to export review"
            )
    selected = report.get("selected_vr", {})
    if selected.get("status") != "passed" or selected.get("sha256") != identities.get(
        "edit/public/footage/vrchat-world-extended.mp4"
    ):
        errors.append("Selected VR source acceptance/hash is missing or stale")
    if selected.get("poster_sha256") != identities.get(
        "edit/public/captures/vrchat-hdr-correct-new.png"
    ):
        errors.append("Selected VR poster hash is missing or stale")
    wb = report.get("workbench", {})
    if (
        wb.get("saved_project_sha256")
        != identities.get("workbench/projects/virea-english.json")
        or wb.get("muted_preview") != "passed"
        or wb.get("english_interface") != "passed"
    ):
        errors.append("Final workbench import/English/mute check is incomplete")
    parity_path = ROOT / "workbench/.parity-4k/report.json"
    parity = (
        json.loads(parity_path.read_text(encoding="utf-8-sig"))
        if parity_path.exists()
        else {}
    )
    frames = manifest["parity_frames"]
    if parity_path.exists() and wb.get("parity_report_sha256") != digest(parity_path):
        errors.append("Parity report is not attached to final workbench review")
    if (
        parity.get("verdict") != "same"
        or parity.get("frames") != frames
        or parity.get("resolution") != "3840x2160"
        or len(parity.get("results", [])) != len(frames)
        or any(row.get("verdict") != "same" for row in parity.get("results", []))
    ):
        errors.append(f"Fresh {len(frames)}-frame 4K workbench parity is incomplete")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="CPU preflight only (the default)"
    )
    parser.add_argument(
        "--snapshot-inputs",
        action="store_true",
        help="Record final media/source identities before rendering",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Copy the validated allowlist to a new delivery folder",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Also write a ZIP from the same copied file list",
    )
    parser.add_argument("--output", default="delivery")
    args = parser.parse_args()
    if args.zip and not args.build:
        parser.error("--zip requires --build")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    rows, errors = inspect(manifest)
    if args.snapshot_inputs:
        inputs = [entry for entry in manifest["files"] if entry.get("render_input")]
        identities = {
            row["source"]: row["sha256"] for row in rows if row.get("render_input")
        }
        if len(identities) != len({entry["source"] for entry in inputs}):
            print("Cannot snapshot: selected render inputs are missing or excluded.")
            return 2
        save(
            ROOT / "validation/render-inputs.json",
            {
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "files": identities,
            },
        )
        print(
            "Recorded validation/render-inputs.json. This is an input snapshot, not export approval."
        )
        return 0
    errors.extend(review_errors(manifest, rows))
    preflight = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not errors else "pending",
        "allowed_files": len(manifest["files"]),
        "present_files": len(rows),
        "bytes": sum(row["bytes"] for row in rows),
        "errors": errors,
        "rendering_performed": False,
        "audible_playback_performed": False,
    }
    save(ROOT / "validation/package-preflight.json", preflight)
    print(json.dumps(preflight, indent=2))
    if errors or not args.build:
        return 2 if errors else 0
    output = ROOT / args.output
    output.resolve().relative_to(ROOT.resolve())
    if (
        output.parent.resolve() != ROOT.resolve()
        or not output.name.startswith("delivery")
        or output.exists()
        or output.with_suffix(".zip").exists()
    ):
        raise ValueError(
            "Use a new production-root delivery* directory; existing output is never overwritten."
        )
    staging = ROOT / f".{output.name}.incomplete-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    copied = []
    for row in rows:
        target = staging.joinpath(*safe_relative(row["destination"]).parts)
        target.resolve().relative_to(staging.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path(row["source"]), target)
        if digest(target) != row["sha256"]:
            raise ValueError(
                f"Package copy hash mismatch: {row['destination']}; staging retained at {staging.name}"
            )
        copied.append(target)
    save(
        staging / "PACKAGE-MANIFEST.json",
        {
            "packaged_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": rows,
            "allowlist_sha256": digest(MANIFEST),
            "export_review_sha256": digest(ROOT / "validation/export-validation.json"),
        },
    )
    copied.append(staging / "PACKAGE-MANIFEST.json")
    sums = "".join(
        f"{digest(path)}  {path.relative_to(staging).as_posix()}\n"
        for path in sorted(copied)
    )
    (staging / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    copied.append(staging / "SHA256SUMS.txt")
    destinations = [path.relative_to(staging) for path in copied]
    staging.rename(output)
    if args.zip:
        with zipfile.ZipFile(
            output.with_suffix(".zip"),
            "x",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            for relative in destinations:
                archive.write(output / relative, arcname=relative.as_posix())
        print(f"ZIP SHA256: {digest(output.with_suffix('.zip'))}")
    print(f"Packaged {len(destinations)} verified files: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
