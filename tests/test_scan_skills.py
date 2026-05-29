from __future__ import annotations

import importlib.util
import json
import sys
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "scripts"
SCAN_SKILLS_PATH = SCRIPTS_DIR / "scan_skills.py"
SCAN_SKILLS_SPEC = importlib.util.spec_from_file_location("scan_skills", SCAN_SKILLS_PATH)
assert SCAN_SKILLS_SPEC is not None
assert SCAN_SKILLS_SPEC.loader is not None
scan_skills = importlib.util.module_from_spec(SCAN_SKILLS_SPEC)
sys.modules.setdefault("scan_skills", scan_skills)
SCAN_SKILLS_SPEC.loader.exec_module(scan_skills)


def write_skill(path: Path, *, name: str, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                "description: >",
                f"  {description}",
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
        scan_skills.main()
    finally:
        sys.stdout = original_stdout
    return json.loads(stdout.getvalue())


def test_parse_frontmatter_reads_folded_scalar_description() -> None:
    text = "\n".join(
        [
            "---",
            "name: sample",
            "description: >-",
            "  first line",
            "  second line",
            "---",
            "",
            "body",
        ]
    )

    frontmatter = scan_skills.parse_frontmatter(text)

    assert frontmatter["description"] == "first line second line"


def test_parse_frontmatter_preserves_folded_scalar_paragraph_breaks() -> None:
    text = "\n".join(
        [
            "---",
            "name: sample",
            "description: >",
            "  first line",
            "",
            "  second paragraph",
            "---",
            "",
            "body",
        ]
    )

    frontmatter = scan_skills.parse_frontmatter(text)

    assert frontmatter["description"] == "first line\n\nsecond paragraph"


def test_parse_frontmatter_preserves_literal_scalar_newlines() -> None:
    text = "\n".join(
        [
            "---",
            "name: sample",
            "description: |",
            "  first line",
            "  second line",
            "---",
            "",
            "body",
        ]
    )

    frontmatter = scan_skills.parse_frontmatter(text)

    assert frontmatter["description"] == "first line\nsecond line\n"


def test_parse_frontmatter_applies_literal_scalar_chomp_modifiers() -> None:
    stripped = "\n".join(
        [
            "---",
            "name: sample",
            "description: |-",
            "  first line",
            "  second line",
            "---",
            "",
            "body",
        ]
    )
    kept = "\n".join(
        [
            "---",
            "name: sample",
            "description: |+",
            "  first line",
            "  second line",
            "",
            "",
            "---",
            "",
            "body",
        ]
    )

    stripped_frontmatter = scan_skills.parse_frontmatter(stripped)
    kept_frontmatter = scan_skills.parse_frontmatter(kept)

    assert stripped_frontmatter["description"] == "first line\nsecond line"
    assert kept_frontmatter["description"] == "first line\nsecond line\n"


def test_collect_skill_files_deduplicates_plugin_cache_versions(tmp_path: Path, monkeypatch) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        plugin_cache / "vendor/plugin/1.9.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.10.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.1.0/skills/planning/SKILL.md",
        name="planning",
        description="Create implementation plans for engineering work.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    files = scan_skills.collect_skill_files()

    assert files == [
        plugin_cache / "vendor/plugin/1.10.0/skills/brainstorming/SKILL.md",
        plugin_cache / "vendor/plugin/1.1.0/skills/planning/SKILL.md",
    ]


def test_collect_skill_files_prefers_stable_plugin_version_over_prerelease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        plugin_cache / "vendor/plugin/1.0.0-beta/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.0.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    files = scan_skills.collect_skill_files()

    assert files == [
        plugin_cache / "vendor/plugin/1.0.0/skills/brainstorming/SKILL.md",
    ]


def test_collect_skill_files_handles_unparsed_version_segments_without_type_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        plugin_cache / "vendor/plugin/release-2024/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/release-2025/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    files = scan_skills.collect_skill_files()

    assert files == [
        plugin_cache / "vendor/plugin/release-2024/skills/brainstorming/SKILL.md",
        plugin_cache / "vendor/plugin/release-2025/skills/brainstorming/SKILL.md",
    ]


def test_collect_skill_files_preserves_unversioned_plugin_namespaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        plugin_cache / "vendor/plugin/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/skills/planning/SKILL.md",
        name="planning",
        description="Create implementation plans for engineering work.",
    )
    write_skill(
        plugin_cache / "vendor/stable/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Different plugin should keep its own namespace.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    files = scan_skills.collect_skill_files()

    assert files == [
        plugin_cache / "vendor/plugin/skills/brainstorming/SKILL.md",
        plugin_cache / "vendor/plugin/skills/planning/SKILL.md",
        plugin_cache / "vendor/stable/skills/brainstorming/SKILL.md",
    ]


def test_main_excludes_version_only_plugin_duplicates_from_duplicate_and_overlap_counts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        plugin_cache / "vendor/plugin/1.9.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.10.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.1.0/skills/planning/SKILL.md",
        name="planning",
        description="Create implementation plans for engineering work.",
    )
    write_skill(
        global_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    result = run_main()

    assert result["summary"] == {
        "total_skills": 3,
        "sources": {"global": 1, "plugin-cache": 2},
        "trigger_types": {"unknown": 3},
    }
    assert result["duplicate_name_candidates"] == []
    assert result["duplicate_description_candidates"] == []
    assert result["overlap_candidates"] == []


def test_main_collapses_identical_mirrored_installs_across_sources_for_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        global_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        project_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        plugin_cache / "vendor/plugin/1.0.0/skills/brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    result = run_main()

    assert result["summary"] == {
        "total_skills": 3,
        "sources": {"global": 1, "plugin-cache": 1, "project": 1},
        "trigger_types": {"unknown": 3},
    }
    assert result["duplicate_name_candidates"] == []
    assert result["duplicate_description_candidates"] == []
    assert result["overlap_candidates"] == []


def test_main_keeps_duplicate_name_candidates_for_same_name_different_descriptions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        global_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        project_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Generate varied ideas from loose prompts.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    result = run_main()

    assert result["duplicate_name_candidates"] == [
        {
            "name": "brainstorming",
            "paths": [
                str(global_skills / "brainstorming/SKILL.md"),
                str(project_skills / "brainstorming/SKILL.md"),
            ],
        }
    ]


def test_main_keeps_duplicate_description_candidates_for_distinct_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        global_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        project_skills / "planning/SKILL.md",
        name="planning",
        description="Turn ideas into designs with approval gates.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    result = run_main()

    assert result["duplicate_description_candidates"] == [
        {
            "description": "Turn ideas into designs with approval gates.",
            "skills": ["brainstorming", "planning"],
        }
    ]


def test_main_ignores_mirror_copies_when_calculating_overlap_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin_cache = tmp_path / ".claude/plugins/cache"
    global_skills = tmp_path / ".claude/skills"
    project_skills = tmp_path / "repo/.claude/skills"

    write_skill(
        global_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        project_skills / "brainstorming/SKILL.md",
        name="brainstorming",
        description="Turn ideas into designs with approval gates.",
    )
    write_skill(
        project_skills / "ideation/SKILL.md",
        name="ideation",
        description="Turn ideas into designs with approval gates for engineering teams.",
    )

    monkeypatch.setattr(scan_skills, "PLUGIN_CACHE", plugin_cache)
    monkeypatch.setattr(scan_skills, "GLOBAL_SKILLS", global_skills)
    monkeypatch.setattr(scan_skills, "PROJECT_SKILLS", project_skills)

    result = run_main()

    assert result["overlap_candidates"] == [
        {
            "left": {
                "name": "brainstorming",
                "path": str(global_skills / "brainstorming/SKILL.md"),
                "location": "global",
            },
            "right": {
                "name": "ideation",
                "path": str(project_skills / "ideation/SKILL.md"),
                "location": "project",
            },
            "shared_tokens": ["approval", "designs", "gates", "ideas", "turn"],
        }
    ]
