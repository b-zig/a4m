---
id: ADR-0001
title: Keep the architecture as ArchiMate YAML in git, with C4 as derived views
status: accepted
date: 2026-10-23
affects: [bus-pri-as-code, bus-goal-portable, bus-wp-office]
---

## Context

Architecture diagrams drift when they are drawn by hand. We want an LLM (Claude Code now,
GitHub Copilot at the office) to maintain the model, and the result must be checkable.

## Decision

- The model is YAML under `models/<sa>/`, one folder per solution architecture (SA), validated against Archi's ArchiMate 3.2
  relationship matrix.
- Archi is the rich viewer/editor via the Open Exchange Format (`build/<sa>.oef.xml`, `build/_landscape.oef.xml`).
- Mermaid docs (flowchart + C4) are generated for GitHub/VS Code.
- C4 is a projection of the same model (`c4:` tags), not a second source of truth.

## Consequences

- Every change is a reviewable diff; CI rejects invalid ArchiMate.
- Archi edits must be round-tripped with `a4m import-oef`.
