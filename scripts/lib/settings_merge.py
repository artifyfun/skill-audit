from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Any, Final


MANAGED_HOOKS_KEY: Final = "skill-audit-managed"
JsonDict = dict[str, Any]
CommandFingerprint = tuple[tuple[str, str], ...]


class SettingsParseError(ValueError):
    pass


class ConflictError(ValueError):
    def __init__(self, conflicts: list[str]):
        self.conflicts = conflicts
        super().__init__("hook merge conflict: " + ", ".join(conflicts))



def _ensure_safe_path(path: PathLike[str] | str) -> Path:
    candidate_path = Path(path).expanduser()
    for path_part in (candidate_path, *candidate_path.parents):
        if path_part.is_symlink():
            raise SettingsParseError(f"refusing to use symlink path: {candidate_path}")
    return candidate_path.resolve(strict=False)



def load_settings(path: Path) -> JsonDict:
    path = _ensure_safe_path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SettingsParseError(f"invalid settings JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SettingsParseError(f"invalid settings JSON at {path}: root must be an object")
    return data



def settings_to_text(settings: JsonDict) -> str:
    return json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + "\n"



def write_settings(path: Path, settings: JsonDict) -> None:
    path = _ensure_safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings_to_text(settings), encoding="utf-8")



def backup_settings(path: Path) -> Path | None:
    path = _ensure_safe_path(path)
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = _ensure_safe_path(path.with_name(f"{path.name}.bak.{timestamp}"))
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path



def _command_fingerprint(entry: JsonDict) -> tuple[str, CommandFingerprint]:
    matcher = str(entry.get("matcher") or "")
    hooks = entry.get("hooks") or []
    normalized: list[tuple[str, str]] = []
    if isinstance(hooks, list):
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            normalized.append((str(hook.get("type") or ""), str(hook.get("command") or "")))
    return matcher, tuple(normalized)



def _managed_key(event_name: str, matcher: str) -> str:
    return f"{event_name}:{matcher}"



def _event_conflict_path(event_name: str, matcher: str) -> str:
    return f"hooks.{event_name}[matcher={matcher}]"



def _get_managed_hooks(settings: JsonDict) -> set[str]:
    managed = settings.get("metadata", {}).get(MANAGED_HOOKS_KEY, [])
    if not isinstance(managed, list):
        return set()
    return {value for value in managed if isinstance(value, str)}



def _set_managed_hooks(settings: JsonDict, managed_hooks: set[str]) -> None:
    metadata = settings.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        settings["metadata"] = metadata
    metadata[MANAGED_HOOKS_KEY] = sorted(managed_hooks)



def _matching_entries(entries: list[Any], matcher: str) -> list[tuple[int, JsonDict]]:
    matches: list[tuple[int, JsonDict]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_matcher, _ = _command_fingerprint(entry)
        if entry_matcher == matcher:
            matches.append((index, entry))
    return matches



def _find_matching_entry_index(entries: list[Any], matcher: str, commands: CommandFingerprint) -> int | None:
    for index, entry in _matching_entries(entries, matcher):
        _, entry_commands = _command_fingerprint(entry)
        if entry_commands == commands:
            return index
    return None



def _find_managed_entry_index(
    entries: list[Any],
    event_name: str,
    matcher: str,
    managed_hooks: set[str],
    required_commands: CommandFingerprint | None = None,
) -> int | None:
    managed_key = _managed_key(event_name, matcher)
    if managed_key not in managed_hooks:
        return None
    matches = _matching_entries(entries, matcher)
    if len(matches) != 1:
        return None
    index, entry = matches[0]
    if required_commands is not None:
        _, entry_commands = _command_fingerprint(entry)
        if set(required_commands).issubset(entry_commands) and entry_commands != required_commands:
            return None
    return index



def _has_matcher_conflict(entries: list[Any], event_name: str, matcher: str, managed_hooks: set[str]) -> bool:
    matches = _matching_entries(entries, matcher)
    if not matches:
        return False
    return True



def detect_conflicts(
    existing: JsonDict,
    required: JsonDict,
    force: bool = False,
    append_pretooluse_bash: bool = False,
) -> list[str]:
    conflicts: list[str] = []
    existing_hooks = existing.get("hooks")
    required_hooks = required.get("hooks")
    managed_hooks = _get_managed_hooks(existing)
    if not isinstance(existing_hooks, dict) or not isinstance(required_hooks, dict):
        return conflicts

    for event_name, required_entries in required_hooks.items():
        if not isinstance(required_entries, list):
            continue
        current_entries = existing_hooks.get(event_name)
        if current_entries is None:
            continue
        if not isinstance(current_entries, list):
            conflicts.append(f"hooks.{event_name}")
            continue

        for required_entry in required_entries:
            if not isinstance(required_entry, dict):
                continue
            matcher, commands = _command_fingerprint(required_entry)
            if _find_matching_entry_index(current_entries, matcher, commands) is not None:
                continue
            if (
                force
                and _find_managed_entry_index(
                    current_entries,
                    event_name,
                    matcher,
                    managed_hooks,
                    required_commands=commands,
                )
                is not None
            ):
                continue
            if append_pretooluse_bash and event_name == "PreToolUse" and matcher == "Bash":
                continue
            if _has_matcher_conflict(current_entries, event_name, matcher, managed_hooks):
                conflicts.append(_event_conflict_path(event_name, matcher))
    return sorted(set(conflicts))



def _ensure_managed_marker(event_name: str, matcher: str, managed_hooks: set[str]) -> bool:
    managed_key = _managed_key(event_name, matcher)
    if managed_key in managed_hooks:
        return False
    managed_hooks.add(managed_key)
    return True



def _append_required_entry(
    entries: list[Any],
    required_entry: JsonDict,
    event_name: str,
    matcher: str,
    managed_hooks: set[str],
) -> bool:
    if _has_matcher_conflict(entries, event_name, matcher, managed_hooks):
        raise ConflictError([_event_conflict_path(event_name, matcher)])
    entries.append(copy.deepcopy(required_entry))
    managed_hooks.add(_managed_key(event_name, matcher))
    return True



def _replace_managed_entry(
    entries: list[Any],
    required_entry: JsonDict,
    event_name: str,
    matcher: str,
    managed_hooks: set[str],
) -> bool:
    replacement_index = _find_managed_entry_index(
        entries,
        event_name,
        matcher,
        managed_hooks,
        required_commands=_command_fingerprint(required_entry)[1],
    )
    if replacement_index is None:
        raise ConflictError([_event_conflict_path(event_name, matcher)])
    entries[replacement_index] = copy.deepcopy(required_entry)
    managed_hooks.add(_managed_key(event_name, matcher))
    return True



def _append_pretooluse_bash_command(
    entries: list[Any],
    required_entry: JsonDict,
    event_name: str,
    matcher: str,
    commands: CommandFingerprint,
    managed_hooks: set[str],
) -> bool:
    matches = _matching_entries(entries, matcher)
    if len(matches) != 1:
        raise ConflictError([_event_conflict_path(event_name, matcher)])

    index, entry = matches[0]
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        raise ConflictError([_event_conflict_path(event_name, matcher)])

    existing_commands = {tuple(command) for command in _command_fingerprint(entry)[1]}
    managed_hooks.discard(_managed_key(event_name, matcher))
    changed = False
    for hook_type, command in commands:
        if (hook_type, command) in existing_commands:
            continue
        hooks.append({"type": hook_type, "command": command})
        existing_commands.add((hook_type, command))
        changed = True

    entries[index] = entry
    return changed



def _merge_required_entry(
    entries: list[Any],
    required_entry: JsonDict,
    event_name: str,
    managed_hooks: set[str],
    force: bool,
    append_pretooluse_bash: bool,
) -> bool:
    matcher, commands = _command_fingerprint(required_entry)
    if append_pretooluse_bash and event_name == "PreToolUse" and matcher == "Bash":
        return _append_pretooluse_bash_command(entries, required_entry, event_name, matcher, commands, managed_hooks)
    if _find_matching_entry_index(entries, matcher, commands) is not None:
        return _ensure_managed_marker(event_name, matcher, managed_hooks)
    if force and _find_managed_entry_index(entries, event_name, matcher, managed_hooks) is not None:
        return _replace_managed_entry(entries, required_entry, event_name, matcher, managed_hooks)
    return _append_required_entry(entries, required_entry, event_name, matcher, managed_hooks)



def merge_hooks(
    existing: JsonDict,
    required: JsonDict,
    force: bool,
    append_pretooluse_bash: bool = False,
) -> tuple[JsonDict, bool]:
    if not force:
        conflicts = detect_conflicts(
            existing,
            required,
            force=False,
            append_pretooluse_bash=append_pretooluse_bash,
        )
        if conflicts:
            raise ConflictError(conflicts)

    merged = copy.deepcopy(existing)
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsParseError("invalid settings JSON: hooks must be an object")

    changed = False
    required_hooks = required.get("hooks")
    if not isinstance(required_hooks, dict):
        return merged, changed

    managed_hooks = _get_managed_hooks(merged)

    for event_name, required_entries in required_hooks.items():
        if not isinstance(required_entries, list):
            continue
        current_entries = hooks.get(event_name)
        if current_entries is None:
            current_entries = []
            hooks[event_name] = current_entries
        elif not isinstance(current_entries, list):
            raise ConflictError([f"hooks.{event_name}"])

        for required_entry in required_entries:
            if not isinstance(required_entry, dict):
                continue
            changed = _merge_required_entry(
                current_entries,
                required_entry,
                event_name,
                managed_hooks,
                force=force,
                append_pretooluse_bash=append_pretooluse_bash,
            ) or changed

    _set_managed_hooks(merged, managed_hooks)
    return merged, changed
