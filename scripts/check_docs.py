"""Deterministic Markdown, math, link, and showcase checks for VIREA docs."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "site-packages",
}


def repository_markdown() -> list[Path]:
    """Discover every project-owned Markdown file, not only the docs folder."""

    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not any(part in MARKDOWN_EXCLUDED_PARTS for part in path.parts)
        and ".egg-info" not in path.as_posix()
    )


DOC_FILES = repository_markdown()
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
METADATA_EXEMPT = {
    # This is a byte-for-byte archival copy of the user-supplied registry
    # snapshot. Governance metadata lives in its catalog/index sidecars.
    "doc/model-catalog/motion-generation-registry-2026-08-20.zh-CN.md",
    # Conventional legal notices are consumed verbatim by packaging and
    # license scanners. They remain in the all-Markdown link/content checks,
    # but governance metadata lives in the owning model manifest or root docs.
    "THIRD_PARTY_NOTICES.md",
    "plugins/models/acmdm-humanml3d/runtime/THIRD_PARTY_NOTICES.md",
    "plugins/models/cmdm-humanml3d/runtime/THIRD_PARTY_NOTICES.md",
    "plugins/models/flood-diffusion-tiny/runtime/THIRD_PARTY_NOTICES.md",
    "plugins/models/mardm-humanml3d/runtime/THIRD_PARTY_NOTICES.md",
    "plugins/models/momadiff-humanml3d/runtime/THIRD_PARTY_NOTICES.md",
    "plugins/models/prism-tp2m-1-4b/runtime/THIRD_PARTY_NOTICES.md",
}
BILINGUAL_DOCUMENT_PAIRS = {
    "README.md": "README.zh-CN.md",
    "doc/README.en.md": "doc/README.zh-CN.md",
    "doc/getting-started.en.md": "doc/getting-started.zh-CN.md",
    "doc/getting-started/installation.en.md": "doc/getting-started/installation.zh-CN.md",
    "doc/getting-started/first-generation.en.md": "doc/getting-started/first-generation.zh-CN.md",
    "doc/getting-started/browser-playback.en.md": "doc/getting-started/browser-playback.zh-CN.md",
    "doc/reference/cli.en.md": "doc/reference/cli.zh-CN.md",
    "doc/platforms/README.en.md": "doc/platforms/README.zh-CN.md",
    "doc/platforms/windows.en.md": "doc/platforms/windows.zh-CN.md",
    "doc/platforms/linux.en.md": "doc/platforms/linux.zh-CN.md",
    "doc/platforms/wsl2.en.md": "doc/platforms/wsl2.zh-CN.md",
    "doc/platforms/macos.en.md": "doc/platforms/macos.zh-CN.md",
    "doc/models/README.en.md": "doc/models/README.zh-CN.md",
    "doc/development/documentation.en.md": "doc/development/documentation.zh-CN.md",
    "doc/operations/troubleshooting.en.md": "doc/operations/troubleshooting.zh-CN.md",
    "doc/operations/runtime-data-and-retention.en.md": "doc/operations/runtime-data-and-retention.zh-CN.md",
    "doc/quality/production-e2e.en.md": "doc/quality/production-e2e.zh-CN.md",
    "doc/quality/production-browser-evidence.en.md": "doc/quality/production-browser-evidence.zh-CN.md",
}
COMMAND_GUIDE_DOCUMENTS = {
    "README.md",
    "README.zh-CN.md",
    "doc/getting-started.en.md",
    "doc/getting-started.zh-CN.md",
    "doc/getting-started/installation.en.md",
    "doc/getting-started/installation.zh-CN.md",
    "doc/getting-started/first-generation.en.md",
    "doc/getting-started/first-generation.zh-CN.md",
    "doc/getting-started/browser-playback.en.md",
    "doc/getting-started/browser-playback.zh-CN.md",
    "doc/reference/cli.en.md",
    "doc/reference/cli.zh-CN.md",
    "doc/platforms/README.en.md",
    "doc/platforms/README.zh-CN.md",
    "doc/platforms/windows.en.md",
    "doc/platforms/windows.zh-CN.md",
    "doc/platforms/linux.en.md",
    "doc/platforms/linux.zh-CN.md",
    "doc/platforms/wsl2.en.md",
    "doc/platforms/wsl2.zh-CN.md",
    "doc/platforms/macos.en.md",
    "doc/platforms/macos.zh-CN.md",
    "doc/models/README.en.md",
    "doc/models/README.zh-CN.md",
    "doc/operations/troubleshooting.en.md",
    "doc/operations/troubleshooting.zh-CN.md",
    "doc/operations/runtime-data-and-retention.en.md",
    "doc/operations/runtime-data-and-retention.zh-CN.md",
    "doc/quality/production-e2e.en.md",
    "doc/quality/production-browser-evidence.en.md",
}
FORBIDDEN_MATH = {
    "\\operatorname": "target renderer rejects operatorname",
    "\\mathcal": "target renderer has unstable mathcal support",
    "\\bar{o}": "target rest offset must use o with a T superscript",
}
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HTML_LINK_TAG_RE = re.compile(r"<(?:a|img|audio|video|source)\b[^>]*>", re.IGNORECASE)
HTML_LINK_ATTRIBUTE_RE = re.compile(
    r"\b(?P<name>href|src|poster|srcset)=[\"'](?P<value>[^\"']+)[\"']",
    re.IGNORECASE,
)
HTML_IMAGE_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_ALT_RE = re.compile(r"\balt=[\"']([^\"']*)[\"']", re.IGNORECASE)
FENCED_CODE_RE = re.compile(r"```[^\n]*\n(?P<body>.*?)```", re.DOTALL)
PUBLIC_MEDIA_RE = re.compile(
    r"\.(?:gif|webm|png|jpe?g|webp|avif|apng|svg|bmp|tiff?|mp4|m4v|mov|ogv|mkv|avi|mp3|wav|ogg|m4a|flac)(?:[?#].*)?$",
    re.IGNORECASE,
)
MALFORMED_63_HEX_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{63}(?![0-9a-fA-F])")
SNAKE_IN_MATH_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]+_[A-Za-z][A-Za-z0-9_]+\b")
DOUBLE_SUBSCRIPT_RE = re.compile(
    r"(?:[A-Za-z]|\})_(?:\{[^{}\n]+\}|[A-Za-z0-9])_(?:\{|[A-Za-z0-9])"
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$")
HTML_ANCHOR_RE = re.compile(
    r"<(?:a|[A-Za-z][A-Za-z0-9:-]*)\b[^>]*(?:id|name)=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
ALLOWED_TYPES = {
    "adr",
    "audit",
    "checklist",
    "engineering-blueprint",
    "engineering-brief",
    "eval-report",
    "evidence",
    "explanation",
    "how-to",
    "index",
    "model-card",
    "notice",
    "policy",
    "quality-plan",
    "readme",
    "reference",
    "release-acceptance",
    "release-notes",
    "report",
    "research-log",
    "research-record",
    "rfc",
    "runtime-guide",
    "tutorial",
}
ALLOWED_STATUSES = {
    "Accepted",
    "Active",
    "Blocked",
    "Current",
    "Generated",
    "Historical",
    "Implemented",
    "InReview",
    "Proposed",
    "Superseded",
    "Superseded in part",
    "Validated",
    "draft",
}


def metadata_block(text: str) -> str | None:
    if not text.startswith("---\n"):
        for match in reversed(
            list(re.finditer(r"<!--\s*(.*?)\s*-->", text, re.DOTALL))
        ):
            candidate = match.group(1).strip()
            if candidate.startswith("---\n") and candidate.endswith("\n---"):
                candidate = candidate[4:-4].strip()
            # VIREA's established convention stores YAML metadata directly in
            # a trailing HTML comment, without an inner `---` wrapper.
            if re.search(r"(?m)^type:\s*\S", candidate) and re.search(
                r"(?m)^canonical:\s*\S", candidate
            ):
                return candidate
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    return text[4:end]


def frontmatter_keys(text: str) -> set[str]:
    block = metadata_block(text)
    if block is None:
        return set()
    keys: set[str] = set()
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):", line)
        if match:
            keys.add(match.group(1))
    return keys


def frontmatter_scalar(text: str, key: str) -> str | None:
    block = metadata_block(text)
    if block is None:
        return None
    match = re.search(rf"(?m)^{re.escape(key)}:\s*([^\n]+)$", block)
    if not match:
        return None
    return match.group(1).strip().strip("\"'")


def metadata_mapping(text: str) -> tuple[dict[str, object] | None, str | None]:
    block = metadata_block(text)
    if block is None:
        return None, "metadata block is missing"
    try:
        value = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        return None, f"metadata is not valid YAML: {exc}"
    if not isinstance(value, dict):
        return None, "metadata must be a YAML object"
    return value, None


def github_heading_anchors(text: str) -> set[str]:
    """Return GitHub-compatible heading anchors plus explicit HTML anchors."""

    anchors = {unquote(value) for value in HTML_ANCHOR_RE.findall(text)}
    seen: dict[str, int] = {}
    for heading in HEADING_RE.findall(without_code(text)):
        plain = re.sub(r"<[^>]+>", "", heading)
        plain = re.sub(r"!?(?:\[([^\]]*)\])\([^)]*\)", r"\1", plain)
        plain = re.sub(r"[`*_~]", "", plain).strip().lower()
        slug = "".join(
            char
            for char in plain
            if char.isalnum() or char in {" ", "-", "_"} or ord(char) >= 128
        )
        slug = re.sub(r"\s+", "-", slug)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def local_link_parts(markdown: Path, raw_target: str) -> tuple[Path | None, str | None]:
    cleaned = raw_target.strip().strip("<>")
    target_value, separator, fragment = cleaned.partition("#")
    if target_value.startswith(("http://", "https://", "mailto:", "data:")):
        return None, None
    target_value = unquote(target_value)
    fragment_value = unquote(fragment) if separator else None
    if not target_value:
        return markdown.resolve(), fragment_value
    if " " in target_value and not Path(target_value).exists():
        target_value = target_value.split(" ", 1)[0]
    return (markdown.parent / target_value).resolve(), fragment_value


def metadata_target(markdown: Path, raw_target: str) -> Path | None:
    """Resolve metadata references, allowing the established repo-root form."""

    target, _ = local_link_parts(markdown, raw_target)
    if target is None or target.exists() or raw_target.startswith((".", "#")):
        return target
    root_target = (ROOT / unquote(raw_target).split("#", 1)[0]).resolve()
    return root_target if root_target.exists() else target


def math_segments(text: str) -> list[str]:
    segments: list[str] = []
    display_parts = text.split("$$")
    segments.extend(display_parts[index] for index in range(1, len(display_parts), 2))
    without_display = "".join(
        part if index % 2 == 0 else "\n" for index, part in enumerate(display_parts)
    )
    segments.extend(
        match.group(1)
        for match in re.finditer(r"(?<!\$)\$([^$\n]+)\$(?!\$)", without_display)
    )
    return segments


def without_code(text: str) -> str:
    """Remove fenced and inline code before interpreting Markdown math."""

    no_fences = re.sub(r"```.*?```", "\n", text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", no_fences)


def local_link_target(markdown: Path, raw_target: str) -> Path | None:
    target, _ = local_link_parts(markdown, raw_target)
    return target


def html_link_targets(text: str) -> list[str]:
    """Return every media/link target from supported public HTML tags."""

    targets: list[str] = []
    for tag in HTML_LINK_TAG_RE.findall(text):
        for match in HTML_LINK_ATTRIBUTE_RE.finditer(tag):
            value = match.group("value")
            if match.group("name").lower() == "srcset":
                targets.extend(
                    candidate.strip().split()[0]
                    for candidate in value.split(",")
                    if candidate.strip()
                )
            else:
                targets.append(value)
    return targets


def check_markdown(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    prose = without_code(text)
    rel = path.relative_to(ROOT).as_posix()

    if rel not in METADATA_EXEMPT:
        metadata, metadata_error = metadata_mapping(text)
        if metadata_error:
            errors.append(f"{rel}: {metadata_error}")
            metadata = {}
        missing = REQUIRED_FRONTMATTER - set(metadata)
        if missing:
            errors.append(
                f"{rel}: missing frontmatter keys: {', '.join(sorted(missing))}"
            )

        canonical = metadata.get("canonical")
        if canonical and canonical != rel:
            errors.append(
                f"{rel}: canonical frontmatter must equal its repository path, found {canonical!r}"
            )
        doc_type = metadata.get("type")
        if doc_type is not None and doc_type not in ALLOWED_TYPES:
            errors.append(f"{rel}: unknown documentation type {doc_type!r}")
        status = metadata.get("status")
        if status is not None and status not in ALLOWED_STATUSES:
            errors.append(f"{rel}: unknown documentation status {status!r}")
        review_cycle = metadata.get("review_cycle_days")
        if (
            not isinstance(review_cycle, int)
            or isinstance(review_cycle, bool)
            or review_cycle <= 0
        ):
            errors.append(f"{rel}: review_cycle_days must be a positive integer")
        parsed_dates: dict[str, date] = {}
        for key in ("created", "updated", "last_reviewed"):
            value = metadata.get(key)
            if isinstance(value, date):
                parsed_dates[key] = value
                continue
            try:
                parsed_dates[key] = date.fromisoformat(str(value))
            except (TypeError, ValueError):
                errors.append(f"{rel}: {key} must be an ISO YYYY-MM-DD date")
        if {"created", "updated"}.issubset(parsed_dates) and parsed_dates[
            "updated"
        ] < parsed_dates["created"]:
            errors.append(f"{rel}: updated date precedes created date")
        for key in ("related", "supersedes", "superseded_by"):
            value = metadata.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors.append(f"{rel}: {key} must be a list of strings")
        for key in ("related", "supersedes", "superseded_by"):
            for value in (
                metadata.get(key, []) if isinstance(metadata.get(key), list) else []
            ):
                target = metadata_target(path, value)
                if target is not None and not target.exists():
                    errors.append(f"{rel}: {key} references missing document {value}")

    if re.search(r"(?m)^#{1,6} .*\$", prose):
        errors.append(f"{rel}: math is not allowed in headings")
    if WINDOWS_ABSOLUTE_PATH_RE.search(text):
        errors.append(f"{rel}: contains a machine-specific absolute Windows path")
    if MALFORMED_63_HEX_RE.search(prose):
        errors.append(f"{rel}: contains a malformed 63-character hexadecimal digest")

    delimiter_lines = [line for line in prose.splitlines() if "$$" in line]
    if len(delimiter_lines) % 2:
        errors.append(f"{rel}: unpaired display math delimiter")
    for line in delimiter_lines:
        if line.strip() != "$$":
            errors.append(
                f"{rel}: display math delimiter must be on its own line: {line.strip()}"
            )

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

    for match in MARKDOWN_IMAGE_RE.finditer(text):
        if not match.group(1).strip():
            errors.append(f"{rel}: Markdown image is missing meaningful alt text")
    for tag in HTML_IMAGE_RE.findall(text):
        alt = HTML_ALT_RE.search(tag)
        if alt is None or not alt.group(1).strip():
            errors.append(f"{rel}: HTML image is missing meaningful alt text")

    link_targets = [match.group(1) for match in LINK_RE.finditer(text)]
    link_targets.extend(html_link_targets(text))
    for raw_target in link_targets:
        target, fragment = local_link_parts(path, raw_target)
        if target is not None and not target.exists():
            errors.append(f"{rel}: missing local link target {raw_target}")
            continue
        if (
            target is not None
            and fragment
            and target.is_file()
            and target.suffix.lower() == ".md"
        ):
            anchors = github_heading_anchors(target.read_text(encoding="utf-8"))
            if fragment not in anchors:
                errors.append(f"{rel}: missing Markdown anchor {raw_target}")
    return errors


def check_bilingual_document_contract(repository_paths: set[str]) -> list[str]:
    """Keep active clone-first user paths available in both supported languages."""

    errors: list[str] = []
    for english, chinese in BILINGUAL_DOCUMENT_PAIRS.items():
        for path in (english, chinese):
            if path not in repository_paths:
                errors.append(f"bilingual documentation pair is missing {path}")
        if english not in repository_paths or chinese not in repository_paths:
            continue
        english_text = (ROOT / english).read_text(encoding="utf-8")
        chinese_text = (ROOT / chinese).read_text(encoding="utf-8")
        chinese_link = Path(chinese).relative_to(Path(english).parent).as_posix()
        english_link = Path(english).relative_to(Path(chinese).parent).as_posix()
        if chinese_link not in english_text:
            errors.append(
                f"{english}: missing direct Chinese counterpart link {chinese_link}"
            )
        if english_link not in chinese_text:
            errors.append(
                f"{chinese}: missing direct English counterpart link {english_link}"
            )
    return errors


def check_command_guides() -> list[str]:
    """Require a shell comment immediately before each user-facing VIREA command."""

    errors: list[str] = []
    for rel in sorted(COMMAND_GUIDE_DOCUMENTS):
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for block_index, match in enumerate(FENCED_CODE_RE.finditer(text), start=1):
            previous_nonempty = ""
            for line in match.group("body").splitlines():
                stripped = line.strip()
                if re.search(r"^(?:uv\s+run\s+)?virea(?:\s|$)", stripped):
                    if not (
                        previous_nonempty.startswith("#")
                        or previous_nonempty.lower().startswith("rem ")
                        or previous_nonempty.startswith("::")
                    ):
                        errors.append(
                            f"{rel}: command block {block_index} has an uncommented VIREA command {stripped!r}"
                        )
                if stripped:
                    previous_nonempty = stripped
    return errors


def _load_json(path: Path, label: str, errors: list[str]) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"showcase: invalid {label}: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"showcase: {label} must be a JSON object")
        return None
    return value


def check_showcase() -> list[str]:
    errors: list[str] = []
    showcase = ROOT / "doc" / "showcase"
    expected_datasets = {
        "amass",
        "babel",
        "beat",
        "grab",
        "humanml3d",
        "motionx",
        "susuinteracts",
    }
    displayed_datasets = expected_datasets
    permission_unverified_datasets = {"amass", "babel", "grab", "humanml3d"}
    expected_roles = {"hero", "hands", "feet", "facing"}

    retired = [
        showcase / "showcase-samples.json",
        *list((showcase / "gifs").glob("*.gif")),
        *list((showcase / "videos").glob("*.webm")),
    ]
    if any(path.exists() for path in retired):
        present = ", ".join(
            path.relative_to(ROOT).as_posix() for path in retired if path.exists()
        )
        errors.append(
            f"showcase: retired media returned to the current tree ({present})"
        )

    policy = _load_json(
        showcase / "publication-policy.json", "publication policy", errors
    )
    if policy is None:
        return errors
    if policy.get("schema_version") != "virea.showcase_publication.v2":
        errors.append("showcase: publication policy has the wrong schema_version")
    if policy.get("decision") != "selective-allowlist":
        errors.append("showcase: publication policy must use selective-allowlist")
    if policy.get("public_embed_allowed") is not True:
        errors.append(
            "showcase: selective allowlist must explicitly permit listed embeds"
        )

    dataset_policy = policy.get("datasets")
    if not isinstance(dataset_policy, dict) or set(dataset_policy) != expected_datasets:
        errors.append(
            "showcase: publication policy must contain exactly seven datasets"
        )
        dataset_policy = {}
    expected_decisions = {
        "amass": ("owner-directed-display-permission-unverified", True),
        "babel": ("owner-directed-display-permission-unverified", True),
        "beat": ("allowed-with-attribution", True),
        "grab": ("owner-directed-display-permission-unverified", True),
        "humanml3d": ("owner-directed-display-permission-unverified", True),
        "motionx": ("allowed-noncommercial-attribution-sharealike", True),
        "susuinteracts": ("allowed-noncommercial-with-attribution", True),
    }
    for dataset, (decision, media_allowed) in expected_decisions.items():
        record = dataset_policy.get(dataset)
        if not isinstance(record, dict):
            errors.append(f"showcase: dataset policy must be an object ({dataset})")
            continue
        if record.get("decision") != decision:
            errors.append(f"showcase: incorrect publication decision for {dataset}")
        if record.get("public_media_allowed") is not media_allowed:
            errors.append(f"showcase: incorrect public-media flag for {dataset}")
        if decision == "owner-directed-display-permission-unverified":
            if record.get("legal_permission_verified") is not False:
                errors.append(
                    f"showcase: owner-directed media must preserve the unverified-permission boundary ({dataset})"
                )
            if (
                record.get("publication_basis")
                != "repository-owner-instruction-2026-08-21"
            ):
                errors.append(
                    f"showcase: owner-directed media has no exact publication basis ({dataset})"
                )

    vrm_policy = policy.get("vrm")
    if not isinstance(vrm_policy, dict):
        errors.append("showcase: VRM policy must be an object")
        vrm_policy = {}
    if vrm_policy.get("author") != "Reira":
        errors.append("showcase: audited VRM must credit Reira")
    if vrm_policy.get("decision") != "allowed-noncommercial-with-credit":
        errors.append("showcase: audited VRM must retain its non-commercial decision")
    if vrm_policy.get("public_rendering_allowed") is not True:
        errors.append("showcase: audited VRM must explicitly allow public rendering")
    if vrm_policy.get("model_redistribution_allowed") is not False:
        errors.append(
            "showcase: audited VRM model redistribution must remain prohibited"
        )

    manifest_rel = policy.get("public_media_manifest")
    if manifest_rel != "doc/showcase/media/manifest.json":
        errors.append("showcase: publication policy points to the wrong media manifest")
        manifest_rel = "doc/showcase/media/manifest.json"
    manifest = _load_json(ROOT / manifest_rel, "public media manifest", errors)
    if manifest is None:
        return errors
    if manifest.get("schema_version") != "virea.showcase_media_manifest.v3":
        errors.append("showcase: public media manifest has the wrong schema_version")
    required_manifest_keys = {
        "schema_version",
        "canonical_version",
        "processing_version",
        "total_entries",
        "datasets",
        "entries",
    }
    if set(manifest) != required_manifest_keys:
        errors.append("showcase: v3 media manifest has unexpected or missing fields")
    if manifest.get("canonical_version") != "v3.0.0":
        errors.append("showcase: v3 media manifest has the wrong canonical version")
    if manifest.get("processing_version") != "v0.4.0":
        errors.append("showcase: v3 media manifest has the wrong processing version")
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list) or set(datasets) != expected_datasets:
        errors.append("showcase: v3 media manifest must list exactly seven datasets")
    serialized_manifest = json.dumps(manifest, ensure_ascii=False).lower()
    for forbidden in ("127.0.0.1", "localhost", "dirty tree", "tmp/"):
        if forbidden in serialized_manifest:
            errors.append(
                f"showcase: public media manifest contains forbidden value {forbidden!r}"
            )
    if re.search(r"(?<![a-z])[a-z]:[\\/]", serialized_manifest):
        errors.append(
            "showcase: public media manifest contains an absolute Windows path"
        )

    items = manifest.get("entries")
    if not isinstance(items, list) or len(items) != 28:
        errors.append(
            "showcase: v3 media manifest must contain exactly twenty-eight GIF records"
        )
        items = []
    if manifest.get("total_entries") != 28:
        errors.append(
            "showcase: v3 media manifest total_entries must equal twenty-eight"
        )
    manifest_media: dict[str, tuple[str, str]] = {}
    roles_by_dataset = {dataset: set() for dataset in expected_datasets}
    exact_item_keys = {
        "dataset",
        "role",
        "sample_id",
        "source",
        "license",
        "label",
        "media",
    }
    for index, item in enumerate(items):
        label = f"v3 media item {index}"
        if not isinstance(item, dict):
            errors.append(f"showcase: {label} must be an object")
            continue
        if set(item) != exact_item_keys:
            errors.append(f"showcase: {label} has unexpected or missing fields")
        dataset = item.get("dataset")
        role = item.get("role")
        if dataset not in expected_datasets:
            errors.append(f"showcase: {label} uses an unknown dataset {dataset!r}")
        elif role in expected_roles:
            if role in roles_by_dataset[dataset]:
                errors.append(f"showcase: duplicate {dataset}/{role} media record")
            roles_by_dataset[dataset].add(role)
        else:
            errors.append(f"showcase: {label} has invalid role {role!r}")
        if not isinstance(item.get("sample_id"), str) or not item.get("sample_id"):
            errors.append(f"showcase: {label} has no sample_id")
        for field in ("source", "license", "label"):
            if not isinstance(item.get(field), str) or not item.get(field):
                errors.append(f"showcase: {label} has no {field}")

        media = item.get("media")
        if not isinstance(media, dict):
            errors.append(f"showcase: {label} has no media record")
            continue
        if not {"path", "width", "height", "bytes"}.issubset(media):
            errors.append(f"showcase: {label} media metadata is incomplete")
        relative_media_path = media.get("path")
        expected_relative_path = f"{dataset}/{role}.gif"
        if relative_media_path != expected_relative_path:
            errors.append(f"showcase: {label} has an invalid v3 media path")
            continue
        media_path = f"doc/showcase/media/{relative_media_path}"
        if media_path in manifest_media:
            errors.append(f"showcase: duplicate public media path {media_path}")
        manifest_media[media_path] = (str(dataset), str(role))
        media_file = ROOT / media_path
        if not media_file.is_file():
            errors.append(f"showcase: missing public media file {media_path}")
        elif media.get("bytes") != media_file.stat().st_size:
            errors.append(f"showcase: {label} byte count disagrees with the media file")
        if (media.get("width"), media.get("height")) != (480, 233):
            errors.append(f"showcase: {label} has incorrect dimensions")

    for dataset, roles in roles_by_dataset.items():
        if roles != expected_roles:
            errors.append(
                f"showcase: {dataset} must provide hero/hands/feet/facing media"
            )

    actual_gallery_gifs = {
        path.relative_to(ROOT).as_posix()
        for path in (showcase / "media").rglob("*.gif")
    }
    if actual_gallery_gifs != set(manifest_media):
        errors.append(
            "showcase: gallery GIF files must exactly match the public media manifest"
        )

    allowlist = policy.get("public_media_allowlist")
    if not isinstance(allowlist, dict) or not allowlist:
        errors.append(
            "showcase: publication policy must define a public media allowlist"
        )
        allowlist = {}
    for asset, asset_policy in allowlist.items():
        if not isinstance(asset, str) or not isinstance(asset_policy, dict):
            errors.append("showcase: invalid public media allowlist record")
            continue
        if asset_policy.get("public_embed_allowed") is not True:
            errors.append(
                f"showcase: allowlisted asset must permit embedding ({asset})"
            )
        asset_path = ROOT / asset
        if not asset_path.is_file():
            errors.append(f"showcase: allowlisted asset is missing ({asset})")
        if asset in manifest_media:
            dataset, role = manifest_media[asset]
            if asset_policy.get("kind") != "retarget-result":
                errors.append(
                    f"showcase: gallery asset must be a retarget-result ({asset})"
                )
            if (
                asset_policy.get("dataset") != dataset
                or asset_policy.get("role") != role
            ):
                errors.append(
                    f"showcase: allowlist metadata disagrees with manifest ({asset})"
                )
            if dataset not in displayed_datasets:
                errors.append(
                    f"showcase: dataset is not approved for display by policy ({asset})"
                )
            if (
                dataset in permission_unverified_datasets
                and asset_policy.get("legal_permission_verified") is not False
            ):
                errors.append(
                    f"showcase: owner-directed asset must not claim verified permission ({asset})"
                )
        elif not str(asset_policy.get("kind", "")).startswith("project-owned-"):
            errors.append(
                f"showcase: non-gallery media must be project-owned ({asset})"
            )
    expected_public_media = {
        path
        for path, (dataset, _) in manifest_media.items()
        if dataset in displayed_datasets
    }
    if not expected_public_media.issubset(allowlist):
        errors.append(
            "showcase: every policy-permitted GIF must appear in the public allowlist"
        )

    linked_local_media: set[str] = set()
    for markdown in DOC_FILES:
        text = markdown.read_text(encoding="utf-8")
        targets = [match.group(1) for match in LINK_RE.finditer(text)]
        targets.extend(html_link_targets(text))
        for raw_target in targets:
            normalized = unquote(raw_target.strip().strip("<>"))
            resolved = local_link_target(markdown, normalized)
            if resolved is None or not resolved.is_relative_to(ROOT):
                continue
            if not PUBLIC_MEDIA_RE.search(resolved.name):
                continue
            identifier = resolved.relative_to(ROOT).as_posix()
            linked_local_media.add(identifier)
            if identifier not in allowlist:
                errors.append(
                    f"showcase: public Markdown links unlisted local media "
                    f"({markdown.relative_to(ROOT).as_posix()}: {normalized})"
                )
    if linked_local_media != set(allowlist):
        missing = set(allowlist) - linked_local_media
        if missing:
            errors.append(
                "showcase: every allowlisted media file must appear in public Markdown "
                f"({', '.join(sorted(missing))})"
            )

    selection = _load_json(
        showcase / "showcase-v3-samples.json", "gallery selection", errors
    )
    if selection is not None:
        if selection.get("schema_version") != "virea.showcase_gallery.v2":
            errors.append("showcase: gallery selection has the wrong schema_version")
        layout = selection.get("layout") or {}
        if layout.get("dataset_count") != 7 or layout.get("items_per_dataset") != 4:
            errors.append(
                "showcase: gallery selection must declare seven datasets and four roles"
            )
        if set(layout.get("roles") or []) != expected_roles:
            errors.append(
                "showcase: gallery selection must declare hero/hands/feet/facing"
            )
        selected_datasets = selection.get("datasets") or {}
        if set(selected_datasets) != expected_datasets:
            errors.append(
                "showcase: gallery selection must contain exactly seven datasets"
            )
        for dataset in expected_datasets:
            rows = selected_datasets.get(dataset, [])
            if not isinstance(rows, list) or len(rows) != 4:
                errors.append(
                    f"showcase: gallery selection {dataset} must have four records"
                )
                continue
            roles = {row.get("role") for row in rows if isinstance(row, dict)}
            if roles != expected_roles:
                errors.append(
                    f"showcase: gallery selection {dataset} has incorrect roles"
                )

    return errors


def main() -> int:
    errors: list[str] = []
    repository_paths = {path.relative_to(ROOT).as_posix() for path in DOC_FILES}
    stale_exemptions = METADATA_EXEMPT - repository_paths
    if stale_exemptions:
        errors.append(
            "documentation metadata exemptions reference missing files: "
            + ", ".join(sorted(stale_exemptions))
        )
    canonical_owners: dict[str, str] = {}
    for path in DOC_FILES:
        errors.extend(check_markdown(path))
        rel = path.relative_to(ROOT).as_posix()
        canonical = frontmatter_scalar(path.read_text(encoding="utf-8"), "canonical")
        if canonical:
            previous = canonical_owners.get(canonical)
            if previous is not None:
                errors.append(
                    f"{rel}: canonical {canonical!r} is already owned by {previous}"
                )
            else:
                canonical_owners[canonical] = rel
    errors.extend(check_bilingual_document_contract(repository_paths))
    errors.extend(check_command_guides())
    errors.extend(check_showcase())
    if errors:
        print("Documentation checks failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Documentation checks passed: {len(DOC_FILES)} Markdown files, "
        "28 v3 media records, 28 explicitly allowlisted retarget GIFs, "
        "exact public-media allowlist enforced without a content-hash gate."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
