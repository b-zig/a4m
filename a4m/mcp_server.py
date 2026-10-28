"""Minimal MCP server (JSON-RPC 2.0 over stdio, newline-delimited), stdlib only.

Exposes a4m's grounding and validation functions as tools so any MCP client
(GitHub Copilot agent mode, Claude Code, Claude Desktop, local agents) can use them.
The model itself is edited as YAML files with the client's normal file tools.
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict

from . import __version__
from .build import build, render_view
from .landscape import build_landscape
from .paths import workspace_root
from .rules import RELATIONSHIP_TYPES, load_rules
from .validate import has_errors, validate
from .workspace import Workspace

PROTOCOL_VERSION = "2025-06-18"
INSTRUCTIONS = (
    "a4m stores solution architectures (SAs) as ArchiMate YAML under models/<sa>/. Elements of other SAs are "
    "referenced as <sa>/<id> (only ids they export). Search all SAs (a4m_search) before adding anything shared, "
    "ground every edit with a4m_types / a4m_allowed, edit the YAML files directly, then call a4m_validate until it "
    "reports no errors, then a4m_build. See AGENTS.md in the repository for conventions."
)

SA_ARG = {"type": "string", "description": "Solution architecture: folder name under models/ (see a4m_list_sas)."}
SA_OPTIONAL = {"type": "string", "description": "Solution architecture under models/; omit for all SAs."}
TOOLS = [
    {
        "name": "a4m_validate",
        "description": "Validate one SA (or all): schema, ArchiMate 3.2 relationship rules, cross-SA references and exports, change states, C4 tags, views and ADR links. Returns issues with fix hints.",
        "inputSchema": {"type": "object", "properties": {"sa": SA_OPTIONAL}},
    },
    {
        "name": "a4m_list_sas",
        "description": "List the solution architectures: kind (solution/platform/enterprise), status, owner, exports and which SAs each one uses.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "a4m_impact",
        "description": "Who depends on an SA or on one of its elements: relationships declared in other SAs and ADRs. ref is <sa> or <sa>/<id>.",
        "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
    },
    {
        "name": "a4m_types",
        "description": "List ArchiMate element types (optionally for one layer) with their aspect, the folder they go in (models/<sa>/<layer>/) and the id prefix convention.",
        "inputSchema": {"type": "object", "properties": {"layer": {"type": "string"}}},
    },
    {
        "name": "a4m_allowed",
        "description": "Relationship types ArchiMate allows from source_type to target_type.",
        "inputSchema": {
            "type": "object",
            "properties": {"source_type": {"type": "string"}, "target_type": {"type": "string"}},
            "required": ["source_type", "target_type"],
        },
    },
    {
        "name": "a4m_search",
        "description": "Find elements whose id, name or type contains the query (case-insensitive), in one SA or all SAs (ids returned as <sa>/<id>, with whether they are exported).",
        "inputSchema": {"type": "object", "properties": {"sa": SA_OPTIONAL, "query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "a4m_get",
        "description": "Get one element, relationship or view by id (or <sa>/<id> without sa), with the element's incoming/outgoing relationships and source file.",
        "inputSchema": {"type": "object", "properties": {"sa": SA_OPTIONAL, "id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "a4m_list_views",
        "description": "List an SA's views (ArchiMate and C4).",
        "inputSchema": {"type": "object", "properties": {"sa": SA_ARG}, "required": ["sa"]},
    },
    {
        "name": "a4m_render_view",
        "description": "Render one view as Mermaid (flowchart for ArchiMate views, C4 syntax for C4 views); state: change (default, changes highlighted), baseline or target.",
        "inputSchema": {
            "type": "object",
            "properties": {"sa": SA_ARG, "view": {"type": "string"}, "state": {"enum": ["change", "baseline", "target"]}},
            "required": ["sa", "view"],
        },
    },
    {
        "name": "a4m_build",
        "description": "Validate, then write build/<sa>.oef.xml (import into Archi), docs/<sa>/*.md (Mermaid) and the enterprise landscape docs (docs/README.md, docs/_landscape/).",
        "inputSchema": {"type": "object", "properties": {"sa": SA_OPTIONAL}},
    },
]


def _sa(ws: Workspace, arguments: dict) -> str:
    sa = arguments.get("sa")
    if not sa:
        raise ValueError(f"sa is required; available: {', '.join(ws.sas()) or 'none'}")
    if sa not in ws.sas():
        raise ValueError(f"no SA '{sa}'; available: {', '.join(ws.sas())}")
    return sa


def call_tool(name: str, arguments: dict) -> tuple[object, bool]:
    """Returns (payload, is_error)."""
    rules = load_rules()
    if name == "a4m_types":
        layers = [arguments["layer"]] if arguments.get("layer") else rules.layer_order()
        return {
            layer: {"folder": layer if layer in rules.layer_folders() else None, "prefix": rules.layers[layer].get("prefix"), "types": {t: rules.aspect_of(t) for t in rules.types_in_layer(layer)}}
            for layer in layers
            if layer in rules.layers
        } | {"relationships": RELATIONSHIP_TYPES, "c4_tags": {t: s["types"] for t, s in rules.c4["tags"].items()}}, False
    if name == "a4m_allowed":
        return {"source": arguments["source_type"], "target": arguments["target_type"],
                "allowed": rules.allowed(arguments["source_type"], arguments["target_type"])}, False

    ws = Workspace()
    if name == "a4m_validate":
        results = {sa: validate(ws.model(sa), rules) for sa in ([_sa(ws, arguments)] if arguments.get("sa") else ws.sas())}
        return {
            "ok": not any(has_errors(i) for i in results.values()),
            "issues": [{"sa": sa, **i.to_dict()} for sa, issues in results.items() for i in issues],
        }, False
    if name == "a4m_list_sas":
        deps = ws.dependencies()
        return [
            {
                "sa": sa, "name": ws.own(sa).name, "kind": ws.own(sa).kind, "status": ws.own(sa).status,
                "owner": ws.own(sa).owner, "exports": ws.own(sa).exports,
                "uses": sorted(deps.get(sa, {})), "used_by": sorted(c for c, p in deps.items() if sa in p),
            }
            for sa in ws.sas()
        ], False
    if name == "a4m_impact":
        usages = ws.consumers_of(arguments["ref"])
        return [{"consumer": u.consumer, "type": u.rel.type, "source": u.rel.source, "target": u.rel.target,
                 "name": u.rel.name, "state": u.rel.state, "file": u.rel.file} for u in usages], False
    if name == "a4m_search":
        q = arguments["query"].lower()
        scope = ws.model(_sa(ws, arguments)).own_elements() if arguments.get("sa") else ws.merged.elements.values()
        hits = [
            {"id": e.id, "type": e.type, "name": e.name, "sa": e.sa, "exported": ws.own(e.sa).is_exported(e.id.split("/")[-1]),
             "state": e.state, "file": e.file}
            for e in scope
            if q in e.id.lower() or q in e.name.lower() or q in e.type.lower()
        ]
        return {"matches": hits[:50], "total": len(hits)}, False
    if name == "a4m_build":
        targets = [_sa(ws, arguments)] if arguments.get("sa") else ws.sas()
        invalid = {sa: [i.to_dict() for i in validate(ws.model(sa), rules) if i.severity == "error"] for sa in ws.sas()}
        invalid = {sa: errors for sa, errors in invalid.items() if errors}
        if any(sa in invalid for sa in targets):
            return {"built": False, "errors": invalid}, True
        root = workspace_root()
        results = [build(ws.model(sa), root, rules) for sa in targets]
        if not invalid:
            results.append(build_landscape(ws, root, rules))
        return {
            "built": True,
            "landscape": not invalid,
            "files": [p.relative_to(root).as_posix() for r in results for p in [r.oef, *r.docs]],
        }, False

    if name == "a4m_get" and not arguments.get("sa") and "/" in arguments.get("id", ""):
        arguments = {**arguments, "sa": arguments["id"].split("/")[0], "id": arguments["id"].split("/", 1)[1]}
    model = ws.model(_sa(ws, arguments))
    if name == "a4m_get":
        concept_id = arguments["id"]
        concept = model.elements.get(concept_id) or model.relationships.get(concept_id) or model.views.get(concept_id)
        if concept is None:
            return {"error": f"no element, relationship or view '{concept_id}'"}, True
        payload = {"kind": type(concept).__name__.lower(), **{k: v for k, v in asdict(concept).items() if k != "workspace"}}
        if concept_id in model.elements:
            payload["outgoing"] = [asdict(r) for r in model.outgoing.get(concept_id, [])]
            payload["incoming"] = [asdict(r) for r in model.incoming.get(concept_id, [])]
        return payload, False
    if name == "a4m_list_views":
        return [{"id": v.id, "name": v.name, "kind": v.kind, "file": v.file} for v in model.views.values()], False
    if name == "a4m_render_view":
        view = model.views.get(arguments["view"])
        if view is None:
            return {"error": f"no view '{arguments['view']}'", "views": list(model.views)}, True
        return render_view(model, view, rules, arguments.get("state")), False
    return {"error": f"unknown tool '{name}'"}, True


def handle(message: dict) -> dict | None:
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:
        return None  # notification (e.g. notifications/initialized)
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        result = {
            "protocolVersion": requested or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "a4m", "version": __version__},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            payload, is_error = call_tool(params.get("name", ""), params.get("arguments") or {})
        except Exception as exc:  # report tool failures to the model rather than killing the server
            payload, is_error = f"{type(exc).__name__}: {exc}", True
            traceback.print_exc(file=sys.stderr)
        text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
        result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {exc}"}}
        else:
            response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
