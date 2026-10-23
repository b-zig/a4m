---
mode: agent
description: Add elements and relationships to a solution architecture
---
Add the following to solution architecture ${input:sa:nextcloud}: ${input:change:describe what to add}

Follow AGENTS.md:
1. Search **all** SAs first (`a4m_search` or `grep -r "name:" models/`). If it already exists in another
   SA, reference it as `<sa>/<id>` (ask for it to be exported if it is not) instead of re-creating it.
2. Check types with `python3 -m a4m types` and every relationship with `python3 -m a4m allowed`.
3. Put elements in the folder for their layer with the right id prefix; add `documentation`.
4. Connect the new elements up (motivation/business, usually in `enterprise/`) and down (technology,
   usually a platform SA) the layers.
5. If this is a proposal rather than today's reality, mark the new items `state: new` (and anything
   being replaced `state: retiring`).
6. Add them to the relevant view(s) in `views/`.
7. Run `python3 -m a4m validate` until there are no errors, then `python3 -m a4m build`.
8. Summarise what you added, which other SAs you now depend on, and which views changed.
