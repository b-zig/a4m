"""Change state: every element and relationship is existing, new, changed or retiring.

A solution architecture (SA) describes its current state (baseline) and its target state in
one model. Views render the change (everything, new/retiring highlighted) or one of the two
states. In the enterprise landscape, an SA's changes count towards the target only once the
SA is approved.
"""

from __future__ import annotations

from dataclasses import replace

STATES = ["existing", "new", "changed", "retiring"]
VIEW_STATES = ["change", "baseline", "target"]
SA_KINDS = ["solution", "platform", "enterprise"]
SA_STATUSES = ["draft", "proposed", "approved", "implemented", "rejected"]
APPROVED = {"approved", "implemented"}

# Colours for highlighted states (borders/lines). "proposed" = new in an SA that is not approved yet.
STATE_COLORS = {"new": "#2e7d32", "changed": "#ef6c00", "retiring": "#c62828", "proposed": "#6a1b9a"}
STATE_LABELS = {"new": "NEW", "changed": "CHANGED", "retiring": "RETIRING", "proposed": "PROPOSED"}
LEGEND = (
    "Change highlighting: green = new, orange = changed, red = retiring"
    " (purple = proposed by an SA that is not approved yet)."
)


def in_baseline(state: str) -> bool:
    return state != "new"


def in_target(state: str) -> bool:
    return state != "retiring"


def display_state(model, concept) -> str:
    """State to highlight. In the landscape, new items of unapproved SAs show as 'proposed'."""
    if concept.state == "new" and model.kind == "landscape" and model.sa_status.get(concept.sa) not in APPROVED:
        return "proposed"
    return concept.state


def _keep(model, concept, view_state: str) -> bool:
    if view_state == "baseline":
        return in_baseline(concept.state)
    if view_state == "target":
        if model.kind == "landscape" and model.sa_status.get(concept.sa) not in APPROVED:
            return in_baseline(concept.state)  # unapproved change: the target keeps today's state
        return in_target(concept.state)
    return True


def at_state(model, view_state: str):
    """The model as it is in the baseline or target state ("change" returns it unchanged)."""
    if view_state == "change":
        return model
    elements = {k: e for k, e in model.elements.items() if _keep(model, e, view_state)}
    relationships = {
        k: r
        for k, r in model.relationships.items()
        if _keep(model, r, view_state) and r.source in elements and r.target in elements
    }
    return replace(model, elements=elements, relationships=relationships)


def has_changes(model, element_ids, relationships=()) -> bool:
    return any(model.elements[i].state != "existing" for i in element_ids if i in model.elements) or any(
        r.state != "existing" for r in relationships
    )
