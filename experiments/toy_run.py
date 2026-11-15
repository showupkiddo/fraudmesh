from __future__ import annotations

import os

import mlflow

from fraudmesh.project import PROJECT_ROOT


def main() -> None:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", PROJECT_ROOT.joinpath("mlruns").as_uri()))
    mlflow.set_experiment("fraudmesh-phase0")

    with mlflow.start_run(run_name="phase0-toy") as run:
        mlflow.log_params({
            "phase": "0",
            "dataset": "fixture",
            "seed": 7,
            "device": "cpu",
        })
        mlflow.log_metric("toy_loss", 0.12, step=1)
        mlflow.log_metric("confidence", 0.9, step=1)
        mlflow.log_artifact(str(PROJECT_ROOT / "docs" / "PLAN.md"), artifact_path="docs")

    print(f"Run ID: {run.info.run_id}")
    print(f"Tracking URI: {mlflow.get_tracking_uri()}")


if __name__ == "__main__":
    main()
