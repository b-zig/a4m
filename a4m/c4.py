"""Project the ArchiMate model onto C4 views (context / container / component / deployment).

C4 elements are ArchiMate elements tagged with `c4:`. Arrows are derived from ArchiMate
interactions (Serving, Flow, Triggering, Access); untagged intermediates such as an
ApplicationService or a BusinessRole collapse onto the tagged elements behind them, and
relationships to nested elements roll up to whatever is visible at the view's C4 level.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Element, Model, View
from .rules import Rules
from .state import display_state

MAX_COLLAPSE_DEPTH = 5


@dataclass
class C4Rel:
    source: str
    target: str
    label: str
    technology: str = ""
    state: str = "existing"


@dataclass
class C4Diagram:
    kind: str
    title: str
    elements: list[str] = field(default_factory=list)  # every element shown (excl. deployment nodes)
    boundary: tuple[str, str, list[str]] | None = None  # (mermaid macro, element id or label, member ids)
    rels: list[C4Rel] = field(default_factory=list)
    # deployment views only
    roots: list[str] = field(default_factory=list)
    children: dict[str, list[str]] = field(default_factory=dict)
    hosted: dict[str, list[str]] = field(default_factory=dict)  # deployment node -> element ids
    groups: list[tuple[str, str, list[str]]] = field(default_factory=list)  # landscape: (sa, label, ids) inside the boundary

    def archimate_members(self) -> list[str]:
        """Element ids to place on the matching Archi view."""
        ids = list(self.elements)
        if self.boundary and self.boundary[1] not in ids:
            ids.insert(0, self.boundary[1])
        stack = list(self.roots)
        while stack:
            node = stack.pop(0)
            if node not in ids:
                ids.append(node)
            stack[:0] = self.children.get(node, [])
        for hosted in self.hosted.values():
            ids.extend(h for h in hosted if h not in ids)
        return [i for i in ids if not i.startswith("label:")]


class C4Projector:
    def __init__(self, model: Model, rules: Rules):
        self.model = model
        self.rules = rules
        self.spec = rules.c4

    # --- structure -----------------------------------------------------------------------

    def tagged(self, tag: str) -> list[str]:
        return [e.id for e in self.model.elements.values() if e.c4 == tag]

    def tag(self, element_id: str) -> str | None:
        el = self.model.elements.get(element_id)
        return el.c4 if el else None

    def parents(self, element_id: str) -> list[str]:
        """Structural C4 parents: a container's systems, a component's containers, a deployment node's nodes."""
        tag = self.tag(element_id)
        if tag == "deployment":
            parent_tag, nesting = "deployment", self.spec["deployment_nesting"]
        else:
            parent_tag = self.spec["tags"].get(tag, {}).get("parent") if tag else None
            nesting = self.spec["nesting"]
        if not parent_tag:
            return []
        return [
            r.source
            for r in self.model.incoming.get(element_id, [])
            if r.type in nesting and self.tag(r.source) == parent_tag and r.source != element_id
        ]

    def parent(self, element_id: str) -> str | None:
        found = self.parents(element_id)
        return found[0] if found else None

    def system_of(self, element_id: str) -> str | None:
        current, guard = element_id, 0
        while current and self.tag(current) != "system" and guard < 10:
            current, guard = self.parent(current), guard + 1
        return current if current and self.tag(current) == "system" else None

    def children_of(self, element_id: str, tag: str) -> list[str]:
        return [e for e in self.tagged(tag) if self.parent(e) == element_id]

    # --- interactions --------------------------------------------------------------------

    def resolve(self, concept_id: str, depth: int = 0, seen: frozenset = frozenset()) -> set[str]:
        """Tagged element(s) standing behind concept_id."""
        if self.tag(concept_id):
            return {concept_id}
        if depth >= MAX_COLLAPSE_DEPTH or concept_id in seen:
            return set()
        found: set[str] = set()
        for rel in self.model.incoming.get(concept_id, []):
            if rel.type in self.spec["collapse_via"]:
                found |= self.resolve(rel.source, depth + 1, seen | {concept_id})
        return found

    def interactions(self) -> list[C4Rel]:
        result: list[C4Rel] = []
        for rel in self.model.relationships.values():
            spec = self.spec["interactions"].get(rel.type)
            if not spec:
                continue
            label = _c4_label(rel, spec)
            technology = str(rel.properties.get("technology", ""))
            state = display_state(self.model, rel)
            for s in sorted(self.resolve(rel.source)):
                for t in sorted(self.resolve(rel.target)):
                    a, b = (t, s) if spec["flip"] else (s, t)
                    if a != b:
                        result.append(C4Rel(a, b, label, technology, state))
        return result

    def representative(self, element_id: str, visible: set[str]) -> str | None:
        current, guard = element_id, 0
        while current and current not in visible and guard < 10:
            current, guard = self.parent(current), guard + 1
        return current if current in visible else None

    def rolled_rels(self, visible: set[str], keep=lambda a, b: True) -> list[C4Rel]:
        merged: dict[tuple[str, str], C4Rel] = {}
        for rel in self.interactions():
            a = self.representative(rel.source, visible)
            b = self.representative(rel.target, visible)
            if not a or not b or a == b or not keep(a, b):
                continue
            existing = merged.get((a, b))
            if existing is None:
                merged[(a, b)] = C4Rel(a, b, rel.label, rel.technology, rel.state)
                continue
            if rel.label not in existing.label.split("; "):
                existing.label = f"{existing.label}; {rel.label}"
            if rel.state != existing.state:
                existing.state = "changed"  # the arrow exists before and after, with different content
        return list(merged.values())

    # --- views ---------------------------------------------------------------------------

    def project(self, view: View) -> C4Diagram:
        handler = {
            "c4-context": self._context,
            "c4-container": self._container,
            "c4-component": self._component,
            "c4-deployment": self._deployment,
        }[view.kind]
        return handler(view)

    def _context(self, view: View) -> C4Diagram:
        visible = set(self.tagged("person")) | set(self.tagged("system"))
        if view.scope:
            rels = self.rolled_rels(visible, keep=lambda a, b: view.scope in (a, b))
            shown = {view.scope} | {r.source for r in rels} | {r.target for r in rels}
        else:
            rels = self.rolled_rels(visible)
            shown = visible
        ordered = self._ordered(shown)
        internal = [
            e for e in ordered
            if self.tag(e) == "system" and not self.model.elements[e].external and not self.model.elements[e].foreign
        ]
        if self.model.kind == "landscape":
            # System landscape: the enterprise, with one boundary per solution architecture.
            groups: dict[str, list[str]] = {}
            for e in internal:
                groups.setdefault(self.model.elements[e].sa, []).append(e)
            boundary = ("Enterprise_Boundary", f"label:{self.model.name}", internal) if internal else None
            return C4Diagram(view.kind, view.name, ordered, boundary, rels, groups=[(sa, sa_label(self.model, sa), ids) for sa, ids in groups.items()])
        boundary = ("Boundary", f"label:{self.model.name or self.model.sa}", internal) if internal else None
        return C4Diagram(view.kind, view.name, ordered, boundary, rels)

    def _container(self, view: View) -> C4Diagram:
        system = view.scope
        inner = self.children_of(system, "container")
        visible = set(inner) | set(self.tagged("person")) | (set(self.tagged("system")) - {system})
        rels = self.rolled_rels(visible, keep=lambda a, b: a in inner or b in inner)
        shown = set(inner) | {r.source for r in rels} | {r.target for r in rels}
        return C4Diagram(view.kind, view.name, self._ordered(shown), ("System_Boundary", system, inner), rels)

    def _component(self, view: View) -> C4Diagram:
        container = view.scope
        system = self.system_of(container)
        inner = self.children_of(container, "component")
        siblings = set(self.children_of(system, "container")) - {container} if system else set()
        visible = set(inner) | siblings | set(self.tagged("person")) | (set(self.tagged("system")) - {system})
        rels = self.rolled_rels(visible, keep=lambda a, b: a in inner or b in inner)
        shown = set(inner) | {r.source for r in rels} | {r.target for r in rels}
        return C4Diagram(view.kind, view.name, self._ordered(shown), ("Container_Boundary", container, inner), rels)

    def _deployment(self, view: View) -> C4Diagram:
        nodes = self.tagged("deployment")
        children: dict[str, list[str]] = {}
        for node in nodes:
            parent = self.parent(node)
            if parent:
                children.setdefault(parent, []).append(node)
        roots = [view.scope] if view.scope else [n for n in nodes if not self.parent(n)]
        in_scope = _subtree(roots, children)

        # Deployable units: containers, plus systems that have no containers.
        units = self.tagged("container") + [s for s in self.tagged("system") if not self.children_of(s, "container")]
        if self.model.kind != "landscape":
            # An SA's deployment: its own units, plus other SAs' units it interacts with.
            own = {u for u in units if not self.model.elements[u].foreign}
            partners = {e for r in self.rolled_rels(set(units)) for e in (r.source, r.target) if {r.source, r.target} & own}
            units = [u for u in units if u in own or u in partners]
        hosted: dict[str, list[str]] = {}
        for unit in units:
            for host in self._hosts(unit):
                if host in in_scope:
                    hosted.setdefault(host, []).append(unit)
        placed = {u for members in hosted.values() for u in members}
        rels = self.rolled_rels(set(units), keep=lambda a, b: a in placed and b in placed)
        # Only nodes that (transitively) host something: Mermaid rejects empty Deployment_Node blocks.
        populated = {n for n in in_scope if _subtree([n], children) & set(hosted)}
        return C4Diagram(
            view.kind, view.name, self._ordered(placed), None, rels,
            roots=[r for r in roots if r in populated],
            children={k: [c for c in v if c in populated] for k, v in children.items() if k in populated},
            hosted=hosted,
        )

    def _hosts(self, unit: str) -> list[str]:
        hosting = self.spec["hosting"]
        hosts: list[str] = []
        for rel in self.model.incoming.get(unit, []):
            if rel.type not in hosting["direct"]:
                continue
            source = self.model.elements.get(rel.source)
            if source is None:
                continue
            if source.c4 == "deployment":
                hosts.append(source.id)
            elif source.type == "Artifact":
                hosts.extend(
                    r.source
                    for r in self.model.incoming.get(source.id, [])
                    if r.type in hosting["via_artifact"] and self.tag(r.source) == "deployment"
                )
        return list(dict.fromkeys(hosts))

    def _ordered(self, ids: set[str]) -> list[str]:
        """Model declaration order, persons first."""
        order = {"person": 0, "system": 1, "container": 2, "component": 3, "deployment": 4}
        declared = [e for e in self.model.elements if e in ids]
        return sorted(declared, key=lambda e: order.get(self.tag(e) or "", 9))


def sa_label(model: Model, sa: str) -> str:
    """Display name of an SA (its model.yaml name)."""
    workspace = model.workspace
    return workspace.own(sa).name if workspace is not None and sa in workspace.sa_status else sa


def _subtree(roots: list[str], children: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(children.get(node, []))
    return seen


def _c4_label(rel, spec: dict) -> str:
    """C4 arrow text. A flipped relationship's ArchiMate name reads the wrong way round,
    so it becomes "Uses — <name>"; `properties.c4_label` overrides either form."""
    if rel.properties.get("c4_label"):
        return str(rel.properties["c4_label"])
    default = _access_label(rel.access) if rel.type == "Access" else spec["label"]
    if not rel.name:
        return default
    return f"{default} — {rel.name}" if spec["flip"] else rel.name


def _access_label(access: str | None) -> str:
    return {"read": "Reads", "write": "Writes", "readwrite": "Reads/writes"}.get(access or "write", "Accesses")


def element_description(el: Element, limit: int = 90) -> str:
    text = " ".join((el.documentation or "").split())
    first = text.split(". ")[0]
    first = first if len(first) <= limit else first[: limit - 1].rstrip() + "…"
    return f"[{el.sa}] {first}".rstrip() if el.foreign else first
