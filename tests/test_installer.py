from __future__ import annotations
# ruff: noqa: E402

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from install import run_install
from lib.settings_merge import SettingsParseError


FILES_TO_COPY = {
    "SKILL.md": "skill spec\n",
    "README.md": "readme\n",
    ".gitignore": "*.pyc\n",
    "scripts/scan_skills.py": "print('scan skills')\n",
    "scripts/scan_usage.py": "print('scan usage')\n",
    "examples/hooks-settings.json": json.dumps(
        {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "matcher": "*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "input=$(cat); prompt=$(printf '%s' \"$input\" | jq -r '.user_prompt // empty'); jq -cn --arg prompt \"$prompt\" '{event:\"prompt\",prompt:$prompt}' >> ~/.claude/skills/skill-audit-usage.jsonl",
                            }
                        ],
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "input=$(cat); cmd=$(printf '%s' \"$input\" | jq -r '.tool_input.command // empty'); jq -cn --arg command \"$cmd\" '{event:\"pre_tool\",tool:\"Bash\",command:$command}' >> ~/.claude/skills/skill-audit-usage.jsonl",
                            }
                        ],
                    }
                ],
            }
        },
        indent=2,
    )
    + "\n",
}


def make_source_tree(root: Path) -> Path:
    source_dir = root / "source"
    copy_paths = [
        ".gitignore",
        "SKILL.md",
        "README.md",
        "scripts/install.py",
        "scripts/scan_skills.py",
        "scripts/scan_usage.py",
        "scripts/lib/__init__.py",
        "scripts/lib/install_manifest.py",
        "scripts/lib/install_skill.py",
        "scripts/lib/settings_merge.py",
        "examples/hooks-settings.json",
    ]
    for relative_path in copy_paths:
        source_path = ROOT / relative_path
        file_path = source_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    for relative_path, content in FILES_TO_COPY.items():
        file_path = source_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return source_dir


def test_dry_run_reports_operations_without_writing_files(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        dry_run=True,
    )

    assert install_dir.exists() is False
    assert settings_path.exists() is False
    assert result.changed is False
    assert result.planned_copies
    assert result.planned_settings_change is True
    assert result.conflicts == []


def test_copy_install_copies_files_and_writes_settings(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    assert result.changed is True
    assert (install_dir / "SKILL.md").read_text(encoding="utf-8") == "skill spec\n"
    assert (install_dir / "scripts/scan_usage.py").read_text(encoding="utf-8") == "print('scan usage')\n"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "UserPromptSubmit" in settings["hooks"]
    assert "PreToolUse" in settings["hooks"]
    assert settings["metadata"]["skill-audit-managed"] == ["PreToolUse:Bash", "UserPromptSubmit:*"]


def test_hook_merge_is_idempotent_when_run_twice(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"

    first = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )
    after_first = settings_path.read_text(encoding="utf-8")

    second = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )
    after_second = settings_path.read_text(encoding="utf-8")

    assert first.changed is True
    assert second.changed is False
    assert after_first == after_second


def test_conflict_detection_rejects_non_matching_existing_managed_hook(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "printf 'different' >> /tmp/out.jsonl"}
                            ],
                        }
                    ]
                },
                "metadata": {"skill-audit-managed": ["UserPromptSubmit:*"]},
            }
        ),
        encoding="utf-8",
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    assert result.changed is False
    assert result.conflicts == ["hooks.UserPromptSubmit[matcher=*]"]
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "printf 'different' >> /tmp/out.jsonl"


def test_force_does_not_replace_unmanaged_same_matcher_hook(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "printf 'different' >> /tmp/out.jsonl"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        force=True,
    )

    assert result.changed is False
    assert result.conflicts == ["hooks.UserPromptSubmit[matcher=*]"]


def test_force_replaces_existing_managed_hook(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "printf 'different' >> /tmp/out.jsonl"}
                            ],
                        }
                    ]
                },
                "metadata": {"skill-audit-managed": ["UserPromptSubmit:*"]},
            }
        ),
        encoding="utf-8",
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        force=True,
    )

    assert result.changed is True
    assert result.conflicts == []
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] != "printf 'different' >> /tmp/out.jsonl"
    assert settings["hooks"]["PreToolUse"] == json.loads(FILES_TO_COPY["examples/hooks-settings.json"])["hooks"]["PreToolUse"]
    assert settings["metadata"]["skill-audit-managed"] == ["PreToolUse:Bash", "UserPromptSubmit:*"]
    assert result.hooks_merged is True
    assert result.planned_settings_change is True


def test_run_install_reports_conflicts_without_writing_settings(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "printf 'different' >> /tmp/out.jsonl"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    before = settings_path.read_text(encoding="utf-8")
    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        force=True,
    )

    assert result.conflicts == ["hooks.UserPromptSubmit[matcher=*]"]
    assert result.hooks_merged is False
    assert result.planned_settings_change is False
    assert settings_path.read_text(encoding="utf-8") == before
    assert sorted(settings_path.parent.glob("settings.json.bak.*")) == []


def test_run_install_reports_pretooluse_conflict_by_default(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "printf 'existing' >> /tmp/bash.log"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    before = settings_path.read_text(encoding="utf-8")
    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    assert result.conflicts == ["hooks.PreToolUse[matcher=Bash]"]
    assert result.hooks_merged is False
    assert result.planned_settings_change is False
    assert settings_path.read_text(encoding="utf-8") == before


def test_run_install_appends_pretooluse_hook_in_append_mode(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "printf 'existing' >> /tmp/bash.log"}
                            ],
                        }
                    ]
                },
                "metadata": {"owner": "user"},
            }
        ),
        encoding="utf-8",
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        append_pretooluse_bash=True,
    )

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    bash_hooks = settings["hooks"]["PreToolUse"][0]["hooks"]
    telemetry_command = json.loads(FILES_TO_COPY["examples/hooks-settings.json"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    assert result.conflicts == []
    assert result.hooks_merged is True
    assert result.planned_settings_change is True
    assert bash_hooks == [
        {"type": "command", "command": "printf 'existing' >> /tmp/bash.log"},
        {"type": "command", "command": telemetry_command},
    ]
    assert settings["metadata"]["owner"] == "user"
    assert settings["metadata"]["skill-audit-managed"] == ["UserPromptSubmit:*"]



def test_run_install_force_still_reports_pretooluse_conflict_after_append_mode(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "printf 'existing' >> /tmp/bash.log"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    appended = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        append_pretooluse_bash=True,
    )
    forced = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        force=True,
    )

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    bash_hooks = settings["hooks"]["PreToolUse"][0]["hooks"]
    telemetry_command = json.loads(FILES_TO_COPY["examples/hooks-settings.json"])["hooks"]["PreToolUse"][0]["hooks"][0]["command"]

    assert appended.conflicts == []
    assert forced.conflicts == ["hooks.PreToolUse[matcher=Bash]"]
    assert forced.hooks_merged is False
    assert bash_hooks == [
        {"type": "command", "command": "printf 'existing' >> /tmp/bash.log"},
        {"type": "command", "command": telemetry_command},
    ]


def test_cli_returns_non_zero_on_conflict(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        file_path = repo_root / source_path.relative_to(source_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {"type": "command", "command": "printf 'different' >> /tmp/out.jsonl"}
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/install.py"),
            "--target",
            "project",
            "--with-hooks",
            "--force",
            "--settings",
            str(settings_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 1
    assert payload["conflicts"] == ["hooks.UserPromptSubmit[matcher=*]"]
    assert payload["status"] == "ok"



def test_cli_with_hooks_creates_backup_without_backup_flag(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        file_path = repo_root / source_path.relative_to(source_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    settings_path = tmp_path / "settings.json"
    original_settings = {"hooks": {"OtherEvent": []}}
    settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/install.py"),
            "--target",
            "project",
            "--with-hooks",
            "--settings",
            str(settings_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    backup_files = sorted(settings_path.parent.glob("settings.json.bak.*"))

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert payload["settings_backup"] is not None
    assert len(backup_files) == 1
    assert Path(payload["settings_backup"]).read_text(encoding="utf-8") == json.dumps(original_settings)


def test_cli_with_backup_flag_creates_backup_when_settings_change(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        file_path = repo_root / source_path.relative_to(source_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    settings_path = tmp_path / "settings.json"
    original_settings = {"hooks": {"OtherEvent": []}}
    settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/install.py"),
            "--target",
            "project",
            "--with-hooks",
            "--backup",
            "--settings",
            str(settings_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    backup_files = sorted(settings_path.parent.glob("settings.json.bak.*"))

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert payload["settings_backup"] is not None
    assert len(backup_files) == 1
    assert Path(payload["settings_backup"]).read_text(encoding="utf-8") == json.dumps(original_settings)
    assert payload["planned_settings_change"] is True
    assert payload["hooks_merged"] is True
    assert payload["changed"] is True
    assert payload["settings_backup"] == str(backup_files[0])
    assert json.loads(settings_path.read_text(encoding="utf-8"))["hooks"]["OtherEvent"] == []


def test_parse_args_defaults_to_global_target_and_hooks_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["install.py"])

    args = __import__("install").parse_args()

    assert args.target == "global"
    assert args.with_hooks is True


def test_cli_defaults_install_to_global_and_merges_hooks(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        file_path = repo_root / source_path.relative_to(source_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    fake_home = tmp_path / "home"
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"hooks": {"OtherEvent": []}}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts/install.py")],
        cwd=repo_root,
        env={"HOME": str(fake_home)},
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    install_dir = fake_home / ".claude" / "skills" / "skill-audit"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert payload["hooks_merged"] is True
    assert payload["planned_settings_change"] is True
    assert (install_dir / "SKILL.md").exists()
    assert settings["hooks"]["OtherEvent"] == []
    assert "UserPromptSubmit" in settings["hooks"]
    assert "PreToolUse" in settings["hooks"]


def test_cli_without_hooks_skips_settings_changes(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        file_path = repo_root / source_path.relative_to(source_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    fake_home = tmp_path / "home"
    settings_path = fake_home / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    original_settings = {"hooks": {"OtherEvent": []}}
    settings_path.write_text(json.dumps(original_settings), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts/install.py"), "--without-hooks"],
        cwd=repo_root,
        env={"HOME": str(fake_home)},
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    install_dir = fake_home / ".claude" / "skills" / "skill-audit"

    assert result.returncode == 0
    assert payload["status"] == "ok"
    assert payload["hooks_merged"] is False
    assert payload["planned_settings_change"] is False
    assert payload["settings_backup"] is None
    assert (install_dir / "SKILL.md").exists()
    assert json.loads(settings_path.read_text(encoding="utf-8")) == original_settings
























































































































































































































































































































































































def test_backup_flag_does_not_create_backup_when_settings_are_unchanged(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"

    run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        backup=True,
    )

    backup_files = sorted(settings_path.parent.glob("settings.json.bak.*"))

    assert result.changed is False
    assert result.settings_backup is None
    assert backup_files == []


def test_settings_change_creates_backup_without_backup_flag(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {"OtherEvent": []}}), encoding="utf-8")

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    backup_files = sorted(settings_path.parent.glob("settings.json.bak.*"))

    assert result.changed is True
    assert result.settings_backup is not None
    assert len(backup_files) == 1
    assert Path(result.settings_backup).read_text(encoding="utf-8") == json.dumps({"hooks": {"OtherEvent": []}})



def test_settings_change_creates_backup_when_backup_flag_is_set(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"hooks": {"OtherEvent": []}}), encoding="utf-8")

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
        backup=True,
    )

    backup_files = sorted(settings_path.parent.glob("settings.json.bak.*"))

    assert result.changed is True
    assert result.settings_backup is not None
    assert len(backup_files) == 1
    assert Path(result.settings_backup).read_text(encoding="utf-8") == json.dumps({"hooks": {"OtherEvent": []}})


def test_invalid_settings_json_returns_clear_error(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(SettingsParseError) as exc_info:
        run_install(
            source_dir=source_dir,
            install_dir=install_dir,
            settings_path=settings_path,
            with_hooks=True,
        )

    assert str(settings_path) in str(exc_info.value)


def test_non_list_hook_section_returns_conflict_without_write(tmp_path: Path) -> None:
    source_dir = make_source_tree(tmp_path)
    install_dir = tmp_path / "installed" / "skill-audit"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"hooks": {"UserPromptSubmit": {"matcher": "*"}}}),
        encoding="utf-8",
    )

    result = run_install(
        source_dir=source_dir,
        install_dir=install_dir,
        settings_path=settings_path,
        with_hooks=True,
    )

    assert result.changed is False
    assert result.conflicts == ["hooks.UserPromptSubmit"]
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"hooks": {"UserPromptSubmit": {"matcher": "*"}}}
