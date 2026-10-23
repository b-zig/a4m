# Copilot instructions

This repository is ArchiMate architecture-as-code: one folder per **solution architecture (SA)** under
`models/<sa>/`, together forming the enterprise landscape. **Follow [AGENTS.md](../AGENTS.md)** for
every modelling task. The short version:

- Edit only YAML under `models/<sa>/` (and ADRs in `models/<sa>/decisions/`). `docs/` and `build/`
  are generated.
- Search all SAs before adding anything shared; reference another SA's element as `<sa>/<id>`
  (only ids in its `exports:`), and declare that relationship in the SA that uses it.
- Proposals and changes use `state: new | changed | retiring` on elements and relationships, plus the
  SA's `status` in `model.yaml`.
- Ground types and relationships with `python3 -m a4m types` and `python3 -m a4m allowed <Src> <Tgt>`
  (or the `a4m_*` MCP tools from `.vscode/mcp.json`).
- After every edit run `python3 -m a4m validate` and fix all errors using the hints, then
  `python3 -m a4m build`.
- Ids are kebab-case with a layer prefix (`bus-`, `app-`, `tech-`, `mot-`, `str-`, `phys-`, `impl-`, `oth-`).
- C4 diagrams are derived from `c4:` tags. Never write Mermaid or XML by hand.
