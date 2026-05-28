from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lib.install_manifest import INSTALLABLE_PATHS

IGNORED_NAMES = {".DS_Store"}
IGNORED_DIR_NAMES = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".json", ".jsonl"}


@dataclass(frozen=True)
class CopyPlan:
    planned: list[str]
    copied: list[str]
    changed: bool


class InstallTargetError(ValueError):
    pass


def validate_install_dir(install_dir: Path, force: bool) -> None:
    if not install_dir.exists():
        return
    if not install_dir.is_dir():
        raise InstallTargetError(f"install target is not a directory: {install_dir}")
    allowed = {Path(path).parts[0] for path in INSTALLABLE_PATHS}
    existing = {path.name for path in install_dir.iterdir()}
    if not existing.issubset(allowed) and not force:
        raise InstallTargetError(f"install target contains unrelated files: {install_dir}")


def _should_copy(path: Path) -> bool:
    if path.name in IGNORED_NAMES:
        return False
    if any(part in IGNORED_DIR_NAMES for part in path.parts):
        return False
    if path.suffix in IGNORED_SUFFIXES and path.name != "hooks-settings.json":
        return False
    return True


def _copy_file(source: Path, target: Path) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = source.read_bytes()
    if target.exists() and target.read_bytes() == source_bytes:
        return False
    target.write_bytes(source_bytes)
    return True


def copy_installable_paths(source_dir: Path, install_dir: Path, dry_run: bool) -> CopyPlan:
    planned: list[str] = []
    copied: list[str] = []
    changed = False

    for relative_path in INSTALLABLE_PATHS:
        source_path = source_dir / relative_path
        target_path = install_dir / relative_path
        if not source_path.exists():
            continue
        if source_path.is_dir():
            for file_path in sorted(path for path in source_path.rglob("*") if path.is_file() and _should_copy(path)):
                relative_file = file_path.relative_to(source_dir)
                planned.append(str(relative_file))
                if dry_run:
                    continue
                file_changed = _copy_file(file_path, install_dir / relative_file)
                changed = changed or file_changed
                if file_changed:
                    copied.append(str(relative_file))
            continue
        if not _should_copy(source_path):
            continue
        planned.append(relative_path)
        if dry_run:
            continue
        file_changed = _copy_file(source_path, target_path)
        changed = changed or file_changed
        if file_changed:
            copied.append(relative_path)

    return CopyPlan(planned=planned, copied=copied, changed=changed)
