#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HOME = Path.home()
GLOBAL_SKILLS = HOME / ".claude/skills"
REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT_SKILLS = REPO_ROOT / ".claude/skills"
EXECUTION_LOG = GLOBAL_SKILLS / "execution-log.jsonl"
AUDIT_USAGE_LOG = HOME / ".claude/skills/skill-audit-usage.jsonl"
TODAY_MEMORY = HOME / ".claude/memory/today.md"
YESTERDAY_MEMORY = HOME / ".claude/memory/yesterday.md"
PROMPT_SKILL_RE = re.compile(r"/([a-z0-9][a-z0-9-]*)")


def collect_known_skills() -> set[str]:
    skill_roots = [GLOBAL_SKILLS, PROJECT_SKILLS]
    known_skills: set[str] = set()
    for root in skill_roots:
        if not root.exists():
            continue
        known_skills.update(path.parent.name for path in root.glob("*/SKILL.md"))
    return known_skills


def ensure_entry(store: dict[str, dict[str, Any]], skill: str) -> dict[str, Any]:
    if skill not in store:
        store[skill] = {
            "skill": skill,
            "exact_count": 0,
            "expanded_count": 0,
            "inferred_count": 0,
            "last_seen": None,
            "sources": set(),
            "confidence": "none",
        }
    return store[skill]


def bump_confidence(entry: dict[str, Any]) -> None:
    if entry["exact_count"] > 0:
        entry["confidence"] = "exact"
    elif entry["expanded_count"] > 0:
        entry["confidence"] = "expanded"
    elif entry["inferred_count"] > 0:
        entry["confidence"] = "inferred"
    else:
        entry["confidence"] = "none"


def read_execution_log(results: dict[str, dict[str, Any]], known_skills: set[str]) -> list[str]:
    limitations: list[str] = []
    if not EXECUTION_LOG.exists():
        limitations.append("execution-log.jsonl missing")
        return limitations

    for line in EXECUTION_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            limitations.append("execution-log.jsonl contains invalid JSON lines")
            continue
        skill = payload.get("skill")
        if not isinstance(skill, str) or skill not in known_skills:
            continue
        entry = ensure_entry(results, skill)
        entry["exact_count"] += 1
        entry["sources"].add("execution-log.jsonl")
        timestamp = payload.get("timestamp") or payload.get("time")
        if isinstance(timestamp, str):
            entry["last_seen"] = max(filter(None, [entry["last_seen"], timestamp]), default=timestamp)
        bump_confidence(entry)
    return limitations


def read_audit_usage_log(results: dict[str, dict[str, Any]], known_skills: set[str]) -> list[str]:
    limitations: list[str] = []
    if not AUDIT_USAGE_LOG.exists():
        limitations.append("skill-audit-usage.jsonl missing")
        return limitations

    for line in AUDIT_USAGE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            limitations.append("skill-audit-usage.jsonl contains invalid JSON lines")
            continue

        event = payload.get("event")
        if event == "prompt":
            prompt = str(payload.get("prompt") or "")
            for match in PROMPT_SKILL_RE.findall(prompt):
                if match not in known_skills:
                    continue
                entry = ensure_entry(results, match)
                entry["exact_count"] += 1
                entry["sources"].add("skill-audit-usage.jsonl")
                bump_confidence(entry)
        elif event == "expanded":
            skill = payload.get("skill")
            if isinstance(skill, str) and skill in known_skills:
                entry = ensure_entry(results, skill)
                entry["expanded_count"] += 1
                entry["sources"].add("skill-audit-usage.jsonl")
                bump_confidence(entry)
        elif event == "inferred":
            skill = payload.get("skill")
            if isinstance(skill, str) and skill in known_skills:
                entry = ensure_entry(results, skill)
                entry["inferred_count"] += 1
                entry["sources"].add("skill-audit-usage.jsonl")
                bump_confidence(entry)
    return limitations


def read_memory_markers(results: dict[str, dict[str, Any]], known_skills: set[str]) -> list[str]:
    limitations: list[str] = []
    found_any = False
    for path in [TODAY_MEMORY, YESTERDAY_MEMORY]:
        if not path.exists():
            continue
        found_any = True
        text = path.read_text(encoding="utf-8")
        for match in PROMPT_SKILL_RE.findall(text):
            if match not in known_skills:
                continue
            entry = ensure_entry(results, match)
            entry["expanded_count"] += 1
            entry["sources"].add(path.name)
            bump_confidence(entry)
    if not found_any:
        limitations.append("today/yesterday memory markers missing")
    return limitations


def main() -> None:
    known_skills = collect_known_skills()
    results: dict[str, dict[str, Any]] = {}
    limitations: list[str] = []
    limitations.extend(read_execution_log(results, known_skills))
    limitations.extend(read_audit_usage_log(results, known_skills))
    limitations.extend(read_memory_markers(results, known_skills))

    for entry in results.values():
        entry["sources"] = sorted(entry["sources"])

    top_exact = sorted(
        (entry for entry in results.values() if entry["exact_count"] > 0),
        key=lambda item: (-item["exact_count"], item["skill"]),
    )[:10]

    confidence_counts = Counter(entry["confidence"] for entry in results.values())
    status = "ok"
    if not EXECUTION_LOG.exists() and not AUDIT_USAGE_LOG.exists():
        status = "insufficient_evidence"

    payload = {
        "status": status,
        "summary": {
            "known_skills": len(known_skills),
            "skills_with_any_evidence": len(results),
            "confidence_counts": dict(confidence_counts),
        },
        "limitations": sorted(set(limitations)),
        "top_exact": [
            {
                "skill": entry["skill"],
                "exact_count": entry["exact_count"],
                "last_seen": entry["last_seen"],
            }
            for entry in top_exact
        ],
        "usage": sorted(results.values(), key=lambda item: item["skill"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
