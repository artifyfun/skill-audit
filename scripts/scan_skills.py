#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VERSION_SEGMENT_RE = re.compile(r"^v?[a-z0-9.+_-]+$", re.IGNORECASE)
VERSION_PARSE_RE = re.compile(
    r"^v?(?P<core>\d+(?:[._-]\d+)*)(?:(?P<sep>[._-])(?P<suffix>[a-z][a-z0-9._-]*))?$",
    re.IGNORECASE,
)
VERSION_PART_RE = re.compile(r"\d+|[a-z]+", re.IGNORECASE)
BLOCK_SCALAR_RE = re.compile(r"^(?P<style>[>|])(?P<modifiers>[+-]?\d*|\d*[+-]?)$")

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
    multiline_key: str | None = None
    multiline_mode: str | None = None
    multiline_lines: list[str] = []
    multiline_indent: int | None = None
    multiline_chomp: str = "clip"

    def flush_multiline() -> None:
        nonlocal multiline_key, multiline_mode, multiline_lines, multiline_indent, multiline_chomp
        if multiline_key is None or multiline_mode is None:
            return
        result[multiline_key] = format_block_scalar(
            multiline_mode,
            choose_block_lines(multiline_lines, multiline_chomp),
        )
        multiline_key = None
        multiline_mode = None
        multiline_lines = []
        multiline_indent = None
        multiline_chomp = "clip"

    for raw_line in block.splitlines():
        line = raw_line.rstrip("\r")
        if multiline_key:
            block_line = extract_block_line(line, multiline_indent)
            if block_line is not None:
                multiline_indent, content = block_line
                multiline_lines.append(content)
                continue
        flush_multiline()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"').strip("'")
        block_scalar = parse_block_scalar_spec(value)
        if block_scalar is not None:
            multiline_key = key.strip()
            multiline_mode, multiline_chomp = block_scalar
            multiline_lines = []
            multiline_indent = None
            continue
        result[key.strip()] = value

    flush_multiline()
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


def mirror_identity(skill: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    return (
        str(skill["name"]),
        str(skill["description"]),
        tuple(skill["tokens"]),
    )


def collapse_mirrored_skills(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collapsed: dict[tuple[str, str, tuple[str, ...], str], dict[str, Any]] = {}
    for skill in skills:
        identity = mirror_identity(skill)
        current = collapsed.get(identity)
        if current is None or (str(skill["location"]), str(skill["path"])) < (
            str(current["location"]),
            str(current["path"]),
        ):
            collapsed[identity] = skill
    return list(collapsed.values())


def tokenize(description: str) -> set[str]:
    return {
        token for token in WORD_RE.findall(description.lower())
        if token not in STOP_WORDS and len(token) > 2
    }


def plugin_skill_identity(path: Path) -> str:
    relative_parts = path.relative_to(PLUGIN_CACHE).parts
    skills_index = relative_parts.index("skills")
    plugin_parts = relative_parts[:skills_index]
    if plugin_parts and VERSION_PARSE_RE.match(plugin_parts[-1]):
        plugin_parts = plugin_parts[:-1]
    skill_name = relative_parts[skills_index + 1]
    return "/".join((*plugin_parts, skill_name))


def version_token_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in VERSION_PART_RE.findall(value)
    )


def plugin_skill_version_key(
    path: Path,
) -> tuple[int, tuple[tuple[int, int | str], ...], int, tuple[tuple[int, int | str], ...], str]:
    relative_parts = path.relative_to(PLUGIN_CACHE).parts
    skills_index = relative_parts.index("skills")
    plugin_parts = relative_parts[:skills_index]
    if not plugin_parts:
        return (0, (), 0, (), "")
    version = plugin_parts[-1]
    match = VERSION_PARSE_RE.match(version)
    if match is None:
        return (0, version_token_key(version), 0, (), version.lower())

    core = tuple((0, int(segment)) for segment in re.split(r"[._-]", match.group("core")))
    suffix = match.group("suffix")
    if suffix is None:
        return (1, core, 1, (), version.lower())

    return (1, core, 0, version_token_key(suffix), version.lower())


def parse_block_scalar_value(style: str, modifiers: str) -> tuple[str, str]:
    mode = "folded" if style == ">" else "literal"
    chomp = "keep" if "+" in modifiers else "strip" if "-" in modifiers else "clip"
    return mode, chomp


def normalize_plugin_paths(paths: list[Path]) -> list[Path]:
    latest_by_identity: dict[str, Path] = {}
    for path in paths:
        identity = plugin_skill_identity(path)
        current = latest_by_identity.get(identity)
        if current is None or plugin_skill_version_key(path) > plugin_skill_version_key(current):
            latest_by_identity[identity] = path
    return [path for _, path in sorted(latest_by_identity.items())]




def choose_block_lines(lines: list[str], chomp: str) -> list[str]:
    if chomp == "keep":
        return lines[:]
    normalized = lines[:]
    while normalized and normalized[-1] == "":
        normalized.pop()
    if chomp == "clip":
        normalized.append("")
    return normalized


def format_block_scalar(mode: str, lines: list[str]) -> str:
    if mode == "literal":
        return "\n".join(lines)

    paragraphs: list[str] = []
    current_paragraph: list[str] = []
    for multiline_line in lines:
        stripped_line = multiline_line.strip()
        if stripped_line:
            current_paragraph.append(stripped_line)
            continue
        if current_paragraph:
            paragraphs.append(" ".join(current_paragraph))
            current_paragraph = []
    if current_paragraph:
        paragraphs.append(" ".join(current_paragraph))
    return "\n\n".join(paragraphs)


def extract_block_line(line: str, multiline_indent: int | None) -> tuple[int | None, str] | None:
    if not line:
        return multiline_indent, ""
    leading_spaces = len(line) - len(line.lstrip(" "))
    if multiline_indent is None:
        if leading_spaces == 0:
            return None
        multiline_indent = leading_spaces
    if leading_spaces < multiline_indent:
        return None
    return multiline_indent, line[multiline_indent:]


def parse_block_scalar_spec(value: str) -> tuple[str, str] | None:
    block_scalar = BLOCK_SCALAR_RE.match(value)
    if block_scalar is None:
        return None
    return parse_block_scalar_value(block_scalar.group("style"), block_scalar.group("modifiers"))


def collect_skill_files() -> list[Path]:
    paths: list[Path] = []
    if GLOBAL_SKILLS.exists():
        paths.extend(sorted(GLOBAL_SKILLS.glob("*/SKILL.md")))
    if PROJECT_SKILLS.exists():
        paths.extend(sorted(PROJECT_SKILLS.glob("*/SKILL.md")))
    if PLUGIN_CACHE.exists():
        plugin_files = sorted(PLUGIN_CACHE.glob("**/skills/*/SKILL.md"))
        paths.extend(normalize_plugin_paths(plugin_files))
    return paths


def main() -> None:
    skills: list[dict[str, Any]] = []
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

    candidate_skills = collapse_mirrored_skills(skills)
    duplicate_names: defaultdict[str, list[str]] = defaultdict(list)
    duplicate_descriptions: defaultdict[str, list[str]] = defaultdict(list)
    for skill in candidate_skills:
        duplicate_names[str(skill["name"])].append(str(skill["path"]))
        description = str(skill["description"])
        if description:
            duplicate_descriptions[description].append(str(skill["name"]))

    overlaps: list[dict[str, Any]] = []
    for index, left in enumerate(candidate_skills):
        left_tokens = set(left["tokens"])
        if not left_tokens:
            continue
        for right in candidate_skills[index + 1 :]:
            if left["name"] == right["name"] or left["description"] == right["description"]:
                continue
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
