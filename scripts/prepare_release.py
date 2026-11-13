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
