"""Filesystem locations. The tool runs from a checkout of this repo; A4M_ROOT overrides the workspace."""

from __future__ import annotations

import os
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = TOOL_ROOT / "rules"
SCHEMA_PATH = TOOL_ROOT / "schema" / "a4m.schema.json"


def workspace_root() -> Path:
    """Directory holding models/, docs/ and build/ (defaults to the repo itself)."""
    return Path(os.environ.get("A4M_ROOT", TOOL_ROOT)).resolve()
