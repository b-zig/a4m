"""Resolve which elements and relationships appear on a view (ArchiMate or C4)."""

from __future__ import annotations

from .c4 import C4Projector
from .model import Model, Relationship, View
from .rules import Rules


def view_members(model: Model, view: View, rules: Rules) -> list[str]:
    """Element ids on the view, in a stable order."""
    if view.is_c4:
        return C4Projector(model, rules).project(view).archimate_members()
    members = [i for i in view.include if i in model.elements]
    layers = set(view.include_layers)
    # Layers bring in the SA's own elements plus other SAs' elements wired directly to them.
    neighbours = _foreign_neighbours(model)
    members += [
        e.id for e in model.elements.values()
        if rules.layer_of(e.type) in layers and e.id not in members and (not e.foreign or e.id in neighbours)
    ]
    return members


def _foreign_neighbours(model: Model) -> set[str]:
    found = set()
    for rel in model.relationships.values():
        ends = [model.elements.get(rel.source), model.elements.get(rel.target)]
        if all(ends) and ends[0].foreign != ends[1].foreign:
            found.add(ends[0].id if ends[0].foreign else ends[1].id)
    return found


def view_relationships(model: Model, members: list[str]) -> list[Relationship]:
    """Relationships drawn between elements that are both on the view."""
    present = set(members)
    return [r for r in model.relationships.values() if r.source in present and r.target in present]
