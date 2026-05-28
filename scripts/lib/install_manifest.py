from __future__ import annotations

import json
from pathlib import Path

EXAMPLE_HOOKS_PATH = Path(__file__).resolve().parent.parent.parent / "examples" / "hooks-settings.json"
INSTALLABLE_PATHS = [
    ".gitignore",
    "SKILL.md",
    "README.md",
    "scripts",
    "examples",
]
INSTALLER_VERSION = 1

REQUIRED_HOOKS = json.loads(EXAMPLE_HOOKS_PATH.read_text(encoding="utf-8"))
REQUIRED_HOOK_KEYS = [
    "PreToolUse:Bash",
    "UserPromptSubmit:*",
]
