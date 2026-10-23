"""The workspace: models/ holds one folder per solution architecture (SA).

Every element is owned by exactly one SA. Other SAs reference it as `<sa>/<id>` (only ids the
owner lists under `exports:`), and the relationship lives in the SA that references it. The
enterprise architecture is the union of all SAs (`merged`).

`model(sa)` returns one SA with the other SAs' elements it needs attached as *foreign*
concepts (keyed by their qualified id), so validation, views and C4 work across SAs:
* elements it references directly,
* elements of other SAs that reference it (its consumers), with those relationships,
* the elements standing behind those (Realization/Assignment/Composition/Aggregation),
  so a referenced service resolves to its C4 system and a VM to its host.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from .issues import error
from .model import Element, Model, Relationship, list_sas, load_own, split_ref
from .paths import workspace_root

LANDSCAPE = "_landscape"  # pseudo-SA name of the merged workspace (not a valid SA id)
BEHIND = {"Realization", "Assignment", "Composition", "Aggregation"}
MAX_DEPTH = 5


def qualify(sa: str, ref: str) -> str:
    return ref if "/" in ref else f"{sa}/{ref}"


def localize(sa: str, ref: str) -> str:
    prefix = sa + "/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


@dataclass
class Usage:
    """One cross-SA relationship: `consumer` declares `rel`, which touches an element owned by `provider`."""

    consumer: str
    provider: str
    rel: Relationship  # as in the merged model (qualified ids)


class Workspace:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or workspace_root())
        self._own: dict[str, Model] = {}

    def sas(self) -> list[str]:
        return list_sas(self.root)

    def own(self, sa: str) -> Model:
        if sa not in self._own:
            self._own[sa] = load_own(sa, self.root)
        return self._own[sa]

    @cached_property
    def sa_status(self) -> dict[str, str]:
        return {sa: self.own(sa).status for sa in self.sas()}

    @cached_property
    def merged(self) -> Model:
        """All SAs in one model, every id qualified as <sa>/<id>."""
        enterprise = [self.own(sa) for sa in self.sas() if self.own(sa).kind == "enterprise"]
        model = Model(
            sa=LANDSCAPE,
            path=self.root / "models",
            name=enterprise[0].name if enterprise else "Architecture landscape",
            documentation=enterprise[0].documentation if enterprise else "",
            kind="landscape",
            status="implemented",
            sa_status=self.sa_status,
            workspace=self,
        )
        for sa in self.sas():
            own = self.own(sa)
            for el in own.elements.values():
                model.elements[qualify(sa, el.id)] = replace(el, id=qualify(sa, el.id))
            for rel in own.relationships.values():
                q = f"{sa}/{rel.id}"  # default ids of cross-SA relationships already contain a '/'
                model.relationships[q] = replace(rel, id=q, source=qualify(sa, rel.source), target=qualify(sa, rel.target))
            model.adrs.extend(replace(a, affects=[qualify(sa, x) for x in a.affects]) for a in own.adrs)
        return model

    # --- cross-SA usage ----------------------------------------------------------------

    @cached_property
    def usages(self) -> list[Usage]:
        found = []
        for rel in self.merged.relationships.values():
            providers = {split_ref(end)[0] for end in (rel.source, rel.target)} - {rel.sa}
            found += [Usage(rel.sa, p, rel) for p in sorted(providers) if p in self.sa_status]
        return found

    def dependencies(self) -> dict[str, dict[str, list[Relationship]]]:
        """consumer SA -> provider SA -> relationships."""
        deps: dict[str, dict[str, list[Relationship]]] = defaultdict(lambda: defaultdict(list))
        for usage in self.usages:
            deps[usage.consumer][usage.provider].append(usage.rel)
        return deps

    def consumers_of(self, ref: str) -> list[Usage]:
        """Usages of one element (`<sa>/<id>`) or of every element of an SA (`<sa>`)."""
        if "/" in ref:
            return [u for u in self.usages if ref in (u.rel.source, u.rel.target) and u.consumer != split_ref(ref)[0]]
        return [u for u in self.usages if u.provider == ref]

    # --- one SA with its neighbourhood -------------------------------------------------

    def model(self, sa: str) -> Model:
        own = self.own(sa)
        model = replace(
            own,
            elements=dict(own.elements),
            relationships=dict(own.relationships),
            issues=list(own.issues),
            referenced=set(),
            sa_status=self.sa_status,
            workspace=self,
        )
        if model.issues and model.issues[0].code == "no-model":
            return model
        merged = self.merged

        seeds: set[str] = set()
        for ref, file, where in self._references(own):
            if self._check_ref(model, ref, file, where):
                model.referenced.add(ref)
                seeds.add(ref)
        inbound = [
            r for r in merged.relationships.values()
            if r.sa != sa and any(split_ref(end)[0] == sa for end in (r.source, r.target))
        ]
        for rel in inbound:
            seeds.update(end for end in (rel.source, rel.target) if split_ref(end)[0] != sa)

        attached: set[str] = set()
        frontier = [(s, 0) for s in seeds if s in merged.elements]
        while frontier:
            ref, depth = frontier.pop()
            if ref in attached or split_ref(ref)[0] == sa:
                continue
            attached.add(ref)
            if depth < MAX_DEPTH:
                frontier += [(r.source, depth + 1) for r in merged.incoming.get(ref, []) if r.type in BEHIND]

        for ref in sorted(attached):
            model.elements[ref] = replace(merged.elements[ref], foreign=True)
        for rel in merged.relationships.values():
            if rel.sa == sa:
                continue
            source, target = localize(sa, rel.source), localize(sa, rel.target)
            if source in model.elements and target in model.elements:
                model.relationships[rel.id] = replace(rel, source=source, target=target, foreign=True)
        return model

    def _references(self, own: Model):
        """(qualified ref, file, referring id) for every reference to another SA."""
        for rel in own.relationships.values():
            for end in (rel.source, rel.target):
                if "/" in end:
                    yield end, rel.file, rel.id
        for view in own.views.values():
            for ref in [*view.include, *([view.scope] if view.scope else [])]:
                if "/" in ref:
                    yield ref, view.file, view.id
        for record in own.adrs:
            for ref in record.affects:
                if "/" in ref:
                    yield ref, record.file, record.id

    def _check_ref(self, model: Model, ref: str, file: str, where: str) -> bool:
        owner, local = split_ref(ref)
        if owner not in self.sa_status:
            hint = difflib.get_close_matches(owner, self.sas(), n=3, cutoff=0.5)
            model.issues.append(error(
                "unknown-sa",
                f"'{ref}': there is no SA '{owner}' under models/" + (f"; did you mean {', '.join(hint)}?" if hint else f" (SAs: {', '.join(self.sas())})"),
                file, where,
            ))
            return False
        provider = self.own(owner)
        if local not in provider.elements:
            hint = difflib.get_close_matches(local, list(provider.elements), n=3, cutoff=0.6)
            model.issues.append(error(
                "dangling-ref",
                f"'{ref}': {owner} has no element '{local}'" + (f"; did you mean {', '.join(owner + '/' + h for h in hint)}?" if hint else ""),
                file, where,
            ))
            return False
        if not provider.is_exported(local):
            exported = sorted(provider.elements) if provider.exports == "*" else provider.exports
            model.issues.append(error(
                "not-exported",
                f"'{ref}' is internal to {owner}. Reference one of its exports instead "
                f"({', '.join(owner + '/' + e for e in exported) or 'it exports nothing'}), "
                f"or add '{local}' to exports in models/{owner}/model.yaml",
                file, where,
            ))
        return True  # still attach it, so the rest of the model renders
