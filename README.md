# FraudMesh

FraudMesh is a federated graph neural network framework for privacy-preserving detection of mule-account and money-laundering rings across institutions.

## Repository layout

- `data/` — raw and processed datasets, versioned by DVC
- `graph/` — graph construction, labels, split logic
- `models/` — baseline and custom model implementations
- `federated/` — Flower simulation and strategy code
- `privacy/` — DP and privacy-ledger utilities
- `serving/` — FastAPI service and model registry integration
- `console/` — React + TypeScript analyst console
- `infra/` — Docker Compose and deployment assets
- `experiments/` — Hydra configs and experiment runner scripts
- `docs/` — plan, ADRs, progress notes
- `tests/` — unit, boundary, and integration tests

## Quick start

```powershell
python -m pip install -e .[dev]
pytest -q
python experiments/toy_run.py
```

The toy run writes a local MLflow experiment in `mlruns/` under the project root and is intended to validate the tracking setup before real data work begins. The project is pinned to the current Windows development runtime in this session for immediate validation.

## Phase 0 and Phase 1 status

Phase 0 is complete: repository structure, CI, Python packaging, tracking, and a reproducible toy MLflow run are in place.

Phase 1 is in progress: the project now includes the canonical data schema, an initial dataset catalog, and a fixture dataset for CI and local validation while external dataset access remains pending.
