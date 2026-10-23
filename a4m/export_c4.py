"""C4 view -> Mermaid C4 diagram (C4Context / C4Container / C4Component / C4Deployment)."""

from __future__ import annotations

from .c4 import C4Diagram, C4Projector, element_description
from .export_mermaid import mermaid_id
from .model import Model, View
from .rules import Rules, load_rules
from .state import STATE_COLORS, STATE_LABELS, display_state

DIAGRAM_KEYWORD = {
    "c4-context": "C4Context",
    "c4-container": "C4Container",
    "c4-component": "C4Component",
    "c4-deployment": "C4Deployment",
}
SHAPE_SUFFIX = {"database": "Db", "queue": "Queue"}


def q(text: str) -> str:
    return '"' + str(text).replace('"', "'").replace("\n", " ") + '"'


def render_c4(model: Model, view: View, rules: Rules | None = None, styled: bool = False) -> str:
    """styled: highlight new/changed/retiring elements and arrows (the "change" state)."""
    rules = rules or load_rules()
    diagram = C4Projector(model, rules).project(view)
    styles: list[str] = []
    lines = [DIAGRAM_KEYWORD[view.kind], f"  title {view.name}"]
    if view.kind == "c4-deployment":
        lines += _deployment_body(model, diagram, rules, styles if styled else None)
    else:
        lines += _body(model, diagram, rules, styles if styled else None)
    for rel in diagram.rels:
        if view.kind == "c4-deployment":
            continue  # emitted per instance in _deployment_body
        args = [mermaid_id(rel.source), mermaid_id(rel.target), q(rel.label)] + ([q(rel.technology)] if rel.technology else [])
        lines.append(f"  Rel({', '.join(args)})")
        if styled:
            _rel_style(styles, mermaid_id(rel.source), mermaid_id(rel.target), rel.state)
    lines += styles
    lines.append('  UpdateLayoutConfig($c4ShapeInRow="4", $c4BoundaryInRow="2")')
    return "\n".join(lines) + "\n"


def _rel_style(styles: list[str], a: str, b: str, state: str) -> None:
    if state in STATE_COLORS:
        styles.append(f'  UpdateRelStyle({a}, {b}, $textColor="{STATE_COLORS[state]}", $lineColor="{STATE_COLORS[state]}")')


def _shape(model: Model, element_id: str, alias: str | None = None, indent: str = "  ", styles: list[str] | None = None) -> str:
    el = model.elements[element_id]
    tag = el.c4 or "system"
    macro = {"person": "Person", "system": "System", "container": "Container", "component": "Component"}[tag]
    if el.c4_shape and tag != "person":
        macro += SHAPE_SUFFIX[el.c4_shape]
    if el.external or (el.foreign and tag != "person"):  # other SAs' systems are drawn like external ones
        macro += "_Ext"
    alias = alias or mermaid_id(el.id)
    name = el.name
    state = display_state(model, el)
    if styles is not None and state in STATE_COLORS:
        name = f"{name} [{STATE_LABELS[state]}]"
        styles.append(f'  UpdateElementStyle({alias}, $borderColor="{STATE_COLORS[state]}", $fontColor="{STATE_COLORS[state]}")')
    args = [alias, q(name)]
    if tag in ("container", "component"):
        args.append(q(el.properties.get("technology", "")))
    args.append(q(element_description(el)))
    return f"{indent}{macro}({', '.join(args)})"


def _body(model: Model, diagram: C4Diagram, rules: Rules, styles: list[str] | None) -> list[str]:
    lines: list[str] = []
    inside = set(diagram.boundary[2]) if diagram.boundary else set()
    for element_id in diagram.elements:
        if element_id not in inside:
            lines.append(_shape(model, element_id, styles=styles))
    if diagram.boundary:
        macro, ref, members = diagram.boundary
        if ref.startswith("label:"):
            alias, label = "boundary_" + mermaid_id(model.sa), ref.removeprefix("label:")
        else:
            alias, label = "boundary_" + mermaid_id(ref), model.elements[ref].name
        lines.append(f"  {macro}({alias}, {q(label)}) {{")
        grouped = set()
        for sa, sa_name, ids in diagram.groups:
            lines.append(f"    Boundary(sa_{mermaid_id(sa)}, {q(sa_name)}) {{")
            lines += [_shape(model, m, indent="      ", styles=styles) for m in diagram.elements if m in ids]
            lines.append("    }")
            grouped.update(ids)
        lines += [_shape(model, m, indent="    ", styles=styles) for m in diagram.elements if m in inside and m not in grouped]
        lines.append("  }")
    return lines


def _deployment_body(model: Model, diagram: C4Diagram, rules: Rules, styles: list[str] | None) -> list[str]:
    hosts_of: dict[str, list[str]] = {}
    for node, units in diagram.hosted.items():
        for unit in units:
            hosts_of.setdefault(unit, []).append(node)

    def alias(unit: str, node: str) -> str:
        # A unit deployed on several nodes needs one Mermaid alias per instance.
        return mermaid_id(unit) if len(hosts_of[unit]) == 1 else f"{mermaid_id(unit)}__{mermaid_id(node)}"

    lines: list[str] = []

    def emit(node: str, depth: int) -> None:
        el = model.elements[node]
        pad = "  " * depth
        technology = el.properties.get("technology") or el.type
        name, state = el.name, display_state(model, el)
        if styles is not None and state in STATE_COLORS:
            name = f"{name} [{STATE_LABELS[state]}]"
            styles.append(f'  UpdateElementStyle({mermaid_id(node)}, $borderColor="{STATE_COLORS[state]}", $fontColor="{STATE_COLORS[state]}")')
        lines.append(f"{pad}Deployment_Node({mermaid_id(node)}, {q(name)}, {q(technology)}, {q(element_description(el))}) {{")
        for unit in diagram.hosted.get(node, []):
            lines.append(_shape(model, unit, alias=alias(unit, node), indent=pad + "  ", styles=styles))
        for child in diagram.children.get(node, []):
            emit(child, depth + 1)
        lines.append(f"{pad}}}")

    for root in diagram.roots:
        emit(root, 1)
    for rel in diagram.rels:
        for a in (alias(rel.source, n) for n in hosts_of.get(rel.source, [])):
            for b in (alias(rel.target, n) for n in hosts_of.get(rel.target, [])):
                args = [a, b, q(rel.label)] + ([q(rel.technology)] if rel.technology else [])
                lines.append(f"  Rel({', '.join(args)})")
                if styles is not None:
                    _rel_style(styles, a, b, rel.state)
    return lines
