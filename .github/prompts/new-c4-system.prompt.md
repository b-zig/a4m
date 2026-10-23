---
mode: agent
description: Model a software system with C4 containers on top of ArchiMate
---
Model the software system "${input:system:name}" in SA ${input:sa:nextcloud}.

1. Create the system as an ApplicationComponent with `c4: system` (`external: true` if it's outside our control).
2. Create one ApplicationComponent per container with `c4: container`, `properties: { technology: … }`
   (and `c4_shape: database` for data stores), each composed by the system.
3. Model what it offers (ApplicationService + Realization) and who uses it (Serving to processes/roles/actors).
4. Model data flows between containers and to other systems with named Flow relationships.
5. Model deployment: Artifact(s) realizing containers, assigned to SystemSoftware/Node tagged `c4: deployment`.
6. Add a `c4-container` view scoped to the system; make sure the system is in the `c4-context` view.
7. Validate, build, and show `docs/${input:sa}/<view>.md`.
