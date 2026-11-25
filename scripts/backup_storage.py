"""Verify backup streams before publication, pruning, or restoration."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4


def verify(path: Path, *, check_manifest: bool = True) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Backup must be a regular file")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if check_manifest:
        manifest = path.with_name(path.name + ".sha256")
        if manifest.exists():
            expected = manifest.read_text(encoding="ascii").split()
            if len(expected) != 2 or expected != [digest, path.name]:
                raise ValueError("Backup SHA-256 mismatch")
        else:
            print("WARNING: legacy backup has no SHA-256 sidecar; gzip integrity only, verify its source.", file=sys.stderr)
    size = 0
    with gzip.open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
    if not size:
        raise ValueError("Backup contains an empty database dump")
    return digest


def finalize(temporary: Path, target: Path, *, keep: int = 14) -> None:
    if keep < 1 or temporary.parent.resolve() != target.parent.resolve() or target.exists():
        raise ValueError("Invalid backup publication target or retention")
    digest = verify(temporary, check_manifest=False)
    manifest = target.with_name(target.name + ".sha256")
    pending_manifest = target.with_name(f".{target.name}.{uuid4().hex}.sha256.tmp")
    try:
        with pending_manifest.open("x", encoding="ascii") as out:
            out.write(f"{digest}  {target.name}\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, target)
        os.replace(pending_manifest, manifest)
    finally:
        pending_manifest.unlink(missing_ok=True)
    # Retention only follows a fully checked, published backup and its digest.
    completed = sorted(target.parent.glob("qbot-*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in completed[keep:]:
        if stale.is_symlink():
            continue
        stale.unlink()
        stale.with_name(stale.name + ".sha256").unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify")
    check.add_argument("archive", type=Path)
    revision = commands.add_parser("revision")
    revision.add_argument("value")
    publish = commands.add_parser("finalize")
    publish.add_argument("temporary", type=Path)
    publish.add_argument("target", type=Path)
    publish.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    if args.command == "verify":
        verify(args.archive)
    elif args.command == "finalize":
        finalize(args.temporary, args.target, keep=args.keep)
    else:
        known = set()
        for source in (Path(__file__).resolve().parents[1] / "backend/migrations/versions").glob("*.py"):
            for node in ast.parse(source.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "revision" for target in node.targets):
                    known.add(ast.literal_eval(node.value))
        if args.value not in known:
            raise ValueError("Backup revision is missing, ambiguous, or unknown; restoration refused")


if __name__ == "__main__":
    main()
