"""Test helpers: build throwaway model workspaces in temp dirs."""

from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from a4m.model import load_model
from a4m.paths import TOOL_ROOT
from a4m.validate import validate


class WorkspaceTestCase(unittest.TestCase):
    """Each test gets an empty workspace root with a models/ folder."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="a4m-test-"))
        (self.root / "models").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write_sa(self, sa: str, files: dict[str, str], name: str = "Test") -> Path:
        sa_dir = self.root / "models" / sa
        sa_dir.mkdir(parents=True, exist_ok=True)
        (sa_dir / "model.yaml").write_text(f"name: {name}\n", encoding="utf-8")
        for rel_path, text in files.items():
            path = sa_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text), encoding="utf-8")
        return sa_dir

    def copy_samples(self) -> None:
        """All sample SAs (they reference each other)."""
        shutil.rmtree(self.root / "models")
        shutil.copytree(TOOL_ROOT / "models", self.root / "models")

    def load(self, sa: str):
        return load_model(sa, self.root)

    def codes(self, sa: str, severity: str | None = None) -> list[str]:
        return [i.code for i in validate(self.load(sa)) if severity is None or i.severity == severity]


def load_sample(sa: str = "nextcloud"):
    """One SA of the sample workspace (models/), with its cross-SA references attached."""
    return load_model(sa, TOOL_ROOT)
