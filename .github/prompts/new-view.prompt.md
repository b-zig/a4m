---
mode: agent
description: Create an ArchiMate or C4 view in an a4m model
---
Create a view in SA ${input:sa:nextcloud} that answers: ${input:question:what should the view show?}

- Cross-layer / enterprise question → ArchiMate view (`include` ids and/or `include_layers`, optional `viewpoint`).
- One software system → C4 view (`kind: c4-context|c4-container|c4-component|c4-deployment`, `scope`).
  Make sure the needed elements carry `c4:` tags and the C4 parent rules in AGENTS.md hold.
Put it in `models/${input:sa}/views/`, validate, build, then show the rendered Mermaid from `docs/`.
