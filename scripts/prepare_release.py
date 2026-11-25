"""Validate a stable release tag against source versions and render its canonical notes."""

import argparse
import ast
import json
from pathlib import Path
import re


def prepare(root: Path, tag: str) -> str:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Tag must match vMAJOR.MINOR.PATCH")
    version = tag[1:]
    tree = ast.parse((root / "backend/app/core/version.py").read_text(encoding="utf-8"))
    backend = next(
        (ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)),
        None,
    )
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    versions = {"backend": backend, "frontend": package.get("version"), "lockfile": lock.get("version"),
                "lockfile root": lock.get("packages", {}).get("", {}).get("version")}
    for source, actual in versions.items():
        if actual != version:
            raise ValueError(f"{source} version {actual!r} does not match {tag}")
    dedicated = root / "docs/releases" / f"{tag}.md"
    if dedicated.exists():
        notes = dedicated.read_text(encoding="utf-8").strip()
        lines = notes.splitlines()
        if not lines or lines[0] != "## 📢 版本概述":
            raise ValueError(f"Template notes for {tag} must start with '## 📢 版本概述'")
        if any(re.match(r"^#\s", line) or re.match(
            r"^#{2,6}\s+(?:QBot\s+AI\s+)?v?\d+\.\d+\.\d+(?:\s|$|（|\()", line, re.IGNORECASE
        ) or line.strip("# *") == f"QBot AI {tag}" for line in lines):
            raise ValueError(f"Template notes for {tag} must not repeat the release title or version heading")
        if not any(line.startswith("- ") and line[2:].strip() for line in lines):
            raise ValueError(f"Template notes for {tag} are empty")
        if re.search(r"\[(?:项目名称|版本号|待填写|用户能感知的核心变化|功能名称|问题表现)\]", notes):
            raise ValueError(f"Template notes for {tag} contain unfilled placeholders")
        return notes + "\n"
    lines = (root / "docs/releases/release-notes.md").read_text(encoding="utf-8").splitlines()
    header = re.compile(rf"^## v?{re.escape(version)}(?:\s|（|\()")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        raise ValueError(f"No canonical release notes found for {tag}")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    notes = "\n".join(lines[start:end]).strip()
    if not any(line.startswith("- ") for line in lines[start + 1:end]):
        raise ValueError(f"Release notes for {tag} are empty")
    return notes + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes-output", required=True, type=Path)
    args = parser.parse_args()
    try:
        notes = prepare(Path(__file__).resolve().parents[1], args.tag)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.notes_output.parent.mkdir(parents=True, exist_ok=True)
    args.notes_output.write_text(notes, encoding="utf-8")
    print(f"Validated {args.tag}: source versions match and canonical notes are ready.")


if __name__ == "__main__":
    main()
