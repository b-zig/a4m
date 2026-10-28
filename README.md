# a4m — ArchiMate architecture as code

Architecture as **YAML in git**: one folder per **solution architecture (SA)**, each organised in
four layers (**business, information, application, infrastructure**). SAs reference each other's
elements, and together they make the **enterprise landscape**. Everything is checked against the
**ArchiMate 3.2 rules Archi itself uses** and rendered to **Archi** (Open Exchange XML) and to
**Mermaid** docs (ArchiMate-style flowcharts and **C4** diagrams) that GitHub and VS Code display
natively. Each SA shows its **current and target state**. Built to be driven by an LLM (Claude Code,
GitHub Copilot, or a local model) through a validate-and-fix loop.

```
 models/<sa>/<layer>/*.yaml ──► a4m validate ──► a4m build ──┬─► build/<sa>.oef.xml, build/_landscape.oef.xml ──► Archi
   ▲  (LLM or human edits)       schema · layer folders      │
   │                             ArchiMate rules · C4 · ADRs ├─► docs/<sa>/*.md   (Mermaid flowchart + C4, changes, ADRs)
   │                             cross-SA refs · exports     └─► docs/README.md, docs/_landscape/  (all SAs, dependencies,
   │                             change states                   system landscape, deployment, platform consumers)
   └──── a4m import-oef ◄── Archi (File ▸ Export ▸ Model to Open Exchange File)
```

## Quick start

Requirements: Python ≥ 3.10 with `pyyaml` and `jsonschema` (`pip install pyyaml jsonschema`).
Optional: [Archi](https://www.archimatetool.com/) 5.x for the rich viewer/editor, and Node ≥ 20 for
the Mermaid syntax check.

```bash
python3 -m a4m sas                    # the solution architectures, their status and dependencies
python3 -m a4m validate -w            # check every SA (or: validate nextcloud)
python3 -m a4m build                  # → build/*.oef.xml + docs/ (every SA and the landscape)
python3 -m a4m impact dns/app-svc-dns # who depends on this element
python3 -m a4m types --layer application
python3 -m a4m allowed Node ApplicationComponent
python3 -m a4m mermaid backup c4-context --state target
python3 -m unittest discover -s tests -t .
```

Then open [docs/README.md](docs/README.md), or import `build/_landscape.oef.xml` (everything) or
`build/<sa>.oef.xml` (one SA) into Archi.

The sample is a home lab modelled as eight SAs:

| SA | Kind | Shows |
|---|---|---|
| `enterprise` | enterprise | goals, principles, capabilities, the family and admin, the office roadmap |
| `network`, `compute`, `dns` | platform | router/VLANs/rack/UPS; Proxmox, Docker VM and NAS; Pi-hole — used by the others |
| `nextcloud`, `home-automation` | solution | implemented systems on the platforms |
| `backup` | solution, *approved* | a change in flight: Backblaze B2 retiring, Hetzner Storage Box new |
| `media` | solution, *proposed* | a new system (Jellyfin) that is not approved yet |

## Structure: solution architectures in four layers

Every solution architecture is a folder under `models/`, and every SA has the same four layer folders,
quasi-TOGAF, top to bottom:

```
models/
├── enterprise/                 # one SA per folder
├── compute/
└── nextcloud/
    ├── model.yaml              # name, kind, status, owner, exports
    ├── business/               # bus-
    ├── information/            # data-
    ├── application/            # app-
    ├── infrastructure/         # infra-
    ├── views/                  # ArchiMate and C4 views
    └── decisions/              # ADRs (ADR-0001-….md)
```

| Layer folder | Id prefix | What goes in it |
|---|---|---|
| `business/` | `bus-` | Actors, roles, processes, functions, events, business services, business objects, contracts. Also *why* and *when*: stakeholders, drivers, goals, principles, requirements, capabilities, resources, work packages, plateaus |
| `information/` | `data-` | Data objects: the data an application stores or exchanges |
| `application/` | `app-` | Application components, interfaces, functions, processes, events, application services |
| `infrastructure/` | `infra-` | Nodes, devices, system software, networks, technology services, artifacts, physical equipment and facilities, locations |

- **Every ArchiMate type belongs to exactly one layer.** The mapping is one table in
  `rules/elements.yaml`; `python3 -m a4m types --layer <layer>` lists it. ArchiMate's own motivation,
  strategy and implementation & migration layers are folded into Business, and physical elements into
  Infrastructure. Junction and Grouping may go in any layer folder.
- **The validator enforces it.** An element in the wrong folder (or at the SA root) is an error that
  names the right place, e.g. `DataObject belongs to the information layer; move it to
  models/nextcloud/information/ (it is in application/)`.
- **Inside a layer folder, files are free-form**: group by system or topic (`application/nextcloud.yaml`).
  Relationships sit next to the elements they mainly concern.
- **Diagrams use the same layers**: ArchiMate views in Mermaid and Archi show Business → Information →
  Application → Infrastructure as horizontal bands.
- Not every SA needs every layer: a platform SA may only have `infrastructure/`, the enterprise SA
  mostly `business/`.

## Repository layout

| Path | What |
|---|---|
| `models/<sa>/` | The source of truth, one folder per solution architecture (see [Structure](#structure-solution-architectures-in-four-layers)) |
| `rules/archimate-3.2/` | Archi's relationship matrix, vendored unmodified (MIT), see NOTICE |
| `rules/elements.yaml` | Element catalogue: the four layers (folder, id prefix, colour), which layer each ArchiMate type belongs to; viewpoint names |
| `rules/c4.yaml` | C4 ↔ ArchiMate mapping used to derive C4 views |
| `schema/a4m.schema.json` | JSON Schema for model files (editor validation, LLM structured output) |
| `a4m/` | The tool (stdlib + PyYAML + jsonschema) |
| `docs/` | **Generated** Markdown + Mermaid (committed so GitHub renders it): `README.md` + `_landscape/` for the enterprise, `<sa>/` per SA |
| `build/` | **Generated** OEF for Archi (git-ignored; CI uploads it as an artifact) |
| `AGENTS.md` | Modelling rules for any LLM, the canonical guide for contributors too |
| `.github/` | Copilot instructions, prompt files, CI workflow |
| `.mcp.json`, `.vscode/mcp.json` | MCP server registration for Claude Code / VS Code Copilot |

## Commands

| Command | Purpose |
|---|---|
| `validate [sa] [-w] [--format json]` | One SA or all: schema, layer folders, unique ids, dangling refs, ArchiMate relationship rules (with allowed alternatives), cross-SA references and exports, change-state consistency, C4 tag/parent rules, view refs, ADR links; warnings for orphans, unviewed elements, id prefixes, duplicates across SAs, consumers hit by a change |
| `build [sa]` | Validate, then write the OEF and the docs of one SA (or all) and the landscape; prunes stale generated pages |
| `sas` | List SAs: kind, status, number of changes, exports, uses / used by |
| `impact <sa>[/<id>]` | Relationships (and ADRs) in other SAs that depend on an SA or one of its elements |
| `types [--layer L]` / `allowed Src Tgt` | Ground the LLM in the real element types (per layer, with folder and id prefix) and relationship rules |
| `mermaid sa view [--state …]` | Print one view (change, baseline or target) |
| `import-oef file.xml sa` | Bring Archi edits back into YAML (see round-trip below) |
| `new-adr sa "Title"` | Next numbered ADR of that SA from the template |
| `schema [--write]` | Print/regenerate the JSON Schema |
| `mcp` | MCP server on stdio |

## Modelling in one minute

An SA's metadata, then elements and relationships in the layer folders (see [Structure](#structure-solution-architectures-in-four-layers)):

```yaml
# models/nextcloud/model.yaml
name: Nextcloud
kind: solution                        # solution | platform | enterprise
status: implemented                   # draft | proposed | approved | implemented | rejected
exports: [app-nextcloud, app-nextcloud-db, data-files]   # what other SAs may reference
```

```yaml
# models/nextcloud/application/nextcloud.yaml
elements:
  - id: app-nextcloud                 # kebab-case, layer prefix (bus- data- app- infra-)
    type: ApplicationComponent
    name: Nextcloud
    c4: system                        # opt into C4 views
  - id: app-nextcloud-db
    type: ApplicationComponent
    name: Nextcloud database
    c4: container
    c4_shape: database
    properties: { technology: MariaDB 11 }
relationships:
  - { type: Composition, source: app-nextcloud, target: app-nextcloud-db }
  - { type: Flow, source: app-nextcloud-web, target: app-nextcloud-db, name: Reads/writes metadata }
  - { type: Serving, source: dns/app-svc-dns, target: app-nextcloud, name: DNS lookups }   # another SA's service
```

Views are either ArchiMate views (`include:` ids and/or `include_layers: [business, information,
application, infrastructure]`), laid out in the four layer bands, or C4 views (`kind: c4-context | c4-container | c4-component | c4-deployment`, `scope:`),
**derived** from `c4:` tags and the ArchiMate relationships. Untagged services, interfaces, roles and
processes are collapsed, and nested elements roll up to the level shown. See [AGENTS.md](AGENTS.md) for
the full rules and a cheat-sheet.

## Solution architectures and the landscape

- **One owner per element.** Other SAs reference it as `<sa>/<id>`, and only what the owner lists
  under `exports:`. The relationship lives in the SA that uses the other one, so a platform never
  lists its consumers. `a4m impact` and `docs/_landscape/consumers.md` find them.
- **Kinds.** `enterprise` holds what no single solution owns (goals, principles, capabilities, people,
  processes). `platform` SAs are consumed by others (networks, hosting, shared services). `solution`
  SAs deliver systems.
- **Per-SA docs** show the other SAs' elements the SA uses or is used by: dashed and captioned in
  flowcharts, as external systems in C4. A container deployed on another SA's node appears inside it.
- **The landscape is generated**:
  - `docs/README.md` has the SA table (kind, status, changes, uses, used by) and a dependency map;
  - `docs/_landscape/` has the C4 system landscape grouped by SA, deployment across all SAs, and platform consumers;
  - `build/_landscape.oef.xml` holds every SA and all their views in one Archi model.
- **Checks across SAs**: unknown SA or id (with close matches), references to internals that aren't
  exported (it lists the exports), the same element defined in two SAs, relationships between two
  other SAs, and consumers affected when an exported element is retired.

## Current and target state

Every element and relationship has `state: existing | new | changed | retiring` (default `existing`).

- An SA that proposes a new system marks its items `new`. A change to an existing system marks only
  what is added, changed or removed.
- Views render the **change**, with new items in green, changed in orange and retiring in red. Each
  page also adds the **Current state** and **Target state** diagrams.
- In Archi, each view with changes gets `… (current state)` and `… (target state)` copies.
- In the landscape, an SA's changes count towards the target only when the SA is `approved` (or
  `implemented`). Proposals show in purple until then.

## Working with an LLM

- **Claude Code**: `CLAUDE.md` includes `AGENTS.md`; `.mcp.json` registers the `a4m` MCP server.
- **GitHub Copilot (VS Code)**: `.github/copilot-instructions.md` and prompt files in `.github/prompts/`
  (`/new-solution`, `/new-element`, `/new-view`, `/new-c4-system`, `/new-adr`, `/review-model`); agent mode can run the CLI,
  and `.vscode/mcp.json` exposes the MCP tools. The Copilot coding agent also reads `AGENTS.md`.
- **Local models**: give the model `AGENTS.md` and `python3 -m a4m schema` as the structured-output
  schema, then pipe the result through `validate`.

The loop is always: search all SAs → ground (`types`/`allowed`) → edit YAML → `validate` until clean →
`build` → read the generated view.

## Archi round-trip

1. `python3 -m a4m build` → *File ▸ Import ▸ Open Exchange XML Model* → `build/<sa>.oef.xml` (one SA) or
   `build/_landscape.oef.xml` (all SAs; read-only overview).
   - Views arrive laid out in the four layer bands (Business, Information, Application, Infrastructure).
   - `c4` tags, `state` and the owning SA appear as `a4m:*` properties.
   - Other SAs' ids are written as `<sa>.<id>`.
2. Edit one SA's model in Archi if you like, then *File ▸ Export ▸ Model to Open Exchange File*.
3. `python3 -m a4m import-oef exported.xml <sa>` → review `git diff` → `validate`.

Import keeps ids that are valid a4m ids, renames Archi-generated `id-<uuid>` ids to `<prefix>-<name>`,
keeps each concept in the file it came from (new ones go to `<layer folder>/imported.yaml`, e.g. `application/imported.yaml`), keeps C4 view
definitions, and stores node positions as `layout:` only when you moved something.

Some things don't come back:
- **Other SAs' content.** Elements and relationships owned by another SA are never written; references to them stay `<sa>/<id>`.
- **Generated copies.** The `--baseline`/`--target` view copies are skipped.
- **Comments.** YAML comments in rewritten files are lost.
- **Archi drawing details.** Layer bands (groups) and bendpoints drawn in Archi are not imported.

## Porting to the office

One repository is one organisation's landscape, and `models/` holds its SAs.

1. Clone the repo on the office network. It needs only Python 3.10+, PyYAML and jsonschema, plus Archi if you want it.
2. Replace the home lab SAs with the office's own:
   - start with an `enterprise` SA (goals, capabilities, departments);
   - add the shared platforms (for example, the Enterprise Data Fabric on Kafka, networks, identity) with their `exports`;
   - add one folder per solution architecture, with the four layer folders inside.

   Keep a home lab SA or two as worked examples if useful.
3. Use the same CI (`.github/workflows/validate.yml`). It validates and builds every SA under `models/`.
4. Windows: use `py -m a4m …` / `python -m a4m …`; change `"command": "python3"` in `.vscode/mcp.json` if needed.
5. Access control: add a `CODEOWNERS` entry per `models/<sa>/` folder when SAs get owners.

## CI

`.github/workflows/validate.yml` runs the unit tests, validates and builds every SA, fails if the
committed `docs/` are stale, parses every Mermaid block with Mermaid 11 (`tools/check-mermaid.mjs`),
and uploads the OEF files as an artifact. Optional XSD check locally:
`pip install xmlschema` + `A4M_XSD=path/to/archimate3_Diagram.xsd python3 -m unittest tests.test_oef`
(XSDs from <https://www.opengroup.org/xsd/archimate/3.1/>).

## Updating the ArchiMate rules

`make rules-refresh` re-downloads Archi's `relationships.xml` and runs the tests. The rules live in a
versioned folder (`rules/archimate-3.2/`) so a future ArchiMate version can sit next to it.

## Credits / prior art

Relationship matrix from [Archi](https://github.com/archimatetool/archi) (MIT). Ideas borrowed from
[archimate-mcp](https://github.com/thijs-hakkenberg/archimate-mcp) (reject invalid relationships with
alternatives), [enterprise-architecture-skill](https://github.com/gauravs19/enterprise-architecture-skill)
(C4 + ArchiMate at different altitudes, ADR linking, review rubric) and the
[C4 model](https://c4model.com/).
