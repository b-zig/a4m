"""JSON Schema for model YAML files, generated from the rule catalogue.

The committed copy lives at schema/a4m.schema.json (editor validation, LLM structured output);
`a4m schema --write` regenerates it and a test keeps it in sync.
"""

from __future__ import annotations

import json

from .paths import SCHEMA_PATH
from .rules import RELATIONSHIP_TYPES, Rules, load_rules
from .state import SA_KINDS, SA_STATUSES, STATES, VIEW_STATES

ID_PATTERN = "^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
_ID = ID_PATTERN[1:-1]
# A reference: a local id, or `<sa>/<id>` for an element owned by another solution architecture.
REF_PATTERN = f"^({_ID}/)?{_ID}$"
VIEW_KINDS = ["archimate", "c4-context", "c4-container", "c4-component", "c4-deployment"]
ACCESS_MODES = ["access", "read", "write", "readwrite"]


def build_schema(rules: Rules | None = None) -> dict:
    rules = rules or load_rules()
    scalar = {"type": ["string", "number", "boolean"]}
    properties = {"type": "object", "additionalProperties": scalar, "description": "Free-form key/value properties (exported to Archi)."}
    ref = {"type": "string", "pattern": REF_PATTERN, "description": "Element id, or <sa>/<id> for an element exported by another SA."}
    state = {"enum": STATES, "default": "existing", "description": "Change state: existing (default), new, changed or retiring."}
    element = {
        "type": "object",
        "required": ["id", "type", "name"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": ID_PATTERN, "description": "Stable kebab-case id; prefix by layer, e.g. app-nextcloud."},
            "type": {"enum": sorted(rules.types), "description": "ArchiMate 3.2 element type."},
            "name": {"type": "string", "minLength": 1},
            "documentation": {"type": "string"},
            "properties": properties,
            "c4": {"enum": sorted(rules.c4["tags"]), "description": "Opt this element into C4 views."},
            "c4_shape": {"enum": rules.c4["shapes"]},
            "external": {"type": "boolean", "description": "C4: render as *_Ext (outside the enterprise boundary)."},
            "junction_type": {"enum": ["and", "or"], "description": "Only for type Junction."},
            "state": state,
        },
    }
    relationship = {
        "type": "object",
        "required": ["type", "source", "target"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": ID_PATTERN, "description": "Optional; defaults to rel-<source>-<type>-<target>."},
            "type": {"enum": RELATIONSHIP_TYPES},
            "source": ref,
            "target": ref,
            "name": {"type": "string"},
            "documentation": {"type": "string"},
            "properties": properties,
            "access": {"enum": ACCESS_MODES, "description": "Only for Access (default write, as in ArchiMate)."},
            "modifier": {"type": "string", "description": "Only for Influence, e.g. '+', '++', '-'."},
            "directed": {"type": "boolean", "description": "Only for Association."},
            "state": state,
        },
    }
    bounds = {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}
    view = {
        "type": "object",
        "required": ["id", "name"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "string", "pattern": ID_PATTERN},
            "name": {"type": "string", "minLength": 1},
            "kind": {"enum": VIEW_KINDS, "default": "archimate"},
            "documentation": {"type": "string"},
            "viewpoint": {"enum": rules.viewpoints},
            "include": {"type": "array", "items": ref, "uniqueItems": True},
            "include_layers": {"type": "array", "items": {"enum": rules.layer_order()}, "uniqueItems": True},
            "scope": {**ref, "description": "C4 views: the system/container/deployment node in focus."},
            "state": {"enum": VIEW_STATES, "default": "change", "description": "change (default: everything, changes highlighted), baseline or target."},
            "layout": {
                "type": "object",
                "additionalProperties": bounds,
                "description": "Optional fixed [x, y, w, h] per element id (captured by import-oef); otherwise auto-layout.",
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://a4m.local/schema/a4m.schema.json",
        "title": "a4m model file",
        "description": "One YAML file of an a4m solution architecture (models/<sa>/**/*.yaml).",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string", "description": "model.yaml only: model name."},
            "version": {"type": ["string", "number"], "description": "model.yaml only."},
            "documentation": {"type": "string", "description": "model.yaml only."},
            "properties": properties,
            "kind": {"enum": SA_KINDS, "default": "solution", "description": "model.yaml only: solution, platform (consumed by other SAs) or enterprise."},
            "status": {"enum": SA_STATUSES, "default": "draft", "description": "model.yaml only: lifecycle of the SA; changes reach the landscape target once approved."},
            "owner": {"type": "string", "description": "model.yaml only: owning team or person."},
            "exports": {
                "oneOf": [{"const": "*"}, {"type": "array", "items": {"type": "string", "pattern": ID_PATTERN}, "uniqueItems": True}],
                "description": "model.yaml only: ids other SAs may reference as <sa>/<id> (\"*\" = all).",
            },
            "elements": {"type": "array", "items": {"$ref": "#/$defs/element"}},
            "relationships": {"type": "array", "items": {"$ref": "#/$defs/relationship"}},
            "views": {"type": "array", "items": {"$ref": "#/$defs/view"}},
        },
        "$defs": {"element": element, "relationship": relationship, "view": view},
    }


def schema_json(rules: Rules | None = None) -> str:
    return json.dumps(build_schema(rules), indent=2) + "\n"


def write_schema() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_json(), encoding="utf-8")
