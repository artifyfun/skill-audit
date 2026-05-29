from __future__ import annotations
# ruff: noqa: E402

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.install_manifest import REQUIRED_HOOKS
from lib.settings_merge import (
    ConflictError,
    SettingsParseError,
    _ensure_safe_path,
    detect_conflicts,
    load_settings,
    merge_hooks,
)


PRETOOLUSE_TELEMETRY_COMMAND = REQUIRED_HOOKS["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


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


def test_merge_hooks_appends_required_command_in_append_mode() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "printf 'existing-1' >> /tmp/a.log"},
                        {"type": "command", "command": "printf 'existing-2' >> /tmp/b.log"},
                    ],
                },
                {
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": "printf 'read' >> /tmp/read.log"}],
                },
            ]
        },
        "metadata": {"owner": "user"},
    }

    merged, changed = merge_hooks(existing, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    bash_hooks = merged["hooks"]["PreToolUse"][0]["hooks"]
    assert changed is True
    assert bash_hooks == [
        {"type": "command", "command": "printf 'existing-1' >> /tmp/a.log"},
        {"type": "command", "command": "printf 'existing-2' >> /tmp/b.log"},
        {"type": "command", "command": PRETOOLUSE_TELEMETRY_COMMAND},
    ]
    assert merged["hooks"]["PreToolUse"][1] == {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": "printf 'read' >> /tmp/read.log"}],
    }
    assert merged["hooks"]["UserPromptSubmit"] == REQUIRED_HOOKS["hooks"]["UserPromptSubmit"]
    assert merged["metadata"]["owner"] == "user"
    assert merged["metadata"]["skill-audit-managed"] == ["UserPromptSubmit:*"]

    second, second_changed = merge_hooks(merged, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert second_changed is False
    assert second == merged


def test_detect_conflicts_allows_append_mode_for_existing_pretooluse_bash() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "printf 'existing' >> /tmp/a.log"}],
                }
            ]
        }
    }

    conflicts = detect_conflicts(existing, REQUIRED_HOOKS, append_pretooluse_bash=True)

    assert conflicts == []


def test_merge_hooks_force_does_not_replace_user_entry_after_append_mode() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "printf 'existing' >> /tmp/a.log"}],
                }
            ]
        }
    }

    appended, appended_changed = merge_hooks(existing, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert appended_changed is True

    with pytest.raises(ConflictError):
        merge_hooks(appended, REQUIRED_HOOKS, force=True)


def test_merge_hooks_append_mode_does_not_claim_existing_telemetry_only_bash_entry() -> None:
    existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": PRETOOLUSE_TELEMETRY_COMMAND}],
                }
            ]
        }
    }

    merged, changed = merge_hooks(existing, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert changed is True
    assert merged["hooks"]["PreToolUse"] == existing["hooks"]["PreToolUse"]
    assert merged["hooks"]["UserPromptSubmit"] == REQUIRED_HOOKS["hooks"]["UserPromptSubmit"]
    assert merged["metadata"]["skill-audit-managed"] == ["UserPromptSubmit:*"]

    second, second_changed = merge_hooks(merged, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert second_changed is False
    assert second == merged


def test_merge_hooks_append_mode_clears_stale_managed_marker_for_existing_bash_entry() -> None:
    telemetry_only_existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": PRETOOLUSE_TELEMETRY_COMMAND}],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash", "UserPromptSubmit:*"]},
    }

    merged, changed = merge_hooks(telemetry_only_existing, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert changed is True
    assert merged["metadata"]["skill-audit-managed"] == ["UserPromptSubmit:*"]

    forced_again, forced_changed = merge_hooks(merged, REQUIRED_HOOKS, force=True, append_pretooluse_bash=True)

    assert forced_changed is False
    assert forced_again == merged

    user_owned_existing = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {"type": "command", "command": "printf 'user' >> /tmp/bash.log"},
                        {"type": "command", "command": PRETOOLUSE_TELEMETRY_COMMAND},
                    ],
                }
            ]
        },
        "metadata": {"skill-audit-managed": ["PreToolUse:Bash", "UserPromptSubmit:*"]},
    }

    user_merged, user_changed = merge_hooks(user_owned_existing, REQUIRED_HOOKS, force=False, append_pretooluse_bash=True)

    assert user_changed is True
    assert user_merged["metadata"]["skill-audit-managed"] == ["UserPromptSubmit:*"]

    user_forced_again, user_forced_changed = merge_hooks(
        user_merged,
        REQUIRED_HOOKS,
        force=True,
        append_pretooluse_bash=True,
    )

    assert user_forced_changed is False
    assert user_forced_again == user_merged
    assert user_forced_again["hooks"]["PreToolUse"][0]["hooks"] == [
        {"type": "command", "command": "printf 'user' >> /tmp/bash.log"},
        {"type": "command", "command": PRETOOLUSE_TELEMETRY_COMMAND},
    ]


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


def test_ensure_safe_path_rejects_symlink_parent_directory(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    symlink_dir = tmp_path / "linked"
    symlink_dir.symlink_to(real_dir)
    nested_path = symlink_dir / "settings.json"

    with pytest.raises(SettingsParseError) as exc:
        _ensure_safe_path(nested_path)

    assert str(nested_path) in str(exc.value)


def test_ensure_safe_path_rejects_dangling_symlink_file(tmp_path: Path) -> None:
    target_path = tmp_path / "missing.json"
    symlink_path = tmp_path / "settings.json"
    symlink_path.symlink_to(target_path)

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
