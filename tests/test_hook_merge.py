from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.install_manifest import REQUIRED_HOOKS
from lib.settings_merge import ConflictError, SettingsParseError, _ensure_safe_path, detect_conflicts, load_settings, merge_hooks


def test_merge_hooks_adds_required_entries() -> None:
    merged, changed = merge_hooks({}, REQUIRED_HOOKS, force=False)

    assert changed is True
    assert merged["hooks"] == REQUIRED_HOOKS["hooks"]
    assert merged["metadata"]["skill-audit-managed"] == ["PreToolUse:Bash", "UserPromptSubmit:*"]


def test_merge_hooks_is_idempotent() -> None:
    first, first_changed = merge_hooks({}, REQUIRED_HOOKS, force=False)
    second, second_changed = merge_hooks(first, REQUIRED_HOOKS, force=False)

    assert first_changed is True
    assert second_changed is False
    assert second == first


def test_detect_conflicts_reports_mismatched_existing_managed_hook() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash"]},
    }

    conflicts = detect_conflicts(existing, REQUIRED_HOOKS)

    assert conflicts == ["hooks.PreToolUse[matcher=Bash]"]


def test_detect_conflicts_allows_managed_replacement_with_force() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash"]},
    }

    conflicts = detect_conflicts(existing, REQUIRED_HOOKS, force=True)

    assert conflicts == []


def test_detect_conflicts_reports_unmanaged_same_matcher_hook() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        }
    }

    conflicts = detect_conflicts(existing, REQUIRED_HOOKS)

    assert conflicts == ["hooks.PreToolUse[matcher=Bash]"]


def test_merge_hooks_rejects_conflicting_entries_without_force() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash"]},
    }

    with pytest.raises(ConflictError):
        merge_hooks(existing, REQUIRED_HOOKS, force=False)


def test_merge_hooks_does_not_replace_unmanaged_same_matcher_hook_with_force() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        }
    }

    with pytest.raises(ConflictError):
        merge_hooks(existing, REQUIRED_HOOKS, force=True)


def test_merge_hooks_replaces_managed_same_matcher_hook_with_force() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "printf 'different' >> ~/.claude/skills/skill-audit-usage.jsonl",
                        }
                    ],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash"]},
    }

    merged, changed = merge_hooks(existing, REQUIRED_HOOKS, force=True)

    assert changed is True
    assert merged["hooks"]["PreToolUse"] == REQUIRED_HOOKS["hooks"]["PreToolUse"]


def test_load_settings_raises_for_invalid_json(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(SettingsParseError) as exc:
        load_settings(settings_path)

    assert str(settings_path) in str(exc.value)


def test_ensure_safe_path_rejects_symlink_file(tmp_path: Path) -> None:
    real_path = tmp_path / "real.json"
    real_path.write_text("{}", encoding="utf-8")
    symlink_path = tmp_path / "settings.json"
    symlink_path.symlink_to(real_path)

    with pytest.raises(SettingsParseError) as exc:
        _ensure_safe_path(symlink_path)

    assert str(symlink_path) in str(exc.value)


def test_merge_hooks_rejects_non_list_event_entries() -> None:
    existing = {
        "hooks": {
            "PreToolUse": {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "printf 'different'"}],
            }
        }
    }

    with pytest.raises(ConflictError) as exc:
        merge_hooks(existing, REQUIRED_HOOKS, force=False)

    assert exc.value.conflicts == ["hooks.PreToolUse"]
