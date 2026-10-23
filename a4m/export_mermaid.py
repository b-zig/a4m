"""ArchiMate view -> Mermaid flowchart (one subgraph per layer, Archi layer colours).

Mermaid cannot draw true ArchiMate notation, so relationship *types* are conveyed with
line styles + verbs, and element types with a «Type» caption and shape per aspect.
"""

from __future__ import annotations

from .model import Model, View
from .rules import Rules, load_rules
from .state import STATE_COLORS, STATE_LABELS, display_state
from .views import view_members, view_relationships

# Mermaid node shape per ArchiMate aspect: (open, close)
SHAPES = {
    "active": ('["', '"]'),
    "behavior": ('("', '")'),
    "passive": ('[/"', '"/]'),
    "motivation": ('{{"', '"}}'),
    "composite": ('[["', '"]]'),
    "other": ('(("', '"))'),
}

# relationship type -> (arrow, verb)
ARROWS = {
    "Composition": ("-->", "composed of"),
    "Aggregation": ("-->", "aggregates"),
    "Assignment": ("-->", "assigned to"),
    "Realization": ("-.->", "realizes"),
    "Serving": ("-->", "serves"),
    "Access": ("-.->", "accesses"),
    "Influence": ("-.->", "influences"),
    "Triggering": ("==>", "triggers"),
    "Flow": ("-.->", "flows to"),
    "Specialization": ("-->", "specializes"),
    "Association": ("---", "associated with"),
}
ACCESS_VERBS = {"read": "reads", "write": "writes", "readwrite": "reads/writes", "access": "accesses"}


def mermaid_id(concept_id: str) -> str:
    return concept_id.replace("-", "_").replace("/", "__")


def escape(text: str) -> str:
    return text.replace('"', "#quot;").replace("<", "&lt;").replace(">", "&gt;")


def render_archimate(model: Model, view: View, rules: Rules | None = None, styled: bool = False) -> str:
    """styled: highlight new/changed/retiring elements and relationships (the "change" state)."""
    rules = rules or load_rules()
    members = view_members(model, view, rules)
    lines = ["flowchart TB"]
    by_layer: dict[str, list[str]] = {}
    for m in members:
        by_layer.setdefault(rules.layer_of(model.elements[m].type), []).append(m)

    for layer in rules.layer_order():
        ids = by_layer.get(layer)
        if not ids:
            continue
        lines.append(f'  subgraph layer_{layer}["{escape(rules.layers[layer]["label"])}"]')
        lines.append("    direction LR")
        for element_id in ids:
            el = model.elements[element_id]
            open_, close = SHAPES[rules.aspect_of(el.type)]
            caption = f"«{el.type}»" + (f" · {el.sa}" if el.foreign else "")
            state = display_state(model, el)
            if styled and state in STATE_COLORS:
                caption += f"<br/>{STATE_LABELS[state]}"
            lines.append(f"    {mermaid_id(el.id)}{open_}{escape(el.name)}<br/>{caption}{close}")
        lines.append("  end")

    link_styles = []
    for index, rel in enumerate(view_relationships(model, members)):
        state = display_state(model, rel)
        if styled and state in STATE_COLORS:
            dash = ",stroke-dasharray:6 4" if state in ("new", "retiring", "proposed") else ""
            link_styles.append(f"  linkStyle {index} stroke:{STATE_COLORS[state]},stroke-width:2px{dash}")
        arrow, verb = ARROWS[rel.type]
        if rel.type == "Access":
            verb = ACCESS_VERBS[rel.access or "write"]
        if rel.type == "Influence" and rel.modifier:
            verb = f"{verb} {rel.modifier}"
        if rel.type == "Association" and rel.directed:
            arrow = "-->"
        label = rel.name or verb
        lines.append(f'  {mermaid_id(rel.source)} {arrow}|"{escape(label)}"| {mermaid_id(rel.target)}')

    for layer in rules.layer_order():
        if layer in by_layer:
            color = rules.layers[layer]["color"]
            lines.append(f"  classDef {layer} fill:{color},stroke:#555,color:#000")
            lines.append(f"  class {','.join(mermaid_id(i) for i in by_layer[layer])} {layer}")
            lines.append(f"  style layer_{layer} fill:#fafafa,stroke:#bbb")
    foreign = [m for m in members if model.elements[m].foreign]
    if foreign:  # other SAs' elements: dashed grey border
        lines.append("  classDef foreign stroke:#777,stroke-dasharray:3 3")
        lines.append(f"  class {','.join(mermaid_id(i) for i in foreign)} foreign")
    if styled:
        for state, color in STATE_COLORS.items():
            ids = [m for m in members if display_state(model, model.elements[m]) == state]
            if ids:
                dash = ",stroke-dasharray:6 4" if state in ("new", "retiring", "proposed") else ""
                lines.append(f"  classDef st_{state} stroke:{color},stroke-width:3px{dash}")
                lines.append(f"  class {','.join(mermaid_id(i) for i in ids)} st_{state}")
    lines += link_styles
    return "\n".join(lines) + "\n"
