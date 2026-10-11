"""Keep documentation navigation consistent without changing technical content."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_RE = re.compile(r"<!-- BEGIN DOC NAV -->.*?<!-- END DOC NAV -->\s*", re.S)
FOOTER_RE = re.compile(r"<!-- BEGIN DOC FOOTER -->.*?<!-- END DOC FOOTER -->\s*", re.S)
METADATA_RE = re.compile(r"<!--\s*(?:---\s*\n)?type:.*?-->", re.S)


def format_document(text: str, relative_path: str) -> str:
    """Render shared navigation and hide metadata, preserving Markdown anchors."""
    path = ROOT / relative_path
    text = NAV_RE.sub("", FOOTER_RE.sub("", text)).strip()
    metadata = ""
    if text.startswith("---\n"):
        boundary = text.find("\n---\n", 4)
        if boundary >= 0:
            metadata = text[4:boundary].strip()
            text = text[boundary + 5 :].strip()
    if not metadata:
        for match in METADATA_RE.finditer(text):
            if re.search(r"(?m)^canonical:", match.group()):
                metadata = (
                    match.group()[4:-3]
                    .strip()
                    .removeprefix("---")
                    .removesuffix("---")
                    .strip()
                )
                text = (text[: match.start()] + text[match.end() :]).strip()
                break

    chinese = ".zh-CN." in relative_path
    language = "zh-CN" if chinese else "en"

    def link(label: str, target: str) -> str:
        return (
            f"[{label}]({Path(os.path.relpath(ROOT / target, path.parent)).as_posix()})"
        )

    navigation = " · ".join(
        [
            link("✦ VIREA", "README.zh-CN.md" if chinese else "README.md"),
            link("文档" if chinese else "Documentation", f"doc/README.{language}.md"),
            link(
                "部署" if chinese else "Set Up",
                f"doc/getting-started/automatic-setup.{language}.md",
            ),
            link("演示" if chinese else "Demos", f"doc/demos/README.{language}.md"),
        ]
    )
    counterpart = (
        relative_path.replace(".zh-CN.md", ".en.md")
        if chinese
        else relative_path.replace(".en.md", ".zh-CN.md")
    )
    if counterpart != relative_path and (ROOT / counterpart).exists():
        navigation += " · " + link("English" if chinese else "简体中文", counterpart)
    footer = " · ".join(
        [
            link(
                "📚 文档地图" if chinese else "📚 Documentation map",
                f"doc/catalog.{language}.md",
            ),
            link(
                "🛠️ 故障排查" if chinese else "🛠️ Troubleshooting",
                f"doc/operations/troubleshooting.{language}.md",
            ),
            link("🤝 参与贡献" if chinese else "🤝 Contributing", "CONTRIBUTING.md"),
        ]
    )
    result = f"<!-- BEGIN DOC NAV -->\n{navigation}\n<!-- END DOC NAV -->\n\n{text}\n\n<!-- BEGIN DOC FOOTER -->\n---\n\n{footer}\n<!-- END DOC FOOTER -->\n"
    if metadata:
        result += f"\n<!--\n{metadata}\n-->\n"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    tracked = subprocess.check_output(
        ["git", "ls-files", "doc"], cwd=ROOT, text=True
    ).splitlines()
    paths = sorted(
        {ROOT / p for p in tracked if p.endswith(".md")}
        | set((ROOT / "doc").rglob("*.md"))
    )
    paths += [ROOT / "CONTRIBUTING.md", ROOT / "SECURITY.md"]
    changes = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        current = path.read_text(encoding="utf-8")
        expected = format_document(current, relative)
        if current != expected:
            changes.append(relative)
            if not args.check:
                path.write_text(expected, encoding="utf-8", newline="\n")
    if args.check and changes:
        print("Documentation layout needs regeneration:\n" + "\n".join(changes))
        return 1
    print(f"Documentation layout: {len(paths)} pages checked, {len(changes)} updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
