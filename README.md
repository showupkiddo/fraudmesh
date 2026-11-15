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
python -m pip install -e .[dev,data]
python -m pytest -q
python experiments/toy_run.py
```

The toy run writes a local MLflow experiment in `mlruns/` under the project root and is intended to validate the tracking setup before real data work begins. The project is pinned to the current Windows development runtime in this session for immediate validation.

Rebuild the canonical fixture with DVC:

```powershell
python -m dvc repro phase1-fixture-canonical
```

## Phase 0 and Phase 1 status

Phase 0 is complete: repository structure, CI, Python packaging, tracking, and a reproducible toy MLflow run are in place.

Phase 1 remains blocked at its real-data gate: the canonical monetary field is INR-only, reviewed period FX rates are recorded, and AMLworld pattern rows were matched against both Small source files. IEEE-CIS files are now present locally, but full canonicalization, validation, EDA, and a clean-machine DVC rebuild are still incomplete; see `docs/PROGRESS.md`.
