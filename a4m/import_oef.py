"""Import an Open Exchange (OEF) file — e.g. exported from Archi — back into models/<sa>/ YAML.

Round-trip rules:
* ids that are valid a4m ids are kept; Archi-generated ids (id-<uuid>) become <layer-prefix>-<slug>.
* concepts that already exist stay in the YAML file they came from; new ones go to
  <layer>/imported.yaml, relationships/imported.yaml or views/imported.yaml.
* C4 views are derived, so an existing C4 view definition is kept as-is.
* view positions are stored under `layout:` only when they differ from the auto-layout.
* elements and relationships owned by other SAs (property a4m:sa) are not written; references
  to them stay `<sa>/<id>`. Generated `--baseline` / `--target` view copies are skipped.
* YAML comments in rewritten files are not preserved (review the git diff).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .export_oef import NS, STATE_VIEW_SUFFIXES, XSI
from .layout import flatten, layout_view
from .model import MODEL_FILE, Element, Model, Relationship, View, default_relationship_id, load_model
from .paths import workspace_root
from .rules import Rules, load_rules
from .schema import ID_PATTERN
from .state import at_state
from .views import view_members
from .workspace import localize

ARCHI_ID = re.compile(r"^id-[0-9a-f]{32}$")
VALID_ID = re.compile(ID_PATTERN)
ACCESS = {"Access": "access", "Read": "read", "Write": "write", "ReadWrite": "readwrite"}


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(_q(tag))
    return (child.text or "").strip() if child is not None else ""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unnamed"


@dataclass
class ImportResult:
    written: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    renamed: dict[str, str] = field(default_factory=dict)


class _IdMapper:
    def __init__(self, taken: set[str]):
        self.taken = set(taken)
        self.mapping: dict[str, str] = {}

    def map(self, original: str, fallback_base: str) -> str:
        if original in self.mapping:
            return self.mapping[original]
        if VALID_ID.match(original) and not ARCHI_ID.match(original):
            new = original
        else:
            base, new, n = fallback_base, fallback_base, 2
            while new in self.taken:
                new, n = f"{base}-{n}", n + 1
        self.taken.add(new)
        self.mapping[original] = new
        return new


def import_oef(oef_path: Path, sa: str, root: Path | None = None, rules: Rules | None = None) -> ImportResult:
    rules = rules or load_rules()
    root = root or workspace_root()
    sa_dir = root / "models" / sa
    existing = load_model(sa, root) if (sa_dir / MODEL_FILE).exists() else None

    def ident(node: ET.Element, attr: str = "identifier") -> str:
        # export_oef writes `<sa>/<id>` as `<sa>.<id>`; ids of this SA become local again
        return localize(sa, (node.get(attr) or "").replace(".", "/"))

    xml_root = ET.parse(oef_path).getroot()
    prop_names = {
        d.get("identifier"): _text(d, "name")
        for d in xml_root.iterfind(f"{_q('propertyDefinitions')}/{_q('propertyDefinition')}")
    }

    def props(node: ET.Element) -> dict:
        out = {}
        for p in node.iterfind(f"{_q('properties')}/{_q('property')}"):
            out[prop_names.get(p.get("propertyDefinitionRef"), p.get("propertyDefinitionRef"))] = _text(p, "value")
        return out

    # Reserve every valid incoming id first so generated slugs never collide with a later one.
    reserved = {
        ident(n) for n in xml_root.iter()
        if n.get("identifier") and VALID_ID.match(ident(n)) and not ARCHI_ID.match(ident(n))
    }
    ids = _IdMapper(reserved)
    model = Model(sa=sa, path=sa_dir)
    model.name = _text(xml_root, "name") or sa
    model.documentation = _text(xml_root, "documentation")
    model.properties = props(xml_root)

    for node in xml_root.iterfind(f"{_q('elements')}/{_q('element')}"):
        xsi_type = node.get(f"{{{XSI}}}type")
        el_type = "Junction" if xsi_type in ("AndJunction", "OrJunction") else xsi_type
        name = _text(node, "name") or el_type
        prefix = rules.layers[rules.layer_of(el_type)]["prefix"]
        properties = props(node)
        owner = properties.pop("a4m:sa", sa)
        if owner != sa:  # another SA's element, shown on our views: keep the reference only
            ids.mapping[ident(node)] = ident(node)
            model.elements[ident(node)] = Element(id=ident(node), type=el_type, name=name, sa=owner, foreign=True)
            continue
        el_id = ids.map(ident(node), f"{prefix}-{slugify(name)}")
        el = Element(
            id=el_id,
            type=el_type,
            name=name,
            documentation=_text(node, "documentation"),
            c4=properties.pop("a4m:c4", None),
            c4_shape=properties.pop("a4m:c4_shape", None),
            external=properties.pop("a4m:external", "false") == "true",
            junction_type="or" if xsi_type == "OrJunction" else None,
            state=properties.pop("a4m:state", "existing"),
            properties=properties,
            sa=sa,
        )
        model.elements[el.id] = el

    rel_nodes = list(xml_root.iterfind(f"{_q('relationships')}/{_q('relationship')}"))
    pending = list(rel_nodes)
    # Relationships may target relationships; resolve in passes so referenced ones are mapped first.
    for _ in range(3):
        retry = []
        for node in pending:
            source, target = ids.mapping.get(ident(node, "source")), ids.mapping.get(ident(node, "target"))
            if source is None or target is None:
                retry.append(node)
                continue
            properties = props(node)
            rel_type = node.get(f"{{{XSI}}}type")
            owner = properties.pop("a4m:sa", sa)
            if owner != sa:  # declared by another SA: needed to compute views, never written
                model.relationships[ident(node)] = Relationship(
                    id=ident(node), type=rel_type, source=source, target=target, sa=owner, foreign=True
                )
                continue
            default = default_relationship_id(rel_type, source, target)
            original = ident(node)
            keep = VALID_ID.match(original) and not ARCHI_ID.match(original) and original != default
            rel_id = ids.map(original, default)
            rel = Relationship(
                id=rel_id,
                type=rel_type,
                source=source,
                target=target,
                name=_text(node, "name"),
                documentation=_text(node, "documentation"),
                state=properties.pop("a4m:state", "existing"),
                properties=properties,
                access=ACCESS.get(node.get("accessType", "Write")) if rel_type == "Access" else None,
                modifier=node.get("modifier") if rel_type == "Influence" else None,
                directed=node.get("isDirected") == "true",
                explicit_id=bool(keep) or rel_id != default,
                sa=sa,
            )
            model.relationships[rel.id] = rel
        pending = retry
        if not pending:
            break

    generated = tuple(suffix for suffix, _ in STATE_VIEW_SUFFIXES.values())
    for node in xml_root.iterfind(f"{_q('views')}/{_q('diagrams')}/{_q('view')}"):
        if ident(node).endswith(generated):
            continue
        name = _text(node, "name") or "View"
        view_id = ids.map(ident(node), f"view-{slugify(name)}")
        members, layout = [], {}
        for n in node.iter(_q("node")):
            ref = ids.mapping.get(ident(n, "elementRef")) if n.get("elementRef") else None
            if ref in model.elements and ref not in members:
                members.append(ref)
                layout[ref] = [int(n.get(k, 0)) for k in ("x", "y", "w", "h")]
        view = View(id=view_id, name=name, documentation=_text(node, "documentation"), viewpoint=node.get("viewpoint") or None, include=members, layout=layout)
        model.views[view.id] = view

    _reconcile_views(model, existing, rules)
    return _write(model, existing, sa_dir, root, rules, ids)


def _reconcile_views(model: Model, existing: Model | None, rules: Rules) -> None:
    for view_id, view in list(model.views.items()):
        old = existing.views.get(view_id) if existing else None
        if old and old.is_c4:
            model.views[view_id] = View(**{**old.__dict__})
            continue
        if old:
            view.state = old.state
        if old and set(view_members(at_state(existing, old.state), old, rules)) == set(view.include):
            view.include, view.include_layers = list(old.include), list(old.include_layers)
        captured, view.layout = view.layout, {}
        members = view_members(at_state(model, view.state), view, rules)
        auto = {p.ref: [p.x, p.y, p.w, p.h] for p in flatten(layout_view(model, view, members, rules)) if p.kind == "element"}
        if any(captured.get(m) != auto.get(m) for m in members):
            view.layout = {m: captured[m] for m in members if m in captured}


class _Flow(dict):
    """Marker: dump this mapping in YAML flow style."""


class _FlowList(list):
    pass


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(_Flow, lambda d, data: d.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True))
_Dumper.add_representer(_FlowList, lambda d, data: d.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True))


def _element_dict(el: Element) -> dict:
    out = {"id": el.id, "type": el.type, "name": el.name}
    if el.c4:
        out["c4"] = el.c4
    if el.c4_shape:
        out["c4_shape"] = el.c4_shape
    if el.external:
        out["external"] = True
    if el.junction_type:
        out["junction_type"] = el.junction_type
    if el.state != "existing":
        out["state"] = el.state
    if el.documentation:
        out["documentation"] = el.documentation
    if el.properties:
        out["properties"] = _Flow(el.properties)
    return out


def _relationship_dict(rel: Relationship) -> dict:
    out = _Flow()
    if rel.explicit_id:
        out["id"] = rel.id
    out.update(type=rel.type, source=rel.source, target=rel.target)
    for key in ("name", "documentation", "access", "modifier"):
        if getattr(rel, key):
            out[key] = getattr(rel, key)
    if rel.directed:
        out["directed"] = True
    if rel.state != "existing":
        out["state"] = rel.state
    if rel.properties:
        out["properties"] = _Flow(rel.properties)
    return out


def _view_dict(view: View) -> dict:
    out: dict = {"id": view.id, "name": view.name}
    if view.kind != "archimate":
        out["kind"] = view.kind
    if view.viewpoint:
        out["viewpoint"] = view.viewpoint
    if view.scope:
        out["scope"] = view.scope
    if view.state != "change":
        out["state"] = view.state
    if view.documentation:
        out["documentation"] = view.documentation
    if view.include:
        out["include"] = _FlowList(view.include)
    if view.include_layers:
        out["include_layers"] = _FlowList(view.include_layers)
    if view.layout:
        out["layout"] = {k: _FlowList(v) for k, v in view.layout.items()}
    return out


def _write(model: Model, existing: Model | None, sa_dir: Path, root: Path, rules: Rules, ids: _IdMapper) -> ImportResult:
    result = ImportResult(renamed={k: v for k, v in ids.mapping.items() if k != v})
    files: dict[str, dict[str, list]] = {}

    def home(kind: str, concept_id: str, default: str) -> dict[str, list]:
        old = existing and {"elements": existing.elements, "relationships": existing.relationships, "views": existing.views}[kind].get(concept_id)
        model_yaml = (sa_dir / MODEL_FILE).relative_to(root).as_posix()
        rel_path = old.file if old and old.file != model_yaml else (sa_dir / default).relative_to(root).as_posix()
        return files.setdefault(rel_path, {"elements": [], "relationships": [], "views": []})

    for el in model.own_elements():
        home("elements", el.id, f"{rules.layer_of(el.type)}/imported.yaml")["elements"].append(_element_dict(el))
    for rel in model.own_relationships():
        home("relationships", rel.id, "relationships/imported.yaml")["relationships"].append(_relationship_dict(rel))
    for view in model.views.values():
        home("views", view.id, "views/imported.yaml")["views"].append(_view_dict(view))

    sa_dir.mkdir(parents=True, exist_ok=True)
    model_file = sa_dir / MODEL_FILE
    if not model_file.exists():
        meta = {"name": model.name, "version": "0.1"}
        if model.documentation:
            meta["documentation"] = model.documentation
        if model.properties:
            meta["properties"] = model.properties
        model_file.write_text(yaml.dump(meta, Dumper=_Dumper, sort_keys=False, allow_unicode=True), encoding="utf-8")
        result.written.append(model_file)

    for rel_path, content in sorted(files.items()):
        path = root / rel_path
        if path == model_file:
            continue  # model.yaml holds metadata only in imported models
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {k: v for k, v in content.items() if v}
        path.write_text(yaml.dump(body, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        result.written.append(path)

    for stale in sa_dir.rglob("*.y*ml"):
        if stale != model_file and stale not in result.written:
            stale.unlink()
            result.removed.append(stale)
    return result
