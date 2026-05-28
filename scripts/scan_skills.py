#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HOME = Path.home()
PLUGIN_CACHE = HOME / ".claude/plugins/cache"
GLOBAL_SKILLS = HOME / ".claude/skills"
REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_SKILLS = REPO_ROOT / ".claude/skills"

WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,}")
STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "when", "into", "your",
    "skill", "skills", "claude", "code", "uses", "used", "using", "user", "users",
    "project", "global", "local", "audit", "create", "write", "need", "guide",
}


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    block = text[4:end]
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("  ") and current_key:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip().strip('"').strip("'")
        result[current_key] = value
    return result


def infer_trigger_type(description: str, body: str) -> str:
    haystack = f"{description}\n{body}".lower()
    if any(token in haystack for token in ["/", "trigger:", "manual", "手动"]):
        if "/" in haystack:
            return "explicit"
    if any(token in haystack for token in ["auto", "自动", "sessionstart", "posttooluse", "pretooluse", "stop hook"]):
        return "auto-run"
    return "unknown"


def source_label(path: Path) -> tuple[str, str]:
    path_str = str(path)
    if "/.claude/plugins/cache/" in path_str:
        return "plugin-cache", "plugin"
    if path_str.startswith(str(PROJECT_SKILLS)):
        return "project", "project"
    if path_str.startswith(str(GLOBAL_SKILLS)):
        return "global", "personal"
    return "unknown", "unknown"


def tokenize(description: str) -> set[str]:
    return {
        token for token in WORD_RE.findall(description.lower())
        if token not in STOP_WORDS and len(token) > 2
    }


def collect_skill_files() -> list[Path]:
    paths: list[Path] = []
    if GLOBAL_SKILLS.exists():
        paths.extend(sorted(GLOBAL_SKILLS.glob("*/SKILL.md")))
    if PROJECT_SKILLS.exists():
        paths.extend(sorted(PROJECT_SKILLS.glob("*/SKILL.md")))
    if PLUGIN_CACHE.exists():
        paths.extend(sorted(PLUGIN_CACHE.glob("**/skills/*/SKILL.md")))
    return paths


def main() -> None:
    skills: list[dict[str, Any]] = []
    duplicate_names: defaultdict[str, list[str]] = defaultdict(list)
    duplicate_descriptions: defaultdict[str, list[str]] = defaultdict(list)
    token_buckets: defaultdict[str, list[str]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    trigger_counts: Counter[str] = Counter()

    for file_path in collect_skill_files():
        text = file_path.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        name = frontmatter.get("name") or file_path.parent.name
        description = (frontmatter.get("description") or "").strip()
        location, origin = source_label(file_path)
        trigger_type = infer_trigger_type(description, text)
        tokens = sorted(tokenize(description))

        skill = {
            "name": name,
            "path": str(file_path),
            "location": location,
            "origin": origin,
            "description": description,
            "trigger_type": trigger_type,
            "tokens": tokens,
        }
        skills.append(skill)
        source_counts[location] += 1
        trigger_counts[trigger_type] += 1
        duplicate_names[name].append(str(file_path))
        if description:
            duplicate_descriptions[description].append(name)
        for token in tokens:
            token_buckets[token].append(name)

    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(skills):
        left_tokens = set(left["tokens"])
        if not left_tokens:
            continue
        for right in skills[index + 1 :]:
            shared = sorted(left_tokens & set(right["tokens"]))
            if len(shared) < 3:
                continue
            overlaps.append(
                {
                    "left": {"name": left["name"], "path": left["path"], "location": left["location"]},
                    "right": {"name": right["name"], "path": right["path"], "location": right["location"]},
                    "shared_tokens": shared[:8],
                }
            )

    result = {
        "summary": {
            "total_skills": len(skills),
            "sources": dict(source_counts),
            "trigger_types": dict(trigger_counts),
        },
        "skills": skills,
        "duplicate_name_candidates": [
            {"name": name, "paths": paths}
            for name, paths in sorted(duplicate_names.items())
            if len(paths) > 1
        ],
        "duplicate_description_candidates": [
            {"description": description, "skills": sorted(names)}
            for description, names in sorted(duplicate_descriptions.items())
            if len(names) > 1
        ],
        "overlap_candidates": overlaps,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
