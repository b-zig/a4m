"""Load one solution architecture (SA), models/<sa>/**/*.yaml, into an in-memory Model.

`load_own` reads only the SA's own files. `load_model` also attaches the elements of other SAs
that this SA references (`<sa>/<id>`) or that reference it; see workspace.py.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import jsonschema
import yaml

from . import adr as adr_mod
from .issues import Issue, error, warning
from .paths import workspace_root
from .schema import build_schema
from .state import SA_KINDS, SA_STATUSES

MODEL_FILE = "model.yaml"
MODEL_ONLY_KEYS = {"name", "version", "documentation", "properties", "kind", "status", "owner", "exports"}


@dataclass
class Element:
    id: str
    type: str
    name: str
    documentation: str = ""
    properties: dict = field(default_factory=dict)
    c4: str | None = None
    c4_shape: str | None = None
    external: bool = False
    junction_type: str | None = None
    state: str = "existing"
    file: str = ""
    sa: str = ""  # owning SA
    foreign: bool = False  # owned by another SA, attached because it is referenced


@dataclass
class Relationship:
    id: str
    type: str
    source: str
    target: str
    name: str = ""
    documentation: str = ""
    properties: dict = field(default_factory=dict)
    access: str | None = None
    modifier: str | None = None
    directed: bool = False
    state: str = "existing"
    file: str = ""
    explicit_id: bool = False
    sa: str = ""
    foreign: bool = False


@dataclass
class View:
    id: str
    name: str
    kind: str = "archimate"
    documentation: str = ""
    viewpoint: str | None = None
    include: list[str] = field(default_factory=list)
    include_layers: list[str] = field(default_factory=list)
    scope: str | None = None
    state: str = "change"
    layout: dict[str, list[int]] = field(default_factory=dict)
    file: str = ""

    @property
    def is_c4(self) -> bool:
        return self.kind.startswith("c4-")


@dataclass
class Model:
    sa: str
    path: Path
    name: str = ""
    version: str = ""
    documentation: str = ""
    properties: dict = field(default_factory=dict)
    kind: str = "solution"  # solution | platform | enterprise ("landscape" for the merged workspace)
    status: str = "draft"
    owner: str = ""
    exports: list[str] | str = field(default_factory=list)  # ids other SAs may reference, or "*"
    elements: dict[str, Element] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    views: dict[str, View] = field(default_factory=dict)
    adrs: list[adr_mod.Adr] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)  # problems found while loading
    referenced: set[str] = field(default_factory=set)  # other SAs' ids this SA references directly
    sa_status: dict[str, str] = field(default_factory=dict)  # status of every SA in the workspace
    workspace: object = field(default=None, repr=False, compare=False)

    def is_exported(self, local_id: str) -> bool:
        return self.exports == "*" or local_id in self.exports

    def own_elements(self) -> list[Element]:
        return [e for e in self.elements.values() if not e.foreign]

    def own_relationships(self) -> list[Relationship]:
        return [r for r in self.relationships.values() if not r.foreign]

    def concept(self, concept_id: str) -> Element | Relationship | None:
        return self.elements.get(concept_id) or self.relationships.get(concept_id)

    @cached_property
    def outgoing(self) -> dict[str, list[Relationship]]:
        index: dict[str, list[Relationship]] = defaultdict(list)
        for rel in self.relationships.values():
            index[rel.source].append(rel)
        return index

    @cached_property
    def incoming(self) -> dict[str, list[Relationship]]:
        index: dict[str, list[Relationship]] = defaultdict(list)
        for rel in self.relationships.values():
            index[rel.target].append(rel)
        return index


def default_relationship_id(rel_type: str, source: str, target: str) -> str:
    return f"rel-{source}-{rel_type.lower()}-{target}"


def sa_path(sa: str, root: Path | None = None) -> Path:
    candidate = Path(sa)
    if candidate.is_dir() and (candidate / MODEL_FILE).exists():
        return candidate.resolve()
    return (root or workspace_root()) / "models" / sa


def list_sas(root: Path | None = None) -> list[str]:
    models = (root or workspace_root()) / "models"
    return sorted(p.name for p in models.iterdir() if (p / MODEL_FILE).exists()) if models.is_dir() else []


def load_model(sa: str, root: Path | None = None) -> Model:
    """The SA with everything it references in (or is referenced by) other SAs attached."""
    from .workspace import Workspace

    return Workspace(root).model(sa)


def split_ref(ref: str) -> tuple[str | None, str]:
    """'edf/app-kafka' -> ('edf', 'app-kafka'); 'app-x' -> (None, 'app-x').

    Splits at the first '/': merged relationship ids look like 'orders/rel-edf/app-x-serving-app-y'."""
    owner, sep, local = ref.partition("/")
    return (owner, local) if sep else (None, ref)


def load_own(sa: str, root: Path | None = None) -> Model:
    """Only the SA's own files: no other SA is read."""
    root = root or workspace_root()
    path = sa_path(sa, root)
    model = Model(sa=path.name, path=path)
    if not (path / MODEL_FILE).exists():
        model.issues.append(error("no-model", f"{path} has no {MODEL_FILE}; known SAs: {', '.join(list_sas(root)) or 'none'}"))
        return model
    own_prefix = model.sa + "/"

    def local(ref):
        # `<this sa>/<id>` is just a long way of writing `<id>`
        return ref[len(own_prefix):] if isinstance(ref, str) and ref.startswith(own_prefix) else ref

    validators = _item_validators()
    seen: dict[str, str] = {}  # id -> file, across all concept kinds

    def claim(concept_id: str, file: str) -> bool:
        if concept_id in seen:
            model.issues.append(
                error("duplicate-id", f"id '{concept_id}' already defined in {seen[concept_id]}", file, concept_id)
            )
            return False
        seen[concept_id] = file
        return True

    for yaml_path in sorted(path.rglob("*.y*ml")):
        rel_file = _display_path(yaml_path, root)
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            model.issues.append(error("yaml-syntax", str(exc).replace("\n", " "), rel_file))
            continue
        if not isinstance(data, dict):
            model.issues.append(error("schema", "top level must be a mapping", rel_file))
            continue

        is_model_file = yaml_path == path / MODEL_FILE
        for key in data:
            if key not in ("elements", "relationships", "views") and key not in MODEL_ONLY_KEYS:
                model.issues.append(error("schema", f"unknown top-level key '{key}' (expected elements, relationships, views)", rel_file))
            elif key in MODEL_ONLY_KEYS and not is_model_file:
                model.issues.append(warning("misplaced-key", f"'{key}' belongs in {MODEL_FILE}; ignored here", rel_file))
        if is_model_file:
            model.name = str(data.get("name", model.sa))
            model.version = str(data.get("version", ""))
            model.documentation = data.get("documentation", "")
            model.properties = data.get("properties") or {}
            model.kind = str(data.get("kind", "solution"))
            model.status = str(data.get("status", "draft"))
            model.owner = str(data.get("owner", ""))
            exports = data.get("exports", [])
            for key, value, allowed in (("kind", model.kind, SA_KINDS), ("status", model.status, SA_STATUSES)):
                if value not in allowed:
                    model.issues.append(error("sa-meta", f"{key} '{value}' must be one of {', '.join(allowed)}", rel_file))
            if exports == "*" or (isinstance(exports, list) and all(isinstance(x, str) for x in exports)):
                model.exports = exports
            else:
                model.issues.append(error("sa-meta", "exports must be a list of element ids, or \"*\"", rel_file))

        for kind in ("elements", "relationships", "views"):
            items = data.get(kind) or []
            if not isinstance(items, list):
                model.issues.append(error("schema", f"'{kind}' must be a list", rel_file))
                continue
            for index, item in enumerate(items):
                problems = sorted(validators[kind].iter_errors(item), key=lambda e: list(e.path))
                # An unknown `type` alone is left to the validator, which can suggest the right name.
                problems = [p for p in problems if not (kind != "views" and list(p.path) == ["type"] and p.validator == "enum")]
                if problems:
                    label = item.get("id", f"{kind}[{index}]") if isinstance(item, dict) else f"{kind}[{index}]"
                    for problem in problems:
                        at = "/".join(str(p) for p in problem.path)
                        model.issues.append(error("schema", f"{kind}[{index}]{'.' + at if at else ''}: {problem.message}", rel_file, str(label)))
                    continue
                if kind == "relationships":
                    item = {**item, "source": local(item["source"]), "target": local(item["target"])}
                elif kind == "views":
                    item = {**item, "include": [local(i) for i in item.get("include", [])]}
                    if item.get("scope"):
                        item["scope"] = local(item["scope"])
                    if item.get("layout"):
                        item["layout"] = {local(k): v for k, v in item["layout"].items()}
                if kind == "elements":
                    el = Element(**item, file=rel_file, sa=model.sa)
                    if claim(el.id, rel_file):
                        model.elements[el.id] = el
                elif kind == "relationships":
                    explicit = "id" in item
                    rel_id = item.get("id") or default_relationship_id(item["type"], item["source"], item["target"])
                    rel = Relationship(**{**item, "id": rel_id}, file=rel_file, explicit_id=explicit, sa=model.sa)
                    if claim(rel.id, rel_file):
                        model.relationships[rel.id] = rel
                else:
                    view = View(**item, file=rel_file)
                    if claim(view.id, rel_file):
                        model.views[view.id] = view

    for md_path in sorted((path / "decisions").glob("*.md")):
        parsed, problems = adr_mod.parse_adr(md_path, _display_path(md_path, root))
        model.issues.extend(problems)
        if parsed:
            parsed.affects = [local(a) for a in parsed.affects]
            model.adrs.append(parsed)
    return model


def _display_path(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(p)


_VALIDATORS: dict[str, jsonschema.protocols.Validator] | None = None


def _item_validators() -> dict[str, jsonschema.protocols.Validator]:
    global _VALIDATORS
    if _VALIDATORS is None:
        defs = build_schema()["$defs"]
        _VALIDATORS = {
            plural: jsonschema.Draft202012Validator({"$defs": defs, "$ref": f"#/$defs/{singular}"})
            for plural, singular in (("elements", "element"), ("relationships", "relationship"), ("views", "view"))
        }
    return _VALIDATORS
