# FraudMesh progress log

## Phase 0 status

- Status: complete
- Current milestone: repository skeleton, Python packaging, CI workflow, MLflow tracking, DVC-ready structure, and initial ADR set are in place.
- Outcome: the Phase 0 gate report was produced and the project is ready to begin Phase 1.

## Phase 1 status

- Status: in progress / data schema and fixture foundation complete
- Current milestone: canonical transaction schema, validation layer, dataset catalog, and a small fixture dataset are now in place.
- Main focus: continue dataset-access work, document the canonical schema, and retain a reproducible fixture for CI while external data remains pending.

## Decisions taken

- Selected one monorepo with clearly separated runtime modules for data, graph, models, federated, privacy, serving, console, infra, experiments, docs, and tests.
- Set the compatibility baseline in `COMPATIBILITY.md` and kept the environment locked for the current development runtime.
- Chose a CPU-first fixture workflow for local development and a GPU-capable path only when real compute is explicitly available.
- Established a local MLflow tracking pattern using `mlruns/` and a Dockerised MLflow server for the project.
- Adopted a canonical transaction schema in the `fraudmesh.data` package so downstream adapters and graph builders can share one contract.

## Blockers

- Real dataset access (Kaggle/IEEE-CIS) is pending human approval and any required competition-rule acceptance.
- GPU access and DVC remote configuration still need explicit confirmation from the team.
- Full raw-data download and licence verification for P0/P1 sources are currently external dependencies.

## Next actions

1. Finalise the Phase 1 gate report and explicitly mark the external-data blockers.
2. Add the first DVC stage and canonical-data transformation pipeline once the raw downloads are available.
3. Prepare the graph construction package for AMLworld partitioning and the blind-spot table in Phase 2.

## Compute used

- Local CPU environment for scaffold validation, data-schema tests, and toy MLflow execution.
- No GPU workload launched yet.
