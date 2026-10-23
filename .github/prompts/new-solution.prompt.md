---
mode: agent
description: Create a new solution architecture (SA) that builds on the existing landscape
---
Create a solution architecture for: ${input:solution:what is being proposed, for whom, and why}

Follow AGENTS.md:
1. Read `docs/README.md` (the SAs and their dependencies) and run `python3 -m a4m sas`.
2. Pick a short kebab-case SA name and create `models/<sa>/model.yaml` with `name`, `kind: solution`,
   `status: proposed`, `owner`, `documentation` and `exports` (the systems/services others may use).
3. Model the solution in layer folders. Everything this SA adds is `state: new`.
4. Reuse, don't copy: reference the enterprise's actors, processes, goals and capabilities
   (`enterprise/<id>`) and the platforms it runs on (`compute/…`, `network/…`, `dns/…`) as `<sa>/<id>`.
   If something you need is not exported, say so in your summary.
5. Add `views/views.yaml` with an ArchiMate overview (`include_layers: [business, application, technology]`),
   a `c4-context` view, and a `c4-deployment` view if it is deployed on a platform.
6. Write `decisions/ADR-0001-…md` (`python3 -m a4m new-adr <sa> "…"`) with status proposed.
7. `python3 -m a4m validate` until clean, `python3 -m a4m build`, then show `docs/<sa>/README.md`
   and the C4 context diagram, and list the other SAs it depends on.
