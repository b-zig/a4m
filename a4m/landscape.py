"""The enterprise landscape: every solution architecture (SA) merged into one model.

Nothing here is drawn by hand. `a4m build` writes
* docs/README.md — the SAs (kind, status, changes), their dependency map and links,
* docs/_landscape/*.md — the C4 system landscape and deployment across all SAs, and the
  consumers of every platform,
* build/_landscape.oef.xml — one Archi model holding every SA and all their views.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .build import MARKER, BuildResult, view_page
from .export_mermaid import escape, mermaid_id
from .export_oef import export_oef
from .model import Model, View, split_ref
from .rules import Rules, load_rules
from .state import APPROVED
from .views import view_members
from .workspace import LANDSCAPE, Workspace, qualify

KIND_COLORS = {"enterprise": "#fff3c4", "platform": "#d6eaff", "solution": "#e3f5d8"}


def landscape_model(ws: Workspace, with_sa_views: bool = False, rules: Rules | None = None) -> Model:
    """The merged model plus generated landscape views (and, for Archi, every SA's views)."""
    rules = rules or load_rules()
    merged = ws.merged
    views = {
        "landscape-context": View(
            id="landscape-context",
            name=f"{merged.name} — system landscape",
            kind="c4-context",
            documentation="Every system of every solution architecture, grouped by SA, with the people who use them. "
            "Generated from the c4 tags and relationships of all SAs.",
        ),
        "landscape-deployment": View(
            id="landscape-deployment",
            name=f"{merged.name} — deployment",
            kind="c4-deployment",
            documentation="Where every container and system runs, across all SAs.",
        ),
    }
    if with_sa_views:
        for sa in ws.sas():
            model = ws.model(sa)
            for view in model.views.values():
                members = [qualify(sa, m) for m in view_members(model, view, rules)]
                views[f"{sa}/{view.id}"] = View(
                    id=f"{sa}/{view.id}",
                    name=f"{model.name}: {view.name}",
                    documentation=view.documentation,
                    viewpoint=None if view.is_c4 else view.viewpoint,
                    include=members,
                    state=view.state,
                    layout={qualify(sa, k): v for k, v in view.layout.items()},
                )
    return replace(merged, views=views)


def build_landscape(ws: Workspace, root: Path, rules: Rules | None = None) -> BuildResult:
    rules = rules or load_rules()
    oef_path = root / "build" / f"{LANDSCAPE}.oef.xml"
    oef_path.parent.mkdir(parents=True, exist_ok=True)
    oef_path.write_text(export_oef(landscape_model(ws, with_sa_views=True, rules=rules), rules), encoding="utf-8")
    result = BuildResult(oef_path)

    model = landscape_model(ws, rules=rules)
    docs = root / "docs"
    pages = {
        docs / "README.md": index_page(ws, model),
        docs / LANDSCAPE / "system-landscape.md": view_page(model, model.views["landscape-context"], rules, "../README.md", "../.."),
        docs / LANDSCAPE / "deployment.md": view_page(model, model.views["landscape-deployment"], rules, "../README.md", "../.."),
        docs / LANDSCAPE / "consumers.md": consumers_page(ws),
    }
    for path, text in pages.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{MARKER}\n{text}", encoding="utf-8")
        result.docs.append(path)
    for stale in (docs / LANDSCAPE).glob("*.md"):
        if stale not in pages and stale.read_text(encoding="utf-8").startswith(MARKER):
            stale.unlink()
            result.removed.append(stale)
    # docs/<sa>/ folders of SAs that no longer exist
    for folder in docs.iterdir() if docs.is_dir() else []:
        if folder.is_dir() and folder.name != LANDSCAPE and folder.name not in ws.sa_status:
            generated = [p for p in folder.glob("*.md") if p.read_text(encoding="utf-8").startswith(MARKER)]
            for page in generated:
                page.unlink()
                result.removed.append(page)
            if not any(folder.iterdir()):
                folder.rmdir()
    return result


def _changes(model: Model) -> str:
    counts = {s: 0 for s in ("new", "changed", "retiring")}
    for concept in [*model.elements.values(), *model.relationships.values()]:
        if concept.state in counts:
            counts[concept.state] += 1
    parts = [f"{sign}{counts[s]} {s}" for sign, s in (("+", "new"), ("~", "changed"), ("−", "retiring")) if counts[s]]
    return ", ".join(parts) or "—"


def index_page(ws: Workspace, model: Model) -> str:
    deps = ws.dependencies()
    used_by: dict[str, set[str]] = {}
    for consumer, providers in deps.items():
        for provider in providers:
            used_by.setdefault(provider, set()).add(consumer)

    out = [f"# {model.name}", ""]
    if model.documentation:
        out += [model.documentation.strip(), ""]
    out += [
        f"{len(ws.sas())} solution architectures · {len(model.elements)} elements · {len(model.relationships)} relationships.",
        "Each SA lives in `models/<sa>/`; this page and `docs/_landscape/` are generated from all of them.",
        "",
        "- [System landscape](_landscape/system-landscape.md) — every system, grouped by SA (C4)",
        "- [Deployment](_landscape/deployment.md) — where everything runs (C4)",
        "- [Platform consumers](_landscape/consumers.md) — who uses what each SA exports",
        f"- Archi: import `build/{LANDSCAPE}.oef.xml` for the whole enterprise in one model",
        "",
        "## Solution architectures",
        "",
        "| SA | Kind | Status | Owner | Elements | Changes | Uses | Used by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sa in ws.sas():
        own = ws.own(sa)
        uses = ", ".join(f"[{p}]({p}/README.md)" for p in sorted(deps.get(sa, {}))) or "—"
        users = ", ".join(f"[{c}]({c}/README.md)" for c in sorted(used_by.get(sa, set()))) or "—"
        out.append(
            f"| [{own.name}]({sa}/README.md) (`{sa}`) | {own.kind} | {own.status} | {own.owner or '—'} "
            f"| {len(own.elements)} | {_changes(own)} | {uses} | {users} |"
        )
    out += [
        "",
        "Changes in an SA reach the landscape's target state once the SA is **approved** (or implemented).",
        "",
        "## Dependencies between SAs",
        "",
        "An arrow means the SA at the tail references elements of the SA at the head (number = relationships; dashed = all new).",
        "",
        "```mermaid",
        dependency_map(ws).rstrip(),
        "```",
        "",
    ]
    return "\n".join(out) + "\n"


def dependency_map(ws: Workspace) -> str:
    lines = ["flowchart LR"]
    for sa in ws.sas():
        own = ws.own(sa)
        lines.append(f'  sa_{mermaid_id(sa)}["{escape(own.name)}<br/>«{own.kind}» · {own.status}"]')
    for consumer, providers in sorted(ws.dependencies().items()):
        for provider, rels in sorted(providers.items()):
            arrow = "-.->" if all(r.state == "new" for r in rels) else "-->"
            lines.append(f'  sa_{mermaid_id(consumer)} {arrow}|"{len(rels)}"| sa_{mermaid_id(provider)}')
    for kind, color in KIND_COLORS.items():
        ids = [f"sa_{mermaid_id(sa)}" for sa in ws.sas() if ws.own(sa).kind == kind]
        if ids:
            lines.append(f"  classDef {kind} fill:{color},stroke:#555,color:#000")
            lines.append(f"  class {','.join(ids)} {kind}")
    pending = [f"sa_{mermaid_id(sa)}" for sa in ws.sas() if ws.own(sa).status not in APPROVED]
    if pending:
        lines.append("  classDef pending stroke-dasharray:6 4")
        lines.append(f"  class {','.join(pending)} pending")
    return "\n".join(lines) + "\n"


def consumers_page(ws: Workspace) -> str:
    merged = ws.merged
    out = ["# Platform consumers", "", "[index](../README.md)", "",
           "Every relationship one SA declares to an element owned by another SA, grouped by the owner.",
           "Use `python3 -m a4m impact <sa>/<id>` before changing or retiring an exported element.", ""]
    for provider in ws.sas():
        usages = [u for u in ws.usages if u.provider == provider]
        if not usages:
            continue
        own = ws.own(provider)
        out += [f"## {own.name} (`{provider}`, {own.kind})", "", "| Element | Used by | Relationship | State |", "|---|---|---|---|"]
        rows = []
        for u in usages:
            rel = u.rel
            ends = [e for e in (rel.source, rel.target) if split_ref(e)[0] == provider]
            for end in ends:
                el = merged.elements.get(end)
                label = f"{el.name} (`{end}`)" if el else f"`{end}`"
                exported = el is not None and own.is_exported(split_ref(end)[1])
                text = f"{rel.type} `{rel.source}` → `{rel.target}`" + (f" — {rel.name}" if rel.name else "")
                rows.append((label + ("" if exported else " ⚠ not exported"), u.consumer, text, rel.state))
        for label, consumer, text, state in sorted(rows):
            out.append(f"| {label} | [{consumer}](../{consumer}/README.md) | {text} | {'' if state == 'existing' else state} |")
        out.append("")
    if len(out) == 7:
        out.append("No SA references another SA yet.")
    return "\n".join(out) + "\n"
