from pathlib import Path

from fraudmesh.project import PROJECT_ROOT, phase_zero_summary


def test_project_root_exists() -> None:
    assert Path(PROJECT_ROOT).exists()


def test_phase_zero_summary() -> None:
    summary = phase_zero_summary()
    assert summary["project"] == "FraudMesh"
    assert "Phase 0" in summary["phase"]
