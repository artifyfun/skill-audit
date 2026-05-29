from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
SCAN_USAGE_PATH = SCRIPTS_DIR / "scan_usage.py"
SCAN_USAGE_SPEC = importlib.util.spec_from_file_location("scan_usage", SCAN_USAGE_PATH)
assert SCAN_USAGE_SPEC is not None
assert SCAN_USAGE_SPEC.loader is not None
scan_usage = importlib.util.module_from_spec(SCAN_USAGE_SPEC)
sys.modules.setdefault("scan_usage", scan_usage)
SCAN_USAGE_SPEC.loader.exec_module(scan_usage)


def write_skill(path: Path, *, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                "description: >",
                f"  Audit helper for {name}.",
                "---",
                "",
                f"# {name}",
            ]
        ),
        encoding="utf-8",
    )


def run_main() -> dict[str, object]:
    stdout = StringIO()
    original_stdout = sys.stdout
    sys.stdout = stdout
    try:
        scan_usage.main()
    finally:
        sys.stdout = original_stdout
    return json.loads(stdout.getvalue())


def configure_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"
    write_skill(global_skills / "brainstorming/SKILL.md", name="brainstorming")
    monkeypatch.setattr(scan_usage, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_usage, "PROJECT_SKILLS", project_skills)
    monkeypatch.setattr(scan_usage, "EXECUTION_LOG", global_skills / "execution-log.jsonl")
    monkeypatch.setattr(scan_usage, "AUDIT_USAGE_LOG", global_skills / "skill-audit-usage.jsonl")
    monkeypatch.setattr(scan_usage, "TODAY_MEMORY", tmp_path / ".claude/memory/today.md")
    monkeypatch.setattr(scan_usage, "YESTERDAY_MEMORY", tmp_path / ".claude/memory/yesterday.md")
    return global_skills, project_skills


def test_main_reports_insufficient_evidence_when_both_strong_sources_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_paths(monkeypatch, tmp_path)

    result = run_main()

    assert result["status"] == "insufficient_evidence"
    assert result["evidence_state"] == {
        "strong_sources_present": [],
        "strong_sources_missing": ["execution-log.jsonl", "skill-audit-usage.jsonl"],
        "ranking_safe": False,
        "note": "Strong telemetry is missing; rankings are not safe to interpret.",
    }
    assert result["limitations"] == [
        "execution-log.jsonl missing",
        "skill-audit-usage.jsonl missing",
        "today/yesterday memory markers missing",
    ]


def test_main_reports_partial_strong_evidence_without_changing_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_skills, _ = configure_paths(monkeypatch, tmp_path)
    (global_skills / "execution-log.jsonl").write_text(
        json.dumps({"skill": "brainstorming", "timestamp": "2026-05-28T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    result = run_main()

    assert result["status"] == "ok"
    assert result["evidence_state"] == {
        "strong_sources_present": ["execution-log.jsonl"],
        "strong_sources_missing": ["skill-audit-usage.jsonl"],
        "ranking_safe": False,
        "note": "Only part of the strong telemetry is present; rankings should be treated cautiously.",
    }
    assert result["top_exact"] == [
        {
            "skill": "brainstorming",
            "exact_count": 1,
            "last_seen": "2026-05-28T10:00:00Z",
        }
    ]
    assert result["limitations"] == [
        "skill-audit-usage.jsonl missing",
        "today/yesterday memory markers missing",
    ]


def test_main_marks_rankings_safe_only_when_both_strong_sources_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    global_skills, _ = configure_paths(monkeypatch, tmp_path)
    (global_skills / "execution-log.jsonl").write_text(
        json.dumps({"skill": "brainstorming", "timestamp": "2026-05-28T10:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    (global_skills / "skill-audit-usage.jsonl").write_text(
        json.dumps({"event": "prompt", "prompt": "/brainstorming"}) + "\n",
        encoding="utf-8",
    )

    result = run_main()

    assert result["status"] == "ok"
    assert result["evidence_state"] == {
        "strong_sources_present": ["execution-log.jsonl", "skill-audit-usage.jsonl"],
        "strong_sources_missing": [],
        "ranking_safe": True,
        "note": "Both strong telemetry sources are present; exact rankings have a solid basis.",
    }


def test_main_does_not_treat_memory_markers_as_strong_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configure_paths(monkeypatch, tmp_path)
    today_memory = tmp_path / ".claude/memory/today.md"
    today_memory.parent.mkdir(parents=True, exist_ok=True)
    today_memory.write_text("Used /brainstorming today.\n", encoding="utf-8")

    result = run_main()

    assert result["status"] == "insufficient_evidence"
    assert result["evidence_state"] == {
        "strong_sources_present": [],
        "strong_sources_missing": ["execution-log.jsonl", "skill-audit-usage.jsonl"],
        "ranking_safe": False,
        "note": "Strong telemetry is missing; rankings are not safe to interpret.",
    }
    assert result["usage"] == [
        {
            "skill": "brainstorming",
            "exact_count": 0,
            "expanded_count": 1,
            "inferred_count": 0,
            "last_seen": None,
            "sources": ["today.md"],
            "confidence": "expanded",
        }
    ]
