"""Export a Model to the Open Group ArchiMate Model Exchange File Format (OEF 3.1), for Archi."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace

from .layout import Placed, layout_view
from .model import Model, View
from .rules import Rules, load_rules
from .state import STATE_COLORS, at_state, display_state, has_changes
from .views import view_members, view_relationships

NS = "http://www.opengroup.org/xsd/archimate/3.0/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
SCHEMA_LOCATION = f"{NS} http://www.opengroup.org/xsd/archimate/3.1/archimate3_Diagram.xsd"
ACCESS_TYPES = {"access": "Access", "read": "Read", "write": "Write", "readwrite": "ReadWrite"}
# a4m-only attributes travel to Archi as properties so they survive a round-trip.
C4_PROPERTIES = ("c4", "c4_shape", "external")
# Generated per-state copies of views that contain changes; import-oef skips them.
STATE_VIEW_SUFFIXES = {"baseline": ("--baseline", "current state"), "target": ("--target", "target state")}

ET.register_namespace("", NS)
ET.register_namespace("xsi", XSI)


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _text(parent: ET.Element, tag: str, value: str, lang: bool = True) -> None:
    if value:
        child = ET.SubElement(parent, _q(tag))
        if lang:
            child.set(XML_LANG, "en")
        child.text = value


def _hex_rgb(color: str) -> dict[str, str]:
    color = color.lstrip("#")
    return {"r": str(int(color[0:2], 16)), "g": str(int(color[2:4], 16)), "b": str(int(color[4:6], 16))}


def oef_id(ref: str) -> str:
    """OEF identifiers are xs:ID, which disallows '/': `edf/app-kafka` is written as `edf.app-kafka`."""
    return ref.replace("/", ".")


def concept_properties(concept, model: Model) -> dict:
    props = dict(concept.properties)
    for key in C4_PROPERTIES:
        value = getattr(concept, key, None)
        if value:
            props[f"a4m:{key}"] = "true" if value is True else value
    if concept.state != "existing":
        props["a4m:state"] = concept.state
    if concept.foreign or model.kind == "landscape":
        props["a4m:sa"] = concept.sa  # owned by that SA; import-oef leaves it alone
    return props


def export_oef(model: Model, rules: Rules | None = None) -> str:
    rules = rules or load_rules()
    prop_keys = sorted(
        {k for k in model.properties}
        | {k for e in model.elements.values() for k in concept_properties(e, model)}
        | {k for r in model.relationships.values() for k in concept_properties(r, model)}
    )
    prop_ids = {key: f"propid-{i + 1}" for i, key in enumerate(prop_keys)}

    def add_properties(parent: ET.Element, props: dict) -> None:
        if not props:
            return
        container = ET.SubElement(parent, _q("properties"))
        for key, value in props.items():
            prop = ET.SubElement(container, _q("property"), propertyDefinitionRef=prop_ids[key])
            _text(prop, "value", str(value).lower() if isinstance(value, bool) else str(value))

    root = ET.Element(_q("model"), {"identifier": f"model-{oef_id(model.sa)}", f"{{{XSI}}}schemaLocation": SCHEMA_LOCATION})
    _text(root, "name", model.name or model.sa)
    _text(root, "documentation", model.documentation)
    add_properties(root, model.properties)

    elements = ET.SubElement(root, _q("elements"))
    for el in model.elements.values():
        xsi_type = el.type
        if el.type == "Junction":
            xsi_type = "OrJunction" if el.junction_type == "or" else "AndJunction"
        node = ET.SubElement(elements, _q("element"), {"identifier": oef_id(el.id), f"{{{XSI}}}type": xsi_type})
        _text(node, "name", el.name)
        _text(node, "documentation", el.documentation)
        add_properties(node, concept_properties(el, model))

    if model.relationships:
        relationships = ET.SubElement(root, _q("relationships"))
        for rel in model.relationships.values():
            attrs = {"identifier": oef_id(rel.id), "source": oef_id(rel.source), "target": oef_id(rel.target), f"{{{XSI}}}type": rel.type}
            if rel.type == "Access":
                attrs["accessType"] = ACCESS_TYPES[rel.access or "write"]
            if rel.type == "Influence" and rel.modifier:
                attrs["modifier"] = rel.modifier
            if rel.type == "Association" and rel.directed:
                attrs["isDirected"] = "true"
            node = ET.SubElement(relationships, _q("relationship"), attrs)
            _text(node, "name", rel.name)
            _text(node, "documentation", rel.documentation)
            add_properties(node, concept_properties(rel, model))

    if prop_keys:
        definitions = ET.SubElement(root, _q("propertyDefinitions"))
        for key in prop_keys:
            definition = ET.SubElement(definitions, _q("propertyDefinition"), identifier=prop_ids[key], type="string")
            _text(definition, "name", key)

    if model.views:
        diagrams = ET.SubElement(ET.SubElement(root, _q("views")), _q("diagrams"))
        for view in model.views.values():
            state_model = at_state(model, view.state)
            members = view_members(state_model, view, rules)
            _add_view(diagrams, state_model, view, members, rules, styled=view.state == "change")
            if view.state == "change" and has_changes(model, members, view_relationships(model, members)):
                for state, (suffix, label) in STATE_VIEW_SUFFIXES.items():
                    copy = replace(view, id=view.id + suffix, name=f"{view.name} ({label})")
                    filtered = at_state(model, state)
                    _add_view(diagrams, filtered, copy, view_members(filtered, copy, rules), rules, styled=False)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _add_view(diagrams: ET.Element, model: Model, view: View, members: list[str], rules: Rules, styled: bool) -> None:
    view_id = oef_id(view.id)
    attrs = {"identifier": view_id, f"{{{XSI}}}type": "Diagram"}
    if view.viewpoint:
        attrs["viewpoint"] = view.viewpoint
    node = ET.SubElement(diagrams, _q("view"), attrs)
    _text(node, "name", view.name)
    _text(node, "documentation", view.documentation)
    node_ids: dict[str, str] = {}
    for placed in layout_view(model, view, members, rules):
        _add_node(node, view_id, placed, node_ids, rules, model if styled else None)
    for rel in view_relationships(model, members):
        connection = ET.SubElement(
            node,
            _q("connection"),
            {
                "identifier": f"c-{view_id}-{oef_id(rel.id)}",
                "relationshipRef": oef_id(rel.id),
                f"{{{XSI}}}type": "Relationship",
                "source": node_ids[rel.source],
                "target": node_ids[rel.target],
            },
        )
        state = display_state(model, rel)
        if styled and state in STATE_COLORS:
            style = ET.SubElement(connection, _q("style"), lineWidth="2")
            ET.SubElement(style, _q("lineColor"), _hex_rgb(STATE_COLORS[state]))


def _add_node(parent: ET.Element, view_id: str, placed: Placed, node_ids: dict[str, str], rules: Rules, styled: Model | None = None) -> None:
    geometry = {"x": str(placed.x), "y": str(placed.y), "w": str(placed.w), "h": str(placed.h)}
    if placed.kind == "group":
        node = ET.SubElement(parent, _q("node"), {"identifier": f"g-{view_id}-{placed.ref}", f"{{{XSI}}}type": "Container", **geometry})
        _text(node, "label", placed.label)
        style = ET.SubElement(node, _q("style"))
        ET.SubElement(style, _q("fillColor"), {**_hex_rgb(rules.layers[placed.ref]["color"]), "a": "35"})
        ET.SubElement(style, _q("lineColor"), {"r": "160", "g": "160", "b": "160"})
    else:
        node_id = f"n-{view_id}-{oef_id(placed.ref)}"
        node_ids[placed.ref] = node_id
        node = ET.SubElement(parent, _q("node"), {"identifier": node_id, "elementRef": oef_id(placed.ref), f"{{{XSI}}}type": "Element", **geometry})
        state = display_state(styled, styled.elements[placed.ref]) if styled else "existing"
        if state in STATE_COLORS:  # highlight the change with a coloured border
            style = ET.SubElement(node, _q("style"), lineWidth="3")
            ET.SubElement(style, _q("lineColor"), _hex_rgb(STATE_COLORS[state]))
    for child in placed.children:
        _add_node(node, view_id, child, node_ids, rules, styled)
