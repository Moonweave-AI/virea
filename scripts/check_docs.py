"""Deterministic Markdown, math, link, and showcase checks for VIREA docs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "doc").rglob("*.md"))]
REQUIRED_FRONTMATTER = {
    "type",
    "status",
    "owner",
    "created",
    "updated",
    "last_reviewed",
    "review_cycle_days",
    "summary",
    "canonical",
    "related",
    "supersedes",
    "superseded_by",
}
FORBIDDEN_MATH = {
    "\\operatorname": "target renderer rejects operatorname",
    "\\mathcal": "target renderer has unstable mathcal support",
    "\\bar{o}": "target rest offset must use o with a T superscript",
}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SNAKE_IN_MATH_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]+_[A-Za-z][A-Za-z0-9_]+\b")
DOUBLE_SUBSCRIPT_RE = re.compile(
    r"(?:[A-Za-z]|\})_(?:\{[^{}\n]+\}|[A-Za-z0-9])_(?:\{|[A-Za-z0-9])"
)


def frontmatter_keys(text: str) -> set[str]:
    if not text.startswith("---\n"):
        return set()
    end = text.find("\n---\n", 4)
    if end < 0:
        return set()
    keys: set[str] = set()
    for line in text[4:end].splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):", line)
        if match:
            keys.add(match.group(1))
    return keys


def math_segments(text: str) -> list[str]:
    segments: list[str] = []
    display_parts = text.split("$$")
    segments.extend(display_parts[index] for index in range(1, len(display_parts), 2))
    without_display = "".join(
        part if index % 2 == 0 else "\n"
        for index, part in enumerate(display_parts)
    )
    segments.extend(match.group(1) for match in re.finditer(r"(?<!\$)\$([^$\n]+)\$(?!\$)", without_display))
    return segments


def without_code(text: str) -> str:
    """Remove fenced and inline code before interpreting Markdown math."""

    no_fences = re.sub(r"```.*?```", "\n", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", no_fences)


def local_link_target(markdown: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().strip("<>").split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:", "data:")):
        return None
    target = unquote(target)
    if " " in target and not Path(target).exists():
        target = target.split(" ", 1)[0]
    return (markdown.parent / target).resolve()


def check_markdown(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    prose = without_code(text)
    rel = path.relative_to(ROOT).as_posix()

    missing = REQUIRED_FRONTMATTER - frontmatter_keys(text)
    if missing:
        errors.append(f"{rel}: missing frontmatter keys: {', '.join(sorted(missing))}")

    if re.search(r"(?m)^#{1,6} .*\$", prose):
        errors.append(f"{rel}: math is not allowed in headings")
    if re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", prose):
        errors.append(f"{rel}: contains a machine-specific absolute Windows path")

    delimiter_lines = [line for line in prose.splitlines() if "$$" in line]
    if len(delimiter_lines) % 2:
        errors.append(f"{rel}: unpaired display math delimiter")
    for line in delimiter_lines:
        if line.strip() != "$$":
            errors.append(f"{rel}: display math delimiter must be on its own line: {line.strip()}")

    for token, reason in FORBIDDEN_MATH.items():
        if token in prose:
            errors.append(f"{rel}: forbidden {token} ({reason})")

    for segment in math_segments(prose):
        if "`" in segment:
            errors.append(f"{rel}: inline code marker appears inside math")
        if "#" in segment:
            errors.append(f"{rel}: hash character appears inside math")
        if SNAKE_IN_MATH_RE.search(segment):
            errors.append(f"{rel}: code-like snake_case identifier appears inside math")
        if DOUBLE_SUBSCRIPT_RE.search(segment):
            errors.append(f"{rel}: possible double subscript appears inside math")

    for match in LINK_RE.finditer(text):
        target = local_link_target(path, match.group(1))
        if target is not None and not target.exists():
            errors.append(f"{rel}: missing local link target {match.group(1)}")
    return errors


def check_showcase() -> list[str]:
    errors: list[str] = []
    showcase = ROOT / "doc" / "showcase"
    expected = {"amass", "babel", "beat", "grab", "humanml3d", "motionx", "susuinteracts"}
    gifs = {path.stem: path for path in (showcase / "gifs").glob("*.gif")}
    videos = {path.stem: path for path in (showcase / "videos").glob("*.webm")}
    if len(gifs) != 49:
        errors.append(f"showcase: expected 49 GIF files, found {len(gifs)}")
    if len(videos) != 49:
        errors.append(f"showcase: expected 49 WebM files, found {len(videos)}")
    if gifs.keys() != videos.keys():
        errors.append("showcase: GIF/WebM stems do not match")
    for path in [*gifs.values(), *videos.values()]:
        if path.stat().st_size == 0:
            errors.append(f"showcase: empty media file {path.relative_to(ROOT).as_posix()}")

    readme_path = showcase / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    linked_gifs = {
        Path(target).stem
        for target in re.findall(r"!\[[^\]]*\]\((gifs/[^)]+\.gif)\)", readme)
    }
    linked_videos = {
        Path(target).stem
        for target in re.findall(r"\]\((videos/[^)]+\.webm)\)", readme)
    }

    policy_path = showcase / "publication-policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"showcase: invalid publication policy: {exc}"]
    decision = policy.get("decision")
    if decision not in {"allowed", "local-only", "blocked", "unknown"}:
        errors.append(f"showcase: invalid publication decision {decision!r}")
    embed_allowed = policy.get("public_embed_allowed")
    if embed_allowed is not (decision == "allowed"):
        errors.append("showcase: public_embed_allowed must be true only when decision is allowed")
    dataset_decisions = policy.get("datasets")
    if not isinstance(dataset_decisions, dict) or set(dataset_decisions) != expected:
        errors.append("showcase: publication policy must contain exactly seven dataset decisions")
        dataset_decisions = {}
    vrm_decision = (policy.get("vrm") or {}).get("decision")
    if decision == "allowed":
        if vrm_decision != "allowed" or any(dataset_decisions.get(dataset) != "allowed" for dataset in expected):
            errors.append("showcase: overall allowed requires allowed VRM and all dataset decisions")
        if linked_gifs != set(gifs):
            errors.append("showcase: allowed README must reference every and only the 49 GIF files")
        if linked_videos != set(videos):
            errors.append("showcase: allowed README must reference every and only the 49 WebM files")
    elif linked_gifs or linked_videos:
        errors.append("showcase: non-allowed media must not be embedded or linked from README")

    legacy_policy = policy.get("legacy_media") or {}
    if legacy_policy.get("expected_pair_count") != 49:
        errors.append("showcase: legacy publication policy must declare 49 media pairs")
    if decision != "allowed" and legacy_policy.get("public_links_allowed") is not False:
        errors.append("showcase: non-allowed legacy media must set public_links_allowed=false")

    manifest_path = showcase / "showcase-samples.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [*errors, f"showcase: invalid manifest: {exc}"]
    if set(manifest) != expected:
        errors.append("showcase: manifest must contain exactly the seven dataset keys")
    manifest_videos: list[str] = []
    for dataset in expected:
        rows = manifest.get(dataset, [])
        if len(rows) != 7:
            errors.append(f"showcase: {dataset} must contain 7 rows, found {len(rows)}")
        for row in rows:
            video_value = row.get("video") if isinstance(row, dict) else None
            if isinstance(row, dict) and row.get("dataset") != dataset:
                errors.append(f"showcase: {dataset} row has mismatched dataset {row.get('dataset')!r}")
            if not video_value or not (ROOT / video_value).exists():
                errors.append(f"showcase: {dataset} row has missing video {video_value!r}")
            else:
                manifest_videos.append(Path(video_value).stem)
    if len(manifest_videos) != len(set(manifest_videos)):
        errors.append("showcase: manifest contains duplicate video rows")
    if set(manifest_videos) != set(videos):
        errors.append("showcase: manifest videos must match every and only the 49 WebM files")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in DOC_FILES:
        errors.extend(check_markdown(path))
    errors.extend(check_showcase())
    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Documentation checks passed: {len(DOC_FILES)} Markdown files, "
        "49 locally verified GIF/WebM pairs, publication policy enforced."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
