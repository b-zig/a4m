---
mode: agent
description: Record an architecture decision (ADR) linked to model elements
---
Record this decision for SA ${input:sa:nextcloud}: ${input:decision:what was decided and why}

1. Run `python3 -m a4m new-adr ${input:sa} "<short title>"`.
2. Fill in Context, Decision, Consequences. Set `status` (proposed/accepted).
3. Set `affects:` to the ids of the elements, relationships or views the decision concerns
   (use `a4m_search` to find them). If it replaces an older ADR, set `supersedes:` here and
   `status: superseded` + `superseded_by:` on the old one.
4. If the decision changes the architecture, update the YAML model too.
5. Validate and build.
