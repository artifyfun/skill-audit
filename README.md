# skill-audit

**A standalone Claude skill project for auditing your skill tree with both structure analysis and evidence-based usage analysis.**

This repository is designed to be both:

| Role | Meaning |
|---|---|
| installable skill unit | can be copied into a Claude skills directory |
| operator guide | explains exactly how to install, run, and interpret the current implementation |

It combines two strengths that are usually separated:

| Source strength | What it contributes here |
|---|---|
| [runesleo/claude-skill-audit](https://github.com/runesleo/claude-skill-audit) | skill health framing, usage ranking, dead-skill review mindset, telemetry-aware operation |
| [scottholdren/skill-audit](https://github.com/scottholdren/skill-audit) | overlap detection, collision diagnosis, inventory discipline, installable standalone skill shape |

The result is a **portable, versioned, installable** `skill-audit` project that helps you answer both questions at once:

| Question | Answered by |
|---|---|
| What skills do I have, where did they come from, and which ones overlap? | structure scan |
| Which skills show credible signs of real use, and how strong is that evidence? | usage scan |

---

## What is implemented today

This repository currently ships these runnable components:

| Path | Purpose | Implemented now |
|---|---|---|
| `SKILL.md` | installable skill definition and execution spec | yes |
| `README.md` | installation and runtime guide | yes |
| `scripts/install.py` | installer entrypoint | yes |
| `scripts/lib/install_manifest.py` | install manifest and required hook payload loader | yes |
| `scripts/lib/install_skill.py` | file copy and install target validation | yes |
| `scripts/lib/settings_merge.py` | settings merge, conflict detection, and backup logic | yes |

These are **target design ideas**, not shipped behavior in this repo:

| Artifact | Status |
|---|---|
| `quick` mode with changed-skill diffing | not implemented |
| persisted `inventory.json` / `evaluation.json` / `results.json` | not implemented |
| `quick-diff.sh` / `save-results.sh` | not implemented |
| automatic combined report generator | not implemented |

---

## Why this project exists

Most skill audits only solve half the problem.

| Common gap | Why it fails |
|---|---|
| Inventory-only audit | tells you what exists, not what is actually used |
| Usage-only audit | tells you what fired, not where descriptions conflict or duplicate |
| “Top skills” without telemetry | creates fake precision |
| In-place edits to installed skills | mixes experimentation with live environment state |

This repo is designed to avoid those failure modes.

| Design choice | Result |
|---|---|
| Standalone repository | evolve and review audit logic safely |
| Installable skill layout | copy into global or project-local Claude skills |
| Split audit model | structure debt and usage debt stay distinct |
| Explicit evidence tiers | no pretending weak hints are hard truth |
| Safe degradation | missing telemetry returns `insufficient_evidence` |

---

## Repository layout

```text
skill-audit/
├── SKILL.md
├── README.md
├── scripts/
│   ├── install.py
│   ├── scan_skills.py
│   ├── scan_usage.py
│   └── lib/
│       ├── install_manifest.py
│       ├── install_skill.py
│       └── settings_merge.py
├── examples/
│   └── hooks-settings.json
└── .gitignore
```

Install the whole directory, not just `SKILL.md`.

---

## Requirements

| Requirement | Needed for |
|---|---|
| `python3` | both scanners |
| POSIX-like shell | install commands, optional hook setup |
| optional `jq` | sample hook JSON commands |
| access to `~/.claude/skills/` | scanning global skills |
| optional project `.claude/skills/` directory | scanning project-local skills |

---

## Installation

### Install as a global skill

Global install is now the default. Running the installer with no target copies the full skill payload into your global Claude skills directory and merges the sample hooks into Claude settings:

```bash
python3 scripts/install.py
```

Preview the copy plan first if you want to confirm the destination:

```bash
python3 scripts/install.py --dry-run
```

If you want a global install without merging hooks:

```bash
python3 scripts/install.py --without-hooks
```

### Install as a project-local skill

Use the installer to copy the skill into the current project's local Claude skills directory:

```bash
python3 scripts/install.py --target project
```

Preview the local install first:

```bash
python3 scripts/install.py --target project --dry-run
```

If you want a project-local install without merging hooks:

```bash
python3 scripts/install.py --target project --without-hooks
```

### Optional hook control

Hook merge is now enabled by default. Use `--without-hooks` to skip merging the sample telemetry hooks.

Expected result:

```text
<target>/skill-audit/
├── SKILL.md
├── README.md
├── scripts/
└── examples/
```

Useful flags:

| Flag | Effect |
|---|---|
| `--dry-run` | preview file copies and settings changes without writing |
| `--with-hooks` | explicitly enable hook merge; this is now the default |
| `--without-hooks` | skip merging the sample telemetry hooks |
| `--settings <path>` | use a different settings file, useful for testing |
| `--backup` | accepted for compatibility; settings are backed up automatically only when a hook change is written |
| `--force` | allow install into a non-clean target and replace conflicting managed hook entries |

Hook merge rules:

| Behavior | Result |
|---|---|
| missing settings file | a new minimal settings object is planned or written only when `--with-hooks` is used |
| identical managed hooks already present | no duplicate hook entries are added |
| conflicting hook entry with same matcher but different commands | installer reports a conflict unless `--force` is passed |
| settings change is written | existing settings file is backed up first |

The installer writes JSON to stdout describing what it planned or changed.

### What a fresh AI should assume after install

| Safe assumption | Why |
|---|---|
| structure scan works with no telemetry | `scan_skills.py` uses on-disk inventory only |
| usage scan may return `insufficient_evidence` | usage depends on optional logs |
| no persisted cache exists unless you build it yourself | current scripts print JSON to stdout only |
| full audit requires synthesis of two outputs | no combined report script ships today |

---

## Runtime modes

| Mode | Command path | What to run |
|---|---|---|
| `mini` | structure-only inventory review | `python3 scripts/scan_skills.py` |
| `usage` | usage-only evidence review | `python3 scripts/scan_usage.py` |
| `full` | manual combination of both scans | run both commands and synthesize findings |

`quick` is intentionally omitted from runnable instructions because it is not implemented yet.

---

## How it works

### 1. Structure scan

Run:

```bash
python3 scripts/scan_skills.py
```

This scanner inspects these locations when present:

| Location | Meaning |
|---|---|
| `~/.claude/skills/` | global personal skills |
| `$REPO/.claude/skills/` | project-local skills under the installed repo |
| `~/.claude/plugins/cache/` | plugin-provided skills |

It emits JSON with these major sections:

| Section | Meaning |
|---|---|
| `summary` | totals by source and trigger type |
| `skills` | per-skill inventory |
| `duplicate_name_candidates` | repeated names |
| `duplicate_description_candidates` | repeated descriptions |
| `overlap_candidates` | token-overlap review candidates |

### 2. Usage scan

Run:

```bash
python3 scripts/scan_usage.py
```

It uses this evidence model:

| Level | Typical source | Safe use |
|---|---|---|
| `exact` | explicit `/skill-name` traces, execution log entries | ranking, trend tracking |
| `expanded` | named expansion trace or explicit derived record | supporting evidence |
| `inferred` | intentionally logged weak hint | manual review only |
| `none` | no evidence found | no action |

Current evidence inputs:

| Input | Used for | Optional |
|---|---|---|
| `~/.claude/skills/execution-log.jsonl` | strongest exact evidence | yes |
| `~/.claude/skills/skill-audit-usage.jsonl` | sample hook-generated evidence | yes |
| `~/.claude/memory/today.md` | supporting markers | yes |
| `~/.claude/memory/yesterday.md` | supporting markers | yes |

If both strong log sources are missing, the script returns:

```json
{ "status": "insufficient_evidence" }
```

That means observability is limited, not that your skills are unused.

### 3. Full audit workflow

A full audit in the current repo is an operator workflow, not a single command:

1. Run `python3 scripts/scan_skills.py`
2. Run `python3 scripts/scan_usage.py`
3. Review structure overlap, duplication, and trigger ambiguity
4. Review usage evidence and limitations
5. Synthesize action items manually or with a higher-level agent

Minimum report sections:

1. `Inventory`
2. `Structure findings`
3. `Usage findings`
4. `Confidence and limitations`
5. `Action items`

---

## Interpretation rules

### Structure findings

Treat these as **review candidates**, not automatic merge orders:

| Signal | Interpretation |
|---|---|
| duplicate name | naming collision risk |
| duplicate description | same-purpose risk |
| 3+ shared normalized description tokens | lightweight overlap candidate |
| `unknown` trigger type | likely documentation ambiguity |

### Usage findings

Treat these carefully:

| Signal | What it means | What it does not mean |
|---|---|---|
| `exact_count > 0` | direct invocation evidence exists | does not prove highest value |
| `expanded_count > 0` only | some strong supporting evidence exists | does not justify ranking by itself |
| `inferred_count > 0` only | weak hint exists | does not prove real use |
| no evidence | nothing observable was found | does not prove the skill is dead |

### Decision guidance

| Verdict | Use when | Reason must include |
|---|---|---|
| `Keep` | unique and still current | what is uniquely valuable |
| `Improve` | useful but poorly scoped or written | defect and concrete fix |
| `Update` | references may be stale | what needs revalidation |
| `Retire` | fully superseded or too weak to keep | replacement and impact |
| `Merge into X` | two skills no longer justify separation | merge target and integrated content |

---

## Telemetry setup

`examples/hooks-settings.json` provides a conservative example.

It shows two hook shapes:

| Hook | Purpose |
|---|---|
| `UserPromptSubmit` | log prompt text for explicit slash-use candidates |
| `PreToolUse:Bash` | log supporting Bash activity for later enrichment |

Important limits:
- the hook example demonstrates **log shape**, not ground truth
- generic Bash activity alone does not prove a skill was used
- telemetry is optional for structure-only audits
- missing logs should be reported as a limitation, never converted into fake certainty

---

## Validation

### Syntax checks

```bash
python3 -m py_compile scripts/scan_skills.py
python3 -m py_compile scripts/scan_usage.py
```

### Runtime checks

```bash
python3 scripts/scan_skills.py
python3 scripts/scan_usage.py
```

### Hook example check

```bash
jq -e . examples/hooks-settings.json
```

Expected interpretation:

| Check | Expected outcome |
|---|---|
| structure scan | JSON inventory summary |
| usage scan with missing logs | `status: "insufficient_evidence"` |
| hook JSON validation | exit 0 |

---

## Failure modes

| Symptom | Meaning | Safe interpretation |
|---|---|---|
| `execution-log.jsonl missing` | no primary exact telemetry source | strong ranking unavailable |
| `skill-audit-usage.jsonl missing` | sample hook log absent | custom telemetry not installed yet |
| `today/yesterday memory markers missing` | no auxiliary named trace source | supporting evidence limited |
| empty `top_exact` | no direct invocation evidence | do not publish heat ranking |
| many overlap candidates | token similarity is broad | review manually before merge or retire decisions |

---

## Future extensions

These are reasonable next steps, but they are not implemented in this repo today:

| Extension | Why it is useful |
|---|---|
| `quick` mode with changed-skill diffing | faster reruns after small edits |
| persisted `inventory.json` / `evaluation.json` / `results.json` | resumable multi-step audits |
| content-hash based change detection | safer than mtime-only reruns |
| explicit expansion-event logging | better `expanded` evidence quality |
| alias-aware matching | reduces undercounting for renamed skills |
| richer overlap heuristics | reduces false positives |
| markdown report renderer | easier handoff than raw JSON |

---

## Relationship to the upstream repos

This repository is an intentional integration of two open-source directions.

| Upstream repo | Borrowed direction | What changed here |
|---|---|---|
| [runesleo/claude-skill-audit](https://github.com/runesleo/claude-skill-audit) | health-check framing, usage ranking mindset, dead-skill review thinking | replaced single-source confidence with explicit evidence tiers and safe degradation |
| [scottholdren/skill-audit](https://github.com/scottholdren/skill-audit) | inventory discipline, overlap diagnosis, standalone installable skill layout | extended beyond structure analysis into telemetry-aware usage evidence |

---

## References

| Reference | Role |
|---|---|
| [runesleo/claude-skill-audit](https://github.com/runesleo/claude-skill-audit) | upstream source for usage-health framing and audit action model |
| [scottholdren/skill-audit](https://github.com/scottholdren/skill-audit) | upstream source for structure audit framing and overlap diagnosis |
