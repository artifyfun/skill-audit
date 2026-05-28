#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.install_manifest import REQUIRED_HOOKS
from lib.install_skill import InstallTargetError, copy_installable_paths, validate_install_dir
from lib.settings_merge import ConflictError, backup_settings, load_settings, merge_hooks, write_settings


@dataclass(frozen=True)
class InstallResult:
    changed: bool
    installed: bool
    hooks_merged: bool
    planned_copies: list[str]
    copied_paths: list[str]
    planned_settings_change: bool
    settings_backup: str | None
    conflicts: list[str]


def run_install(
    source_dir: Path,
    install_dir: Path,
    settings_path: Path,
    with_hooks: bool,
    dry_run: bool = False,
    force: bool = False,
    backup: bool = False,
) -> InstallResult:
    validate_install_dir(install_dir, force=force)

    settings_backup: str | None = None
    hooks_merged = False
    planned_settings_change = False
    conflicts: list[str] = []

    if with_hooks:
        settings = load_settings(settings_path)
        try:
            merged_settings, hooks_changed = merge_hooks(settings, REQUIRED_HOOKS, force=force)
        except ConflictError as exc:
            conflicts = exc.conflicts
            return InstallResult(
                changed=False,
                installed=False,
                hooks_merged=False,
                planned_copies=[],
                copied_paths=[],
                planned_settings_change=False,
                settings_backup=None,
                conflicts=conflicts,
            )
        planned_settings_change = hooks_changed

    copy_plan = copy_installable_paths(source_dir=source_dir, install_dir=install_dir, dry_run=dry_run)
    changed = copy_plan.changed

    if with_hooks and not dry_run and planned_settings_change:
        backup_path = backup_settings(settings_path)
        if backup_path is None and backup:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_backup = str(backup_path) if backup_path else None
        write_settings(settings_path, merged_settings)
        hooks_merged = True
        changed = True

    return InstallResult(
        changed=changed,
        installed=bool(copy_plan.copied),
        hooks_merged=hooks_merged,
        planned_copies=copy_plan.planned,
        copied_paths=copy_plan.copied,
        planned_settings_change=planned_settings_change,
        settings_backup=settings_backup,
        conflicts=conflicts,
    )


def default_install_dir(target: str, cwd: Path) -> Path:
    if target == "global":
        return Path.home() / ".claude/skills/skill-audit"
    return cwd / ".claude/skills/skill-audit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["global", "project"], default="global")
    parser.add_argument("--with-hooks", dest="with_hooks", action="store_true", default=True)
    parser.add_argument("--without-hooks", dest="with_hooks", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--settings", type=Path, default=Path.home() / ".claude/settings.json")
    parser.add_argument("--backup", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = Path(__file__).resolve().parent.parent
    install_dir = default_install_dir(args.target, Path.cwd())
    try:
        result = run_install(
            source_dir=source_dir,
            install_dir=install_dir,
            settings_path=args.settings,
            with_hooks=args.with_hooks,
            dry_run=args.dry_run,
            force=args.force,
            backup=args.backup,
        )
    except (InstallTargetError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"status": "ok", **asdict(result)}, ensure_ascii=False, indent=2))
    return 1 if result.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
