"""Model validation. Messages are written so an LLM (or a human) can fix them without guessing."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .adr import check_adrs
from .c4 import C4Projector
from .issues import Issue, error, warning
from .model import Model
from .rules import ARCHIMATE_VERSION, RELATIONSHIP_TYPES, Rules, load_rules
from .state import in_baseline, in_target
from .views import view_members

C4_SCOPE_TAG = {"c4-container": "system", "c4-component": "container", "c4-context": "system", "c4-deployment": "deployment"}
C4_SCOPE_REQUIRED = {"c4-container", "c4-component"}


def validate(model: Model, rules: Rules | None = None) -> list[Issue]:
    rules = rules or load_rules()
    issues = list(model.issues)
    issues += _check_elements(model, rules)
    issues += _check_relationships(model, rules)
    issues += _check_states(model)
    issues += _check_sa(model, rules)
    issues += _check_c4(model, rules)
    issues += _check_views(model, rules)
    issues += check_adrs(model)
    issues += _check_coverage(model, rules)
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def _check_elements(model: Model, rules: Rules) -> list[Issue]:
    issues = []
    for el in model.own_elements():
        if el.type not in rules.types:
            hint = rules.suggest_type(el.type)
            issues.append(error("unknown-type", f"unknown element type '{el.type}'" + (f"; did you mean {', '.join(hint)}?" if hint else "; run `a4m types`"), el.file, el.id))
            continue
        layer = rules.layer_of(el.type)
        prefix = rules.layers[layer].get("prefix")
        if prefix and not el.id.startswith(prefix + "-"):
            issues.append(warning("id-prefix", f"{el.type} is in the {layer} layer; id should start with '{prefix}-'", el.file, el.id))
        folder = _sa_folder(model, el.file)
        if folder != rules.folder_of(el.type) and not (rules.folder_of(el.type) is None and folder in rules.layer_folders()):
            where = rules.folder_of(el.type) or " or ".join(f"{f}/" for f in rules.layer_folders())
            issues.append(error(
                "layer-folder",
                f"{el.type} belongs to the {layer} layer; move it to models/{model.sa}/{where}"
                + ("/" if rules.folder_of(el.type) else "")
                + f" (it is in {folder + '/' if folder else 'the SA root'})",
                el.file, el.id,
            ))
        if el.junction_type and el.type != "Junction":
            issues.append(error("bad-attribute", "junction_type is only valid on Junction", el.file, el.id))
        if el.c4_shape and el.c4 not in ("container", "system", "component"):
            issues.append(error("bad-attribute", "c4_shape needs c4: system, container or component", el.file, el.id))
    return issues


def _sa_folder(model: Model, file: str) -> str:
    """First folder of a file below models/<sa>/ ("" for files directly in the SA folder)."""
    path = Path(file)
    if not path.is_absolute():
        path = model.path.parent.parent / path  # paths are shown relative to the workspace root
    try:
        parts = path.resolve().relative_to(model.path.resolve()).parts
    except ValueError:
        return ""
    return parts[0] if len(parts) > 1 else ""


def _concept_type(model: Model, concept_id: str) -> str | None:
    if concept_id in model.elements:
        return model.elements[concept_id].type
    if concept_id in model.relationships:
        return "Relationship"
    return None


def _check_relationships(model: Model, rules: Rules) -> list[Issue]:
    issues = []
    triples = Counter((r.type, r.source, r.target) for r in model.own_relationships())
    for rel in model.own_relationships():
        if rel.type not in RELATIONSHIP_TYPES:
            hint = rules.suggest_relationship(rel.type)
            issues.append(error("unknown-relationship", f"unknown relationship type '{rel.type}'" + (f"; did you mean {', '.join(hint)}?" if hint else ""), rel.file, rel.id))
            continue
        src_type, tgt_type = _concept_type(model, rel.source), _concept_type(model, rel.target)
        for end, ref in (("source", rel.source), ("target", rel.target)):
            if _concept_type(model, ref) is None and "/" not in ref:  # cross-SA refs are reported on load
                hint = _close_ids(model, ref)
                issues.append(error("dangling-ref", f"{end} '{ref}' does not exist" + (f"; did you mean {', '.join(hint)}?" if hint else ""), rel.file, rel.id))
        known = set(rules.types) | {"Relationship"}
        if src_type not in known or tgt_type not in known:
            continue  # dangling ref or unknown element type: already reported
        if not rules.is_allowed(src_type, rel.type, tgt_type):
            allowed = rules.allowed(src_type, tgt_type)
            msg = f"{rel.type} {src_type}→{tgt_type} is not allowed by ArchiMate {ARCHIMATE_VERSION}. "
            msg += f"Allowed {src_type}→{tgt_type}: {', '.join(allowed) or 'none'}."
            if rules.is_allowed(tgt_type, rel.type, src_type):
                msg += f" Note: {rel.type} {tgt_type}→{src_type} (reversed) is allowed."
            issues.append(error("invalid-relationship", msg, rel.file, rel.id))
        if rel.access and rel.type != "Access":
            issues.append(error("bad-attribute", "access is only valid on Access relationships", rel.file, rel.id))
        if rel.modifier and rel.type != "Influence":
            issues.append(error("bad-attribute", "modifier is only valid on Influence relationships", rel.file, rel.id))
        if rel.directed and rel.type != "Association":
            issues.append(error("bad-attribute", "directed is only valid on Association relationships", rel.file, rel.id))
        if rel.source == rel.target and rel.type in ("Composition", "Aggregation", "Specialization"):
            issues.append(error("self-relationship", f"an element cannot {rel.type.lower()} itself", rel.file, rel.id))
        if "/" in rel.source and "/" in rel.target:
            issues.append(warning(
                "foreign-relationship",
                f"both ends belong to other SAs; declare this relationship in {rel.source.split('/')[0]} or {rel.target.split('/')[0]}",
                rel.file, rel.id,
            ))
        if triples[(rel.type, rel.source, rel.target)] > 1 and not rel.explicit_id:
            issues.append(warning("duplicate-relationship", f"{rel.type} {rel.source}→{rel.target} is declared more than once", rel.file, rel.id))
    return issues


def _check_states(model: Model) -> list[Issue]:
    """A relationship exists in a state only if both its ends do (baseline: not new; target: not retiring)."""
    issues = []
    for rel in model.relationships.values():
        for ref in (rel.source, rel.target):
            end = model.elements.get(ref) or model.relationships.get(ref)
            if end is None or (rel.foreign and end.foreign):
                continue  # another SA's internals: checked in that SA
            for state_name, present, fix in (("current", in_baseline, "new"), ("target", in_target, "retiring")):
                if present(rel.state) and not present(end.state):
                    msg = f"{rel.type} {rel.source}→{rel.target} is {rel.state} but {ref} is {end.state}, so it cannot exist in the {state_name} state"
                    if rel.foreign:  # another SA uses our element
                        issues.append(warning("consumer-impact", f"{msg}; {rel.sa} still depends on it (relationship in {rel.file})", end.file, ref))
                    elif end.foreign:  # we use another SA's element
                        issues.append(warning("consumer-impact", f"{msg} in {end.sa}; mark the relationship `state: {fix}` or plan the change with {end.sa}", rel.file, rel.id))
                    else:
                        issues.append(error("state-mismatch", f"{msg}; mark the relationship `state: {fix}`", rel.file, rel.id))
    return issues


def _check_sa(model: Model, rules: Rules) -> list[Issue]:
    issues = []
    model_file = f"models/{model.sa}/model.yaml"
    if model.exports != "*":
        for ref in model.exports:
            if ref not in model.elements or model.elements[ref].foreign:
                issues.append(error("bad-export", f"exports '{ref}', which is not an element of {model.sa}", model_file))
    changed = [e for e in model.own_elements() if e.state != "existing"] + [r for r in model.own_relationships() if r.state != "existing"]
    if model.status == "implemented" and any(c.state in ("new", "retiring") for c in changed):
        issues.append(warning(
            "sa-status",
            f"status is implemented but {len(changed)} items are still new/changed/retiring; set them to existing "
            "(and delete retired ones) or change the status",
            model_file,
        ))
    if model.status in ("proposed", "approved") and not changed:
        issues.append(warning("sa-status", f"status is {model.status} but nothing is new, changed or retiring (implemented?)", model_file))
    workspace = model.workspace
    if workspace is not None:
        mine = {(e.type, _norm(e.name)): e for e in model.own_elements() if e.type not in ("Junction", "Grouping")}
        for other in workspace.sas():
            if other == model.sa:
                continue
            for el in workspace.own(other).elements.values():
                twin = mine.get((el.type, _norm(el.name)))
                if twin:
                    if workspace.own(other).is_exported(el.id):
                        how = f"reference `{other}/{el.id}` instead of redefining it"
                    else:
                        how = "keep it in the SA that owns it, export it there and reference it as <sa>/<id> from the other"
                    issues.append(warning(
                        "duplicate-across-sas",
                        f"{el.type} '{el.name}' is also defined in {other} ({other}/{el.id}); if it is the same thing, {how}",
                        twin.file, twin.id,
                    ))
    return issues


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _check_c4(model: Model, rules: Rules) -> list[Issue]:
    issues = []
    projector = C4Projector(model, rules)
    tags = rules.c4["tags"]
    for el in model.own_elements():
        if not el.c4:
            continue
        spec = tags[el.c4]
        if el.type not in spec["types"]:
            issues.append(error("c4-type", f"c4: {el.c4} must be one of {', '.join(spec['types'])}, not {el.type}", el.file, el.id))
        parent_tag = spec.get("parent")
        if parent_tag:
            parents = projector.parents(el.id)
            if len(parents) != 1:
                found = f"found {len(parents)} ({', '.join(parents)})" if parents else "found none"
                issues.append(error(
                    "c4-parent",
                    f"c4: {el.c4} needs exactly one c4: {parent_tag} parent via Composition/Aggregation "
                    f"(add `{{ type: Composition, source: <{parent_tag}-id>, target: {el.id} }}`); {found}",
                    el.file, el.id,
                ))
    return issues


def _check_views(model: Model, rules: Rules) -> list[Issue]:
    issues = []
    for view in model.views.values():
        for ref in view.include:
            if ref not in model.elements and "/" not in ref:
                hint = _close_ids(model, ref)
                issues.append(error("view-ref", f"include '{ref}' is not an element" + (f"; did you mean {', '.join(hint)}?" if hint else ""), view.file, view.id))
        for ref in view.layout:
            if ref not in model.elements:
                issues.append(warning("view-layout-ref", f"layout entry '{ref}' is not an element", view.file, view.id))
        if view.is_c4:
            if view.include or view.include_layers:
                issues.append(warning("view-c4-include", "C4 views are derived from c4 tags; include/include_layers are ignored", view.file, view.id))
            if view.kind in C4_SCOPE_REQUIRED and not view.scope:
                issues.append(error("view-scope", f"{view.kind} needs scope: <c4 {C4_SCOPE_TAG[view.kind]} id>", view.file, view.id))
            if view.scope and (view.scope in model.elements or "/" not in view.scope):  # bad cross-SA refs: reported on load
                scope = model.elements.get(view.scope)
                if scope is None:
                    issues.append(error("view-scope", f"scope '{view.scope}' does not exist", view.file, view.id))
                elif scope.c4 != C4_SCOPE_TAG[view.kind]:
                    issues.append(error("view-scope", f"{view.kind} scope must have c4: {C4_SCOPE_TAG[view.kind]} ('{scope.id}' has c4: {scope.c4})", view.file, view.id))
        else:
            if view.scope:
                issues.append(warning("view-scope", "scope only applies to C4 views", view.file, view.id))
            if not view.include and not view.include_layers:
                issues.append(error("view-empty", "view needs include: [ids] and/or include_layers: [layers]", view.file, view.id))
    return issues


def _check_coverage(model: Model, rules: Rules) -> list[Issue]:
    """Warnings that keep the model tidy: orphans and elements nobody can see."""
    if any(i.severity == "error" for i in _check_views(model, rules)):
        return []
    issues = []
    on_a_view: set[str] = set()
    for view in model.views.values():
        on_a_view.update(view_members(model, view, rules))
    connected = {r.source for r in model.relationships.values()} | {r.target for r in model.relationships.values()}
    for el in model.own_elements():
        if el.id not in connected:
            issues.append(warning("orphan", "element has no relationships", el.file, el.id))
        if el.id not in on_a_view:
            issues.append(warning("not-in-view", "element does not appear on any view", el.file, el.id))
    return issues


def _close_ids(model: Model, ref: str) -> list[str]:
    import difflib

    return difflib.get_close_matches(ref, list(model.elements) + list(model.relationships), n=3, cutoff=0.6)
