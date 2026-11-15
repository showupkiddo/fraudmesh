from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def phase_zero_summary() -> dict[str, str]:
    return {
        "project": "FraudMesh",
        "phase": "Phase 0: Foundation and engineering setup",
        "status": "scaffolded",
        "root": str(PROJECT_ROOT),
    }
