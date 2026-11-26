from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import cast

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import numpy as np

from fraudmesh.graph_pipeline import (
    build_amlworld_graph,
    build_blind_spot_report,
    build_phase2_artefacts,
    build_ring_negative_report,
    chronological_split,
    derive_account_labels,
    partition_institutions,
    size_skewed_partition,
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


def test_phase2_ring_negatives_edge_features_and_variants(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    table = pa.table(
        {
            "transaction_id": ["t-1", "t-2", "t-3", "t-4", "t-5"],
            "timestamp": pa.array(
                [
                    datetime(2024, 1, 1, tzinfo=timezone.utc),
                    datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
                    datetime(2024, 1, 4, tzinfo=timezone.utc),
                    datetime(2024, 1, 4, 1, tzinfo=timezone.utc),
                    datetime(2024, 1, 6, tzinfo=timezone.utc),
                ],
                type=pa.timestamp("ns", tz="UTC"),
            ),
            "source_account": ["acct-a", "acct-b", "acct-c", "acct-d", "acct-a"],
            "destination_account": ["acct-b", "acct-c", "acct-d", "acct-a", "acct-e"],
            "source_institution": ["bank-a", "bank-b", "bank-c", "bank-d", "bank-a"],
            "destination_institution": ["bank-b", "bank-c", "bank-d", "bank-a", "bank-e"],
            "amount_inr": [10.0, 20.0, 30.0, 40.0, 50.0],
            "original_currency": ["INR", "INR", "INR", "INR", "INR"],
            "channel": ["ACH", "ACH", "ACH", "ACH", "ACH"],
            "edge_label": [0, 0, 0, 1, 0],
            "ring_id": [None, None, None, "ring-1", None],
            "typology": ["FAN-OUT", None, None, None, None],
        }
    )
    pq.write_table(table.take(pa.array([2, 0, 4, 1, 3])), canonical / "part.parquet")

    ring_report = build_ring_negative_report(
        [value.isoformat() for value in table["timestamp"].to_pylist()],
        table["source_account"].to_pylist(),
        table["destination_account"].to_pylist(),
        table["edge_label"].to_pylist(),
        table["ring_id"].to_pylist(),
    )
    assert cast(int, ring_report["positive_ring_count"]) == 1
    assert cast(int, ring_report["candidate_count"]) >= 1
    for candidate in cast(list[dict[str, object]], ring_report["candidates"]):
        for edge_index in cast(list[int], candidate["spanning_tree_edge_indices"]):
            assert table["edge_label"][edge_index].as_py() == 0

    skewed = size_skewed_partition(
        ["bank-a", "bank-b", "bank-c"],
        {"bank-a": 100, "bank-b": 2, "bank-c": 1},
        2,
    )
    assert skewed["bank-a"] == 0

    output = tmp_path / "phase2"
    result = build_phase2_artefacts(canonical, output)
    assert cast(int, result["rows"]) == 5
    assert set(cast(dict[str, object], result["variants"])) == {"k3", "k6", "k8"}
    assert (output / "edge_features.parquet").is_file()
    assert (output / "account_labels.parquet").is_file()
    assert (output / "ring_negatives.json").is_file()
    assert (output / "ring_labels.parquet").is_file()
    assert (output / "k6" / "neo4j" / "client-0-edges.csv").is_file()
    assert (output / "leakage_assertions.json").is_file()
    assert (output / "neutral_validation_edges.parquet").is_file()

    account_labels = pq.read_table(output / "account_labels.parquet").to_pylist()
    account_a = next(row for row in account_labels if row["account_id"] == "acct-a")
    assert account_a["account_label"] == 1
    assert account_a["account_label_train"] == 0
    assert account_a["account_label_validation"] == 1
    assert account_a["train_label_mask"] is True
    assert account_a["validation_label_mask"] is True

    edge_features = pq.read_table(output / "edge_features.parquet")
    t2_features = next(
        row for row in edge_features.to_pylist() if row["transaction_id"] == "t-2"
    )
    assert t2_features["source_count_1h"] == 1
    assert t2_features["source_sum_1h"] == 10.0
    assert t2_features["source_in_degree"] == 1
    assert t2_features["source_in_amount_inr"] == 10.0
    assert t2_features["time_of_day_cos"] < 1.0
    edge_feature_report = cast(dict[str, object], result["edge_features"])
    assert "edge_label" not in cast(list[str], edge_feature_report["feature_columns"])

    neutral_table = pq.read_table(output / "neutral_validation_edges.parquet")
    neutral_ids = set(neutral_table["transaction_id"].to_pylist())
    assert neutral_ids == {"t-3", "t-4"}
    assert all(neutral_table["validation_mask"].to_pylist())
    local_ids: set[str] = set()
    saw_stub = False
    for client_file in (output / "k3" / "balanced_local").glob("client-*.parquet"):
        local_edges = pq.read_table(client_file)
        local_ids.update(local_edges["transaction_id"].to_pylist())
        if local_edges.num_rows:
            assert not any(local_edges["validation_mask"].to_pylist())
            saw_stub |= any(
                node.startswith("stub:")
                for node in local_edges["source_node"].to_pylist()
                + local_edges["destination_node"].to_pylist()
            )
    assert local_ids == {"t-1", "t-2", "t-5"}
    assert saw_stub

    full_negative_report = json.loads((output / "ring_negatives.json").read_text())
    candidate_ids = {
        transaction_id
        for candidate in full_negative_report["candidates"]
        for transaction_id in candidate["spanning_tree_edge_transaction_ids"]
    }
    assert candidate_ids
    assert candidate_ids.isdisjoint({"t-4"})
    ring_labels = pq.read_table(output / "ring_labels.parquet").to_pylist()
    assert sum(row["ring_label"] == 1 for row in ring_labels) == 1
    assert any(row["ring_label"] == 0 for row in ring_labels)
    graph_arrays = output / "k6" / "balanced_local" / "client-0-pyg"
    edge_index = np.load(graph_arrays / "edge_index.npy")
    edge_labels = np.load(graph_arrays / "edge_labels.npy")
    assert isinstance(edge_index, np.ndarray)
    assert isinstance(edge_labels, np.ndarray)
    assert edge_index.shape[0] == 2
    assert edge_index.shape[1] == len(edge_labels)
    assert (graph_arrays / "metadata.json").is_file()
    assert pq.read_table(output / "edge_features.parquet")["transaction_id"].to_pylist() == [
        "t-1",
        "t-2",
        "t-3",
        "t-4",
        "t-5",
    ]
