"""Preserve trusted custom plugin files before a native release directory switch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
from uuid import uuid4

BUILTIN_IDS = {"dice", "keyword_reply"}
PERMISSIONS = {"message:reply", "storage:config", "ai:request", "http:request"}


def validated_manifest(folder: Path, *, default_id: str | None = None) -> dict:
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Plugin source must be a directory, not a symlink")
    for name in ("plugin.json", "main.py"):
        entry = folder / name
        if entry.is_symlink() or not entry.is_file():
            raise ValueError("Plugin manifest and entry point must be regular files")
    manifest = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Plugin manifest must be an object")
    identifier = manifest.get("id", default_id or folder.name)
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", identifier):
        raise ValueError("Plugin identifier is invalid")
    permissions = manifest.get("permissions", ["message:reply"])
    if not isinstance(permissions, list) or any(not isinstance(item, str) or item not in PERMISSIONS for item in permissions):
        raise ValueError("Plugin permission declaration is invalid")
    if not isinstance(manifest.get("config", {}), dict):
        raise ValueError("Plugin configuration must be an object")
    commands = manifest.get("commands", [])
    if not isinstance(commands, list) or any(not isinstance(item, dict) or not isinstance(item.get("name"), str) for item in commands):
        raise ValueError("Plugin commands must have names")
    return {**manifest, "id": identifier}


def _regular_tree(folder: Path) -> None:
    if any(path.is_symlink() or not (path.is_dir() or path.is_file()) for path in folder.rglob("*")):
        raise ValueError("Custom plugin trees must contain only regular files and directories")


def persist_custom_plugins(source: Path, destination: Path, *, owner: tuple[int, int] | None = None) -> dict[str, list[str]]:
    """Copy validated files without executing code or replacing existing extensions."""
    if not source.exists():
        return {"copied": [], "preserved": []}
    if source.is_symlink() or not source.is_dir() or destination.is_symlink():
        raise ValueError("Plugin roots must not be symlinks")
    if source.resolve() == destination.resolve():
        return {"copied": [], "preserved": []}
    destination.mkdir(parents=True, mode=0o750, exist_ok=True)
    if owner is not None:
        os.chown(destination, *owner)
    results: dict[str, list[str]] = {"copied": [], "preserved": []}
    seen = set()
    for folder in sorted(source.iterdir()):
        if not folder.is_dir() or not (folder / "plugin.json").exists():
            continue
        manifest = validated_manifest(folder)
        identifier = manifest["id"]
        if identifier in seen:
            raise ValueError("More than one custom plugin declares the same identifier")
        seen.add(identifier)
        if identifier in BUILTIN_IDS and manifest.get("builtin") is True:
            continue
        _regular_tree(folder)
        target = destination / identifier
        if target.exists() or target.is_symlink():
            existing = validated_manifest(target)
            if existing["id"] != identifier:
                raise ValueError("Existing extension has a conflicting plugin identifier")
            _regular_tree(target)
            results["preserved"].append(identifier)
            continue
        temporary = destination / f".{identifier}.migrate-{uuid4().hex}"
        try:
            shutil.copytree(folder, temporary, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            validated_manifest(temporary, default_id=identifier)
            _regular_tree(temporary)
            if owner is not None:
                for path in [temporary, *temporary.rglob("*")]:
                    os.chown(path, *owner)
                    os.chmod(path, stat.S_IMODE(path.stat().st_mode) & 0o770)
            temporary.rename(target)
            results["copied"].append(identifier)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return results
