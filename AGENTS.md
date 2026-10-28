# AGENTS.md — modelling architecture in a4m

This repo is **architecture as code**. Each **solution architecture (SA)** is a folder of ArchiMate 3.2
YAML under `models/<sa>/`. SAs reference each other's elements, and together they make the
enterprise architecture (the *landscape*). Everything is validated against Archi's relationship rules
and rendered to Archi (Open Exchange XML) and Mermaid (flowchart + C4) docs. These instructions apply
to any assistant (GitHub Copilot, Claude, local models). Humans: see README.md.

## The loop (always)

1. **Understand** — read `docs/README.md` (all SAs and their dependencies), then
   `docs/<sa>/README.md` and the YAML files you will touch. `python3 -m a4m sas` lists the SAs.
2. **Search before you add** — anything shared (a platform, a network, a person, a business
   service) probably exists in another SA: `a4m_search` / `grep -r "name:" models/`. Reference it as
   `<sa>/<id>` instead of re-creating it (the validator warns about duplicates across SAs).
3. **Ground** — never guess types or relationships:
   - `python3 -m a4m types [--layer business|information|application|infrastructure]`
   - `python3 -m a4m allowed <SourceType> <TargetType>`
4. **Edit YAML** — add/change elements, relationships, views (formats below). Never edit
   `docs/` or `build/`; they are generated.
5. **Validate until clean** — `python3 -m a4m validate <sa>` (no argument = every SA). Fix *every*
   error using the hint in the message (it lists allowed alternatives / close matches / exports). Re-run.
   Then check `-w` warnings.
6. **Build** — `python3 -m a4m build` (all SAs + the landscape), then read the affected
   `docs/<sa>/<view>.md` to check the diagram says what you intended.
7. **Record decisions** — for a significant change, `python3 -m a4m new-adr <sa> "Title"`, fill it
   in, and list the affected ids under `affects:`.

If the MCP server is connected (`a4m` tools: `a4m_list_sas`, `a4m_search`, `a4m_get`, `a4m_types`,
`a4m_allowed`, `a4m_validate`, `a4m_impact`, `a4m_render_view`, `a4m_build`), use the tools instead of
the shell commands.

## Solution architectures

- One SA per folder: `models/<sa>/model.yaml` holds its metadata; the rest is model content.
  ```yaml
  name: Nextcloud
  kind: solution            # solution | platform (consumed by other SAs) | enterprise (goals, capabilities, org)
  status: implemented       # draft | proposed | approved | implemented | rejected
  owner: home lab admin
  documentation: One paragraph: what this SA is and why.
  exports: [app-nextcloud, app-nextcloud-db, data-files]   # ids other SAs may reference ("*" = all)
  ```
- **Every element has exactly one owner SA.** Other SAs reference it as `<sa>/<id>`, e.g.
  `source: compute/infra-docker`, in relationships, view `include:`/`scope:`, and ADR `affects:`.
  Only ids listed under the owner's `exports:` may be referenced. Export the *public surface*
  (systems, services, interfaces, shared nodes and networks), not internals.
- **The relationship lives in the SA that uses the other one** — the consumer declares
  `{ type: Serving, source: dns/app-svc-dns, target: app-nextcloud }`, even though the provider is the
  source. Providers never list their consumers; `python3 -m a4m impact <sa>[/<id>]` finds them.
- Shared things belong to a platform or the enterprise SA: business actors, roles and processes,
  goals, principles and capabilities live in `enterprise`; networks, hosts and shared runtimes live in
  platform SAs. A solution SA owns its own components, data, artifacts and dedicated VMs.
- An SA's docs show the other SAs' elements it uses or that use it (dashed, captioned with their SA;
  in C4 as external systems). The landscape (`docs/README.md`, `docs/_landscape/`) shows them all.

## Current and target state

An SA describes today **and** the proposed change in the same model. Every element and relationship
has a `state`:

| state | meaning |
|---|---|
| `existing` (default) | in the current state and the target state |
| `new` | proposed: only in the target state |
| `changed` | in both, but modified by this SA (say how in `documentation`) |
| `retiring` | only in the current state; removed by the target |

- A relationship must not outlive its ends: anything touching a `new` element is `new`; anything
  touching a `retiring` element is `retiring` (the validator says which to set).
- A new system: the whole SA is `new` items with `status: proposed`. A change to an existing system:
  mark only what is added/changed/removed.
- Views default to `state: change` (everything, changes highlighted; the docs add *Current state* and
  *Target state* diagrams). Set `state: baseline` or `state: target` on a view to pin one state.
- SA `status`: `proposed` → `approved` → (built) → `implemented`. An SA's changes count in the
  landscape's target state only once it is `approved`. When implemented: delete the retired items,
  set new ones to `existing`, set `status: implemented`.
- Retiring or changing an element other SAs use raises `consumer-impact` warnings in both SAs:
  check `python3 -m a4m impact <sa>/<id>` and coordinate.

## Files and ids

- Every SA has four **layer folders** (quasi-TOGAF, top to bottom). An element goes in the folder of
  its layer; the validator rejects it anywhere else (`layer-folder`) and names the right folder.

  | Folder | Id prefix | What goes in it (ArchiMate types) |
  |---|---|---|
  | `business/` | `bus-` | actors, roles, processes, functions, events, services, business objects, contracts; also the *why* and the roadmap: stakeholders, drivers, goals, principles, requirements, capabilities, resources, work packages, plateaus |
  | `information/` | `data-` | DataObject (the data an application stores or exchanges) |
  | `application/` | `app-` | application components, interfaces, functions, processes, events, services |
  | `infrastructure/` | `infra-` | nodes, devices, system software, networks, technology services, artifacts, physical equipment and facilities, locations |

  Junction and Grouping may go in any layer folder (no prefix). `python3 -m a4m types --layer <layer>`
  lists the types of a layer. Group files by system or topic (`application/nextcloud.yaml`).
  Relationships go next to the elements they mainly concern (or `relationships/*.yaml`).
  Views go in `views/`. ADRs in `decisions/` (numbered per SA).
- Ids are kebab-case, unique within the SA, **prefixed by layer**: `bus-` `data-` `app-` `infra-`.
  Within the prefix, use a short type hint where it helps: `bus-goal-…`, `bus-cap-…`, `app-svc-…`,
  `infra-art-…`, `infra-net-…`. Views: `view-…` (ArchiMate) / `c4-…` (C4). Ids are permanent — rename
  only with a search-and-replace across all SAs (`grep -r "<sa>/<id>" models/`) and ADRs.
- Relationship ids are optional (default `rel-<source>-<type>-<target>`). Only set one when the same
  type/source/target appears twice.

```yaml
elements:
  - id: app-nextcloud
    type: ApplicationComponent          # exact ArchiMate type (a4m types)
    name: Nextcloud
    c4: system                          # optional C4 tag, see below
    documentation: One or two sentences. The first sentence is used as the C4 description.
    properties: { technology: PHP 8, owner: admin }   # free-form; exported to Archi
  - { id: app-jellyfin, type: ApplicationComponent, name: Jellyfin, c4: system, state: new }
relationships:
  - { type: Serving, source: dns/app-svc-dns, target: app-nextcloud, name: DNS lookups }   # another SA's service
  - { type: Access, source: app-backup, target: nextcloud/data-files, access: read }   # access: read|write|readwrite|access
  - { type: Influence, source: bus-drv-privacy, target: bus-goal-reliable, modifier: "+" }
  - { type: Flow, source: app-backup, target: app-offsite-b2, state: retiring }
views:
  - id: view-layered
    name: Layered overview
    include: [compute/infra-nas]         # explicit ids (any SA) …
    include_layers: [information, application]   # … and/or whole layers: this SA's elements + other SAs' direct neighbours
    viewpoint: Layered                  # optional; only Archi viewpoint names
```

## ArchiMate cheat-sheet (direction = source → target)

| Pattern | Relationship |
|---|---|
| Actor plays role; role/actor performs process | BusinessActor –Assignment→ BusinessRole –Assignment→ BusinessProcess |
| Process delivers business service | BusinessProcess –Realization→ BusinessService |
| Component offers app service | ApplicationComponent –Realization→ ApplicationService |
| App service supports business | ApplicationService –Serving→ BusinessProcess / BusinessRole |
| Component is built of parts | ApplicationComponent –Composition→ ApplicationComponent |
| Data used by app | ApplicationComponent –Access→ DataObject (`access:`) |
| Data between apps | ApplicationComponent –Flow→ ApplicationComponent (`name:` what flows) |
| Node runs software | Node –Assignment→ SystemSoftware, Node –Composition→ Node (VMs) |
| Software deployed as artifact | SystemSoftware –Assignment→ Artifact –Realization→ ApplicationComponent |
| Infra offers tech service | Node/SystemSoftware –Realization→ TechnologyService –Serving→ Node / ApplicationComponent |
| Connected to a network | Node/Device –Association→ CommunicationNetwork |
| Why | Driver –Influence→ Goal; Requirement –Realization→ Goal; element –Realization→ Requirement |
| Capability | Capability –Composition→ Capability; BusinessService –Realization→ Capability |
| Change | WorkPackage –Realization→ Deliverable –Realization→ Plateau; Plateau –Triggering→ Plateau |

Common mistakes the validator will reject: Node –Assignment→ ApplicationComponent (use Realization,
or an Artifact), DataObject –Serving→ anything, Resource –Realization→ Capability (use Assignment).

## C4 (derived views)

C4 diagrams are **not drawn**; they are computed from `c4:` tags and the ArchiMate relationships.

| Tag | Allowed ArchiMate types | Rule |
|---|---|---|
| `person` | BusinessActor, BusinessRole | `external: true` → Person_Ext |
| `system` | ApplicationComponent, ApplicationCollaboration | `external: true` → System_Ext |
| `container` | ApplicationComponent | exactly one `system` –Composition/Aggregation→ it; `c4_shape: database\|queue` |
| `component` | ApplicationComponent | exactly one `container` –Composition/Aggregation→ it |
| `deployment` | Node, Device, SystemSoftware, TechnologyCollaboration, Facility, Equipment, Location | nested by Composition/Aggregation/Assignment |

- Arrows come from Serving (drawn as "Uses", reversed), Flow, Triggering and Access. Untagged services,
  interfaces, roles and processes in between are collapsed automatically, so keep modelling proper
  ArchiMate (component → service → process ← role ← actor) and the C4 arrow appears.
- Serving names read source→target in ArchiMate; C4 shows them as `Uses — <name>`. Override the C4
  text with `properties: { c4_label: "…" }` on the relationship.
- Put `properties: { technology: … }` on containers/components and on Flow relationships.
- Deployment: a container appears inside the deployment node that –Realization→ it, or that is
  –Assignment/Composition→ to an Artifact that –Realization→ it.
- Views: `{ id: c4-context, kind: c4-context, name: … }`, `{ kind: c4-container, scope: <system> }`,
  `{ kind: c4-component, scope: <container> }`, `{ kind: c4-deployment[, scope: <node>] }`.
- In an SA's C4 views its own systems sit in a boundary named after the SA; systems of other SAs
  are drawn as external systems, and a container appears inside another SA's node (e.g.
  `compute/infra-docker`) when its artifact is assigned there. The landscape C4 views group every
  system by SA inside the enterprise boundary.

Use **ArchiMate views** for cross-layer and enterprise questions (goals → infrastructure), **C4
views** for one software system.

## Review mode

When asked to review a model (or before finishing a large change) check and report findings graded
**Critical / Major / Minor / Suggestion**, each with the element ids and a concrete fix:

- Layering gaps: application components with no infrastructure realizing them; business services nobody
  realizes; application services that serve nothing.
- Motivation: goals with no requirement/principle/capability behind them; components realizing no
  requirement where one obviously applies.
- Resilience: single points of failure (one node hosting everything, single network path, no backup flow).
- Security & data: data objects without an owner/accessor; external systems receiving data without a
  named Flow.
- Cross-SA: elements re-created instead of referenced (`duplicate-across-sas`), internals that other
  SAs need but are not exported, platforms with many consumers and no resilience, retiring/changed
  elements still used elsewhere (`consumer-impact`, `a4m impact`).
- Change: `status` that does not match the content (proposed with nothing new; implemented with
  items still new/retiring), new systems without an ADR, target states with no work package.
- Hygiene: `validate -w` warnings, ids not following the prefix rule, missing documentation on
  systems/containers, decisions made without an ADR.

## Don'ts

- Don't write OEF/XML or Mermaid by hand — generate them.
- Don't invent element or relationship types, viewpoints or properties that change meaning silently.
- Don't use Association when a specific relationship is allowed (`a4m allowed` lists them).
- Don't delete elements referenced by ADRs without updating the ADR.
- Don't copy another SA's element into your SA; reference it (`<sa>/<id>`), and ask for it to be
  exported if it is not.
- Don't edit another SA's files to serve your change unless asked; propose it to its owner
  (an ADR, or `state: new` items in that SA if you were asked to model both).
- Don't commit with validation errors; CI will fail.
