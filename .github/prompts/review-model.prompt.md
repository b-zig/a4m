---
mode: agent
description: Review a solution architecture (or the whole landscape) against the AGENTS.md rubric
---
Review solution architecture ${input:sa:nextcloud} (or "all" for the landscape).

1. Run `python3 -m a4m validate ${input:sa} -w` (no SA for all) and read `docs/${input:sa}/README.md`
   (or `docs/README.md`) and the views.
2. Run `python3 -m a4m impact ${input:sa}` to see who depends on it.
3. Apply the **Review mode** rubric from AGENTS.md, including the cross-SA and change checks.
4. Report findings as a table: Severity (Critical/Major/Minor/Suggestion) | Finding | Element ids | Suggested fix.
5. Finish with a verdict: is the model fit to drive decisions, and the top 3 fixes.
Do not change files unless asked.
