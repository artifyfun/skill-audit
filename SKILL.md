---
name: skill-audit
description: installable skill spec for auditing Claude skills by structure and usage evidence
---

# skill-audit

`skill-audit` is an installable skill specification for auditing a Claude skill tree with two distinct lenses:
- **structure**: what skills exist, where they came from, and where names or descriptions overlap
- **usage evidence**: which skills have credible signs of invocation, and how strong that evidence is

This repository is intentionally safe to install as a project-local or global skill because it documents current behavior honestly and does not require mutating live Claude settings automatically.

## Purpose

Use this skill when you need to answer one or more of these questions:

| Question | Answered by |
|---|---|
| What skills exist across global, project, and plugin surfaces? | structure scan |
| Which skills look duplicated, overlapping, or ambiguously triggered? | structure scan |
| Which skills have direct or supporting signs of use? | usage scan |
| Which skills deserve review, improvement, or archival consideration? | combined interpretation |

## Non-goals

This skill does **not**:

| Non-goal | Reason |
|---|---|
| Auto-delete or auto-archive skills | low evidence is not proof of no value |
| Modify `~/.claude/settings.json` automatically | configuration rollout is an operational choice |
| Claim usage rankings from weak hints alone | inferred evidence is intentionally weak |
| Promise persisted quick-resume workflows in this repo | the current implementation prints JSON to stdout and does not persist run state |

## Runtime modes

| Mode | Trigger | Current implementation |
|---|---|---|
| `mini` | lightweight inventory request | run `python3 scripts/scan_skills.py` and review structure output only |
| `usage` | usage-only request | run `python3 scripts/scan_usage.py` |
| `full` | combined audit request | run both scanners and synthesize one report manually |

`quick` is a valid **target design** for a future version, but it is **not implemented in this repository today**.

## Required deliverables

An installable copy of this skill should contain at least these files:

```text
skill-audit/
├── SKILL.md
├── README.md
├── scripts/
│   ├── scan_skills.py
│   └── scan_usage.py
└── examples/
    └── hooks-settings.json
```

## Repository-to-runtime mapping

| Path | Role | Implemented now |
|---|---|---|
| `SKILL.md` | skill definition and execution spec | yes |
| `README.md` | operator guide and installation instructions | yes |
| `scripts/scan_skills.py` | structure scanner | yes |
| `scripts/scan_usage.py` | usage evidence scanner | yes |
| `examples/hooks-settings.json` | sample telemetry hooks | yes |
| `results.json` | persisted combined results cache | no |
| `inventory.json` | persisted inventory snapshot | no |
| `evaluation.json` | persisted per-skill judgments | no |
| `quick-diff.sh` | changed-skill detector | no |
| `save-results.sh` | incremental results writer | no |

## Prerequisites

| Requirement | Why it matters |
|---|---|
| `python3` | required to run both scanners |
| shell environment | required for installation and optional hook setup |
| optional `jq` | needed by the sample hook JSON commands |
| access to `~/.claude/skills/` | required for scanning global skills |
| optional `$PWD/.claude/skills/` | scanned when using the repo inside a project |

## Execution flow

### Phase 1 — Structure scan

Run:

```bash
python3 scripts/scan_skills.py
```

This script currently scans these locations when they exist:

| Location | Meaning |
|---|---|
| `~/.claude/skills/` | global personal skills |
| `{repo}/.claude/skills/` | project-local skills relative to this repository |
| `~/.claude/plugins/cache/` | plugin-provided skills |

It emits JSON to stdout containing:

| Field | Meaning |
|---|---|
| `summary.total_skills` | total discovered skills |
| `summary.sources` | counts by source surface |
| `summary.trigger_types` | counts of `explicit`, `auto-run`, `unknown` |
| `skills[]` | per-skill inventory entries |
| `duplicate_name_candidates` | repeated names across paths |
| `duplicate_description_candidates` | repeated descriptions |
| `overlap_candidates` | lightweight token-overlap matches |

### Phase 2 — Usage evidence scan

Run:

```bash
python3 scripts/scan_usage.py
```

Evidence levels:

| Level | Meaning | Rankable |
|---|---|---|
| `exact` | direct slash invocation or execution-log evidence | yes |
| `expanded` | strong supporting trace naming the skill | supporting only |
| `inferred` | intentionally weak hint | no |
| `none` | no evidence found | no |

Current evidence inputs used by the script:

| Source | Purpose | Optional |
|---|---|---|
| `~/.claude/skills/execution-log.jsonl` | strongest exact evidence source | yes |
| `~/.claude/skills/skill-audit-usage.jsonl` | sample hook-generated evidence | yes |
| `~/.claude/memory/today.md` | supporting marker source | yes |
| `~/.claude/memory/yesterday.md` | supporting marker source | yes |

Rules:
- Never treat `ref=0` or `none` as proof a skill is dead.
- Never rank from `inferred` evidence.
- If strong sources are missing, report `insufficient_evidence` rather than inventing certainty.

### Phase 3 — Combined interpretation

For a full audit, combine both scanner outputs into one review with these minimum sections:

1. `Inventory`
2. `Structure findings`
3. `Usage findings`
4. `Confidence and limitations`
5. `Action items`

The current repo does **not** ship a combined report generator. A human or higher-level agent must synthesize the two JSON outputs.

## Evaluation rules

When turning scanner output into decisions, apply these criteria:

| Verdict | Use when | Minimum reason content |
|---|---|---|
| `Keep` | unique value is still current and evidence does not suggest consolidation | what is uniquely useful and why it remains current |
| `Improve` | worth keeping but wording, scope, or structure reduces usefulness | specific defect, impact, and concrete change |
| `Update` | references, APIs, commands, or technical claims look stale | what looks stale, what must be revalidated, and where |
| `Retire` | content is low-value or fully superseded by another artifact | defect found, replacement source, and removal impact |
| `Merge into X` | overlap is substantial enough that two skills should become one | target skill, what to merge, and why separation no longer helps |

### What counts as evidence

| Signal | Counts as |
|---|---|
| same or near-identical skill name | duplicate-name evidence |
| same or near-identical description | duplicate-description evidence |
| 3+ meaningful shared normalized description tokens | overlap candidate evidence |
| explicit slash use or execution log entry | exact usage evidence |
| hook trace naming a skill | exact or expanded evidence depending on event |
| generic Bash activity without named skill | not enough to prove usage |

### Staleness checks

A skill should be considered for `Update` when it contains any of these and they are no longer verified:
- CLI flags
- tool names
- SDK or API examples
- version-specific setup steps
- file paths or settings claims that may have changed

Use WebSearch only when freshness cannot be verified from the local environment or current docs.

## Telemetry guidance

The sample hook file at `examples/hooks-settings.json` is a conservative example of how to capture supporting usage evidence. It demonstrates log shape, not ground truth.

Interpretation rules:
- missing logs mean **absence of evidence**, not **evidence of absence**
- supporting telemetry can strengthen a judgment, but weak telemetry must not dominate ranking
- hook installation is optional for structure-only audits

## Runtime state model

### Current implementation

Today, both scanners emit JSON to stdout only. This repo does **not** currently persist run state or batch progress.

### Target design for a future version

If persisted state is added later, separate it by responsibility:

| File | Responsibility |
|---|---|
| `inventory.json` | discovered skill snapshot and content/hash metadata |
| `evaluation.json` | per-skill judgments and rationale |
| `results.json` | published combined report for a given run |

If that future design is implemented, use content hashes or equivalent stable change detection rather than relying on mtime alone.

## Installation constraints

- Do not claim `quick` or resume behavior unless the helper scripts actually exist.
- Do not document cache semantics as shipped behavior unless state files are actually written.
- Do not tell users to install only `SKILL.md`; the scripts and example hook file are part of the installable unit.
- Prefer repository installation or update flows that keep the full directory intact.
- If secrets are found while inspecting settings or logs, stop short of rollout changes and report the exposure.

## Validation checklist

Before claiming this skill is installable and runnable:

- [ ] `python3 scripts/scan_skills.py` is documented exactly as implemented
- [ ] `python3 scripts/scan_usage.py` is documented exactly as implemented
- [ ] all referenced repo files exist
- [ ] unimplemented helpers are labeled future work, not current capability
- [ ] telemetry limitations are described honestly
