"""a4m command line. Run `python3 -m a4m --help`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .adr import new_adr
from .build import build, render_view
from .import_oef import import_oef
from .landscape import build_landscape
from .model import sa_path
from .paths import workspace_root
from .rules import RELATIONSHIP_TYPES, load_rules
from .schema import schema_json, write_schema
from .validate import has_errors, validate
from .workspace import Workspace


def _sas(ws: Workspace, sa: str | None) -> list[str]:
    """The SA named on the command line, or every SA when none is given."""
    if sa is None:
        return ws.sas()
    if sa not in ws.sas():
        sys.exit(f"a4m: no SA '{sa}' under models/ (SAs: {', '.join(ws.sas()) or 'none'})")
    return [sa]


def cmd_validate(args) -> int:
    ws = Workspace()
    results = []
    for sa in _sas(ws, args.sa):
        model = ws.model(sa)
        results.append((model, validate(model)))
    failed = any(has_errors(issues) for _, issues in results)
    if args.format == "json":
        payload = [{"sa": m.sa, "ok": not has_errors(i), "issues": [x.to_dict() for x in i]} for m, i in results]
        print(json.dumps(payload[0] if args.sa else {"ok": not failed, "sas": payload}, indent=2))
        return 1 if failed else 0
    for model, issues in results:
        for issue in issues:
            if args.warnings or issue.severity == "error":
                print(issue)
    for model, issues in results:
        errors = sum(i.severity == "error" for i in issues)
        warnings = len(issues) - errors
        status = "FAILED" if errors else "OK"
        hint = "" if args.warnings or not warnings else " (use -w to list warnings)"
        print(f"{status}: {model.sa} — {len(model.own_elements())} elements, {len(model.own_relationships())} relationships, "
              f"{len(model.views)} views, {len(model.adrs)} ADRs; {errors} errors, {warnings} warnings{hint}")
    return 1 if failed else 0


def cmd_build(args) -> int:
    """Build the named SA (or all), then the enterprise landscape when every SA is valid."""
    ws = Workspace()
    root = workspace_root()
    invalid = []
    for sa in ws.sas():
        issues = validate(ws.model(sa))
        if has_errors(issues):
            invalid.append(sa)
            if args.sa in (None, sa):
                for issue in issues:
                    if issue.severity == "error":
                        print(issue)
    targets = _sas(ws, args.sa)
    if any(sa in invalid for sa in targets) and not args.force:
        print("build aborted: fix the errors above (or --force)")
        return 1
    results = [build(ws.model(sa), root) for sa in targets]
    if invalid and not args.force:
        print(f"landscape not rebuilt: {', '.join(invalid)} has validation errors")
    else:
        results.append(build_landscape(ws, root))
    for result in results:
        print(f"wrote {result.oef.relative_to(root).as_posix()}")
        for path in result.docs:
            print(f"wrote {path.relative_to(root).as_posix()}")
        for path in result.removed:
            print(f"removed stale {path.relative_to(root).as_posix()}")
    return 0


def cmd_sas(args) -> int:
    ws = Workspace()
    deps = ws.dependencies()
    rows = []
    for sa in ws.sas():
        own = ws.own(sa)
        used_by = sorted(c for c, providers in deps.items() if sa in providers)
        changes = sum(c.state != "existing" for c in [*own.elements.values(), *own.relationships.values()])
        exports = "*" if own.exports == "*" else str(len(own.exports))
        rows.append([sa, own.kind, own.status, str(len(own.elements)), str(changes), exports,
                     ",".join(sorted(deps.get(sa, {}))) or "-", ",".join(used_by) or "-"])
    header = ["SA", "KIND", "STATUS", "ELEMENTS", "CHANGES", "EXPORTS", "USES", "USED BY"]
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    return 0


def cmd_impact(args) -> int:
    ws = Workspace()
    owner = args.ref.split("/")[0]
    if owner not in ws.sas():
        sys.exit(f"a4m: no SA '{owner}' (SAs: {', '.join(ws.sas())})")
    if "/" in args.ref and args.ref not in ws.merged.elements:
        sys.exit(f"a4m: {owner} has no element '{args.ref.split('/', 1)[1]}'")
    usages = ws.consumers_of(args.ref)
    adrs = [(a, ref) for a in ws.merged.adrs for ref in a.affects
            if (ref == args.ref or ("/" not in args.ref and ref.startswith(owner + "/"))) and not a.file.startswith(f"models/{owner}/")]
    if not usages and not adrs:
        print(f"nothing outside {owner} depends on {args.ref}")
        return 0
    for consumer in sorted({u.consumer for u in usages}):
        print(f"{consumer} ({ws.own(consumer).status}):")
        for u in (u for u in usages if u.consumer == consumer):
            rel = u.rel
            state = "" if rel.state == "existing" else f" [{rel.state}]"
            print(f"  {rel.type} {rel.source} -> {rel.target}{' — ' + rel.name if rel.name else ''}{state}  ({rel.file})")
    for record, ref in adrs:
        print(f"ADR {record.id} {record.title!r} affects {ref}  ({record.file})")
    return 0


def cmd_types(args) -> int:
    rules = load_rules()
    layers = [args.layer] if args.layer else rules.layer_order()
    for layer in layers:
        if layer not in rules.layers:
            sys.exit(f"a4m: unknown layer '{layer}' (choose from {', '.join(rules.layer_order())})")
        spec = rules.layers[layer]
        where = f"folder {layer}/, id prefix '{spec['prefix']}-'" if spec.get("prefix") else "any layer folder"
        print(f"{spec['label']} ({where})")
        for name in rules.types_in_layer(layer):
            print(f"  {name:26} {rules.aspect_of(name)}")
    if not args.layer:
        print("Relationships: " + ", ".join(RELATIONSHIP_TYPES))
        print("C4 tags: " + ", ".join(f"{t} ({'/'.join(s['types'])})" for t, s in rules.c4["tags"].items()))
    return 0


def cmd_allowed(args) -> int:
    rules = load_rules()
    for name in (args.source, args.target):
        if name not in rules.types and name != "Relationship":
            hint = rules.suggest_type(name)
            sys.exit(f"a4m: unknown type '{name}'" + (f"; did you mean {', '.join(hint)}?" if hint else ""))
    allowed = rules.allowed(args.source, args.target)
    if args.format == "json":
        print(json.dumps({"source": args.source, "target": args.target, "allowed": allowed}))
    else:
        print(f"{args.source} → {args.target}: {', '.join(allowed) or 'no relationships allowed'}")
    return 0


def cmd_mermaid(args) -> int:
    model = Workspace().model(args.sa)
    view = model.views.get(args.view)
    if view is None:
        sys.exit(f"a4m: no view '{args.view}' in {model.sa}; views: {', '.join(model.views)}")
    print(render_view(model, view, state=args.state), end="")
    return 0


def cmd_import(args) -> int:
    result = import_oef(Path(args.file), args.sa)
    root = workspace_root()
    for path in result.written:
        print(f"wrote {path.relative_to(root)}")
    for path in result.removed:
        print(f"removed {path.relative_to(root)}")
    for old, new in result.renamed.items():
        print(f"id {old} -> {new}")
    print("review with `git diff`, then run `python3 -m a4m validate`")
    return 0


def cmd_schema(args) -> int:
    if args.write:
        write_schema()
        print("wrote schema/a4m.schema.json")
    else:
        print(schema_json(), end="")
    return 0


def cmd_new_adr(args) -> int:
    path = new_adr(sa_path(args.sa), args.title)
    print(f"created {path.relative_to(workspace_root())}")
    return 0


def cmd_mcp(args) -> int:
    from .mcp_server import serve

    serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="a4m", description="ArchiMate architecture-as-code: solution architectures as YAML → validate → Archi (OEF) + Mermaid/C4 docs")
    parser.add_argument("--version", action="version", version=f"a4m {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check SAs against the schema, ArchiMate rules, cross-SA references, C4 and ADR links")
    p.add_argument("sa", nargs="?", help="one SA (default: all)")
    p.add_argument("-w", "--warnings", action="store_true", help="also list warnings")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="validate, then write build/<sa>.oef.xml, docs/<sa>/*.md and the landscape (docs/README.md)")
    p.add_argument("sa", nargs="?", help="one SA (default: all)")
    p.add_argument("--force", action="store_true", help="build even if validation fails")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("sas", help="list the solution architectures: kind, status, changes, dependencies")
    p.set_defaults(func=cmd_sas)

    p = sub.add_parser("impact", help="who depends on an SA or on one of its elements (<sa> or <sa>/<id>)")
    p.add_argument("ref")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("types", help="list ArchiMate element types by layer")
    p.add_argument("--layer")
    p.set_defaults(func=cmd_types)

    p = sub.add_parser("allowed", help="relationship types allowed from one element type to another")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_allowed)

    p = sub.add_parser("mermaid", help="print one view as Mermaid")
    p.add_argument("sa")
    p.add_argument("view")
    p.add_argument("--state", choices=["change", "baseline", "target"], help="default: the view's own state")
    p.set_defaults(func=cmd_mermaid)

    p = sub.add_parser("import-oef", help="import an Open Exchange XML file (e.g. from Archi) into models/<sa>")
    p.add_argument("file")
    p.add_argument("sa")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("schema", help="print (or --write) the JSON Schema for model YAML")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("new-adr", help="create the next ADR from the template")
    p.add_argument("sa")
    p.add_argument("title")
    p.set_defaults(func=cmd_new_adr)

    p = sub.add_parser("mcp", help="run the MCP server on stdio (for Copilot / Claude / other MCP clients)")
    p.set_defaults(func=cmd_mcp)

    args = parser.parse_args(argv)
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # Windows consoles default to a legacy code page
            stream.reconfigure(encoding="utf-8")
    return args.func(args)
