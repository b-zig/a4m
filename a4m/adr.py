"""Architecture Decision Records: models/<sa>/decisions/ADR-NNNN-<slug>.md with YAML front-matter (numbered per SA)."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .issues import Issue, error, warning

STATUSES = ["proposed", "accepted", "superseded", "deprecated", "rejected"]
ADR_ID = re.compile(r"^ADR-(\d{4})$")
FILE_NAME = re.compile(r"^(ADR-\d{4})(-[a-z0-9-]+)?\.md$")

TEMPLATE = """---
id: {id}
title: {title}
status: proposed
date: {date}
affects: []          # element / relationship / view ids this decision touches (<sa>/<id> for other SAs)
# supersedes: [ADR-0000]
# superseded_by: ADR-0000
---

## Context

What forces are at play? What problem are we solving?

## Decision

What we decided, stated in full sentences.

## Consequences

What becomes easier or harder; follow-up work (link WorkPackage ids if modelled).
"""


@dataclass
class Adr:
    id: str
    title: str
    status: str
    date: str
    file: str
    affects: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    body: str = ""

    @property
    def number(self) -> int:
        return int(self.id.split("-")[1])


def parse_adr(path: Path, display: str) -> tuple[Adr | None, list[Issue]]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not match:
        return None, [error("adr-front-matter", "missing YAML front-matter (--- ... ---)", display)]
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return None, [error("adr-front-matter", f"invalid YAML: {exc}".replace("\n", " "), display)]

    issues: list[Issue] = []
    adr_id = str(meta.get("id", ""))
    if not ADR_ID.match(adr_id):
        issues.append(error("adr-id", f"id '{adr_id}' must look like ADR-0001", display))
        return None, issues
    name_match = FILE_NAME.match(path.name)
    if not name_match or name_match.group(1) != adr_id:
        issues.append(error("adr-id", f"file name should start with {adr_id} (e.g. {adr_id}-short-title.md)", display, adr_id))
    status = str(meta.get("status", ""))
    if status not in STATUSES:
        issues.append(error("adr-status", f"status '{status}' must be one of {', '.join(STATUSES)}", display, adr_id))
    if not meta.get("title"):
        issues.append(error("adr-title", "title is required", display, adr_id))

    affects = meta.get("affects") or []
    supersedes = meta.get("supersedes") or []
    if isinstance(supersedes, str):
        supersedes = [supersedes]
    return (
        Adr(
            id=adr_id,
            title=str(meta.get("title", "")),
            status=status,
            date=str(meta.get("date", "")),
            file=display,
            affects=[str(a) for a in affects] if isinstance(affects, list) else [str(affects)],
            supersedes=[str(s) for s in supersedes],
            superseded_by=str(meta["superseded_by"]) if meta.get("superseded_by") else None,
            body=match.group(2),
        ),
        issues,
    )


def check_adrs(model) -> list[Issue]:
    """Cross-reference checks: affects resolve, supersession links are consistent, numbering has no gaps."""
    issues: list[Issue] = []
    by_id: dict[str, Adr] = {}
    for record in model.adrs:
        if record.id in by_id:
            issues.append(error("adr-duplicate", f"{record.id} also defined in {by_id[record.id].file}", record.file, record.id))
            continue
        by_id[record.id] = record

    known = set(model.elements) | set(model.relationships) | set(model.views)
    for record in by_id.values():
        for ref in record.affects:
            if ref not in known and "/" not in ref:  # cross-SA refs are checked on load
                issues.append(error("adr-unknown-ref", f"affects '{ref}', which is not an element, relationship or view id", record.file, record.id))
        for old in record.supersedes:
            if old not in by_id:
                issues.append(error("adr-unknown-adr", f"supersedes unknown {old}", record.file, record.id))
        if record.superseded_by and record.superseded_by not in by_id:
            issues.append(error("adr-unknown-adr", f"superseded_by unknown {record.superseded_by}", record.file, record.id))
        if record.status == "superseded" and not record.superseded_by:
            issues.append(error("adr-supersession", "status is superseded but superseded_by is not set", record.file, record.id))
        if record.superseded_by and record.status != "superseded":
            issues.append(warning("adr-supersession", f"superseded_by is set but status is '{record.status}'", record.file, record.id))
        if not record.affects:
            issues.append(warning("adr-no-links", "affects is empty; link the element ids this decision concerns", record.file, record.id))

    numbers = sorted(r.number for r in by_id.values())
    for expected, actual in zip(range(1, len(numbers) + 1), numbers):
        if expected != actual:
            issues.append(warning("adr-numbering", f"ADR numbering gap: expected ADR-{expected:04d} before ADR-{actual:04d}"))
            break
    return issues


def adrs_affecting(model, concept_ids: set[str]) -> list[Adr]:
    return [r for r in sorted(model.adrs, key=lambda r: r.id) if concept_ids & set(r.affects)]


def new_adr(sa_dir: Path, title: str, today: dt.date | None = None) -> Path:
    decisions = sa_dir / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    numbers = [int(m.group(1)[4:]) for p in decisions.glob("ADR-*.md") if (m := FILE_NAME.match(p.name))]
    adr_id = f"ADR-{(max(numbers) + 1) if numbers else 1:04d}"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "decision"
    path = decisions / f"{adr_id}-{slug}.md"
    path.write_text(TEMPLATE.format(id=adr_id, title=json.dumps(title), date=(today or dt.date.today()).isoformat()), encoding="utf-8")
    return path
