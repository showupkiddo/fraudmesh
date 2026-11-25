from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from fraudmesh.graph_pipeline import (
    build_amlworld_graph,
    build_blind_spot_report,
    chronological_split,
    derive_account_labels,
    partition_institutions,
)


def test_phase2_account_labels_split_partition_and_blind_spot() -> None:
    labels = derive_account_labels(
        ["acct-a", "acct-b"],
        ["acct-b", "acct-c"],
        [1, 0],
    )
    assert labels == {"acct-a": 1, "acct-b": 1, "acct-c": 0}

    split = chronological_split(
        ["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-04", "2024-01-05"],
    )
    assert split == ["train", "train", "train", "validation", "test"]

    partition = partition_institutions(["bank-c", "bank-a", "bank-b", "bank-a"], 2)
    assert partition == {"bank-a": 0, "bank-b": 1, "bank-c": 0}

    report = build_blind_spot_report(
        ["bank-a", "bank-b"],
        ["bank-b", "bank-c"],
        ["ring-1", None],
        partition,
    )
    assert report["ring_count"] == 1
    assert report["cross_institution_edges"] == 2


def test_build_amlworld_graph_fixture(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    table = pa.table(
        {
            "timestamp": pa.array(
                [
                    datetime(2024, 1, 1, tzinfo=timezone.utc),
                    datetime(2024, 1, 2, tzinfo=timezone.utc),
                    datetime(2024, 1, 3, tzinfo=timezone.utc),
                ],
                type=pa.timestamp("ns", tz="UTC"),
            ),
            "source_account": ["acct-a", "acct-b", "acct-c"],
            "destination_account": ["acct-b", "acct-c", "acct-a"],
            "source_institution": ["bank-a", "bank-b", "bank-c"],
            "destination_institution": ["bank-b", "bank-c", "bank-a"],
            "edge_label": [1, 0, 1],
            "ring_id": ["ring-1", None, "ring-1"],
        }
    )
    pq.write_table(table, canonical / "part.parquet")
    output = tmp_path / "graph"

    result = build_amlworld_graph(canonical, output, client_count=3)

    assert result["rows"] == 3
    assert result["institutions"] == 3
    assert result["positive_accounts"] == 3
    assert json.loads((output / "blind_spot_report.json").read_text())["ring_count"] == 1
    assert ds.dataset(canonical, format="parquet").to_table().num_rows == 3
