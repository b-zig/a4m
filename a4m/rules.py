"""Rule base: ArchiMate element catalogue, relationship matrix (from Archi) and C4 mapping."""

from __future__ import annotations

import difflib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .paths import RULES_DIR

ARCHIMATE_VERSION = "3.2"

# Canonical relationship type names, in ArchiMate spec order.
RELATIONSHIP_TYPES = [
    "Composition",
    "Aggregation",
    "Assignment",
    "Realization",
    "Serving",
    "Access",
    "Influence",
    "Triggering",
    "Flow",
    "Specialization",
    "Association",
]


@dataclass(frozen=True)
class ElementType:
    name: str
    layer: str
    aspect: str
    icon: str = ""
    shape: str = ""


class Rules:
    """Everything a4m knows about ArchiMate and C4, loaded from the rules/ directory."""

    def __init__(self, rules_dir: Path = RULES_DIR, archimate_version: str = ARCHIMATE_VERSION):
        self.rules_dir = rules_dir
        catalogue = yaml.safe_load((rules_dir / "elements.yaml").read_text(encoding="utf-8"))
        self.layers: dict[str, dict] = catalogue["layers"]
        self.types: dict[str, ElementType] = {
            name: ElementType(name, spec["layer"], spec["aspect"], spec.get("icon", ""), spec.get("shape", ""))
            for name, spec in catalogue["types"].items()
        }
        self.aspects: dict[str, dict] = catalogue["aspects"]
        self.viewpoints: list[str] = catalogue["viewpoints"]
        self.c4: dict = yaml.safe_load((rules_dir / "c4.yaml").read_text(encoding="utf-8"))
        self.matrix = _load_matrix(rules_dir / f"archimate-{archimate_version}")

    # --- element types -------------------------------------------------------------------

    def layer_of(self, type_name: str) -> str:
        t = self.types.get(type_name)
        return t.layer if t else "other"

    def aspect_of(self, type_name: str) -> str:
        t = self.types.get(type_name)
        return t.aspect if t else "other"

    def notation_of(self, type_name: str) -> tuple[str, str]:
        """(Mermaid shape, glyph) standing in for the ArchiMate notation of a type."""
        t = self.types.get(type_name)
        aspect = t.aspect if t else "other"
        return (t and t.shape) or self.aspects[aspect]["shape"], t.icon if t else ""

    def layer_order(self) -> list[str]:
        return sorted(self.layers, key=lambda layer: self.layers[layer]["order"])

    def types_in_layer(self, layer: str) -> list[str]:
        return [t.name for t in self.types.values() if t.layer == layer]

    def suggest_type(self, name: str) -> list[str]:
        candidates = list(self.types)
        lowered = {c.lower(): c for c in candidates}
        if name.lower() in lowered:
            return [lowered[name.lower()]]
        return difflib.get_close_matches(name, candidates, n=3, cutoff=0.5)

    def suggest_relationship(self, name: str) -> list[str]:
        lowered = {c.lower(): c for c in RELATIONSHIP_TYPES}
        if name.lower() in lowered:
            return [lowered[name.lower()]]
        return difflib.get_close_matches(name, RELATIONSHIP_TYPES, n=3, cutoff=0.5)

    # --- relationships -------------------------------------------------------------------

    def allowed(self, source_type: str, target_type: str) -> list[str]:
        """Relationship types ArchiMate allows from source_type to target_type (spec order)."""
        found = self.matrix.get((source_type, target_type), set())
        return [r for r in RELATIONSHIP_TYPES if r in found]

    def is_allowed(self, source_type: str, relationship: str, target_type: str) -> bool:
        return relationship in self.matrix.get((source_type, target_type), set())


def _load_matrix(directory: Path) -> dict[tuple[str, str], set[str]]:
    keys_root = ET.parse(directory / "relationships-keys.xml").getroot()
    letters = {
        key.get("char"): key.get("relationship").removesuffix("Relationship") for key in keys_root.iter("key")
    }
    matrix: dict[tuple[str, str], set[str]] = {}
    for source in ET.parse(directory / "relationships.xml").getroot().iter("source"):
        for target in source.iter("target"):
            relations = target.get("relations") or ""
            # Archi plans to mark direct (vs derived) relationships with upper case; treat both alike.
            matrix[(source.get("concept"), target.get("concept"))] = {
                letters[c.lower()] for c in relations if c.lower() in letters
            }
    return matrix


@lru_cache(maxsize=None)
def load_rules() -> Rules:
    return Rules()
