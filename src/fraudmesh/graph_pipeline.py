from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.dataset as ds


def chronological_split(
    timestamps: list[str],
    *,
    train_ratio: float = 0.6,
    validation_ratio: float = 0.2,
) -> list[str]:
    if not 0 < train_ratio < 1 or train_ratio + validation_ratio >= 1:
        raise ValueError("invalid chronological split ratios")
    indices = sorted(range(len(timestamps)), key=timestamps.__getitem__)
    train_end = int(len(indices) * train_ratio)
    validation_end = int(len(indices) * (train_ratio + validation_ratio))
    labels = ["test"] * len(timestamps)
    for position, index in enumerate(indices):
        if position < train_end:
            labels[index] = "train"
        elif position < validation_end:
            labels[index] = "validation"
    return labels


def derive_account_labels(
    source_accounts: list[str],
    destination_accounts: list[str],
    edge_labels: list[int],
) -> dict[str, int]:
    if not (len(source_accounts) == len(destination_accounts) == len(edge_labels)):
        raise ValueError("account-label inputs must have equal lengths")
    labels: dict[str, int] = {}
    for source, destination, label in zip(source_accounts, destination_accounts, edge_labels):
        for account in (source, destination):
            labels[account] = max(labels.get(account, 0), int(label))
    return labels


def partition_institutions(institutions: list[str], client_count: int) -> dict[str, int]:
    if client_count < 1:
        raise ValueError("client_count must be positive")
    unique = sorted(set(institutions))
    if not unique:
        raise ValueError("at least one institution is required")
    return {institution: index % client_count for index, institution in enumerate(unique)}


def build_blind_spot_report(
    source_institutions: list[str],
    destination_institutions: list[str],
    ring_ids: list[str | None],
    institution_to_client: dict[str, int],
) -> dict[str, object]:
    if not (len(source_institutions) == len(destination_institutions) == len(ring_ids)):
        raise ValueError("blind-spot inputs must have equal lengths")

    client_edges: dict[int, int] = {client: 0 for client in set(institution_to_client.values())}
    cross_institution_edges = 0
    for source, destination, ring_id in zip(
        source_institutions,
        destination_institutions,
        ring_ids,
    ):
        source_client = institution_to_client.get(source)
        destination_client = institution_to_client.get(destination)
        if source_client is not None:
            client_edges[source_client] += 1
        if destination_client is not None:
            client_edges[destination_client] += 1
        if source != destination:
            cross_institution_edges += 1

    return {
        "client_edges": client_edges,
        "cross_institution_edges": cross_institution_edges,
        "ring_count": len({ring_id for ring_id in ring_ids if ring_id}),
    }


def build_amlworld_graph(
    canonical_dir: str | Path,
    output_dir: str | Path,
    *,
    client_count: int = 6,
) -> dict[str, object]:
    canonical = ds.dataset(Path(canonical_dir), format="parquet", partitioning="hive").to_table()
    required = {
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "edge_label",
        "ring_id",
    }
    missing = required.difference(canonical.column_names)
    if missing:
        raise ValueError(f"canonical graph input is missing columns: {sorted(missing)}")

    source_accounts = canonical["source_account"].to_pylist()
    destination_accounts = canonical["destination_account"].to_pylist()
    edge_labels = canonical["edge_label"].to_pylist()
    source_institutions = canonical["source_institution"].to_pylist()
    destination_institutions = canonical["destination_institution"].to_pylist()
    ring_ids = canonical["ring_id"].to_pylist()
    timestamps = [value.isoformat() for value in canonical["timestamp"].to_pylist()]

    institutions = sorted(set(source_institutions) | set(destination_institutions))
    institution_to_client = partition_institutions(institutions, client_count)
    account_labels = derive_account_labels(source_accounts, destination_accounts, edge_labels)
    split_labels = chronological_split(timestamps)
    blind_spot = build_blind_spot_report(
        source_institutions,
        destination_institutions,
        ring_ids,
        institution_to_client,
    )

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "institution_partition.json").write_text(
        json.dumps(institution_to_client, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "blind_spot_report.json").write_text(
        json.dumps(blind_spot, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "chronological_split.json").write_text(
        json.dumps(
            {
                "train": split_labels.count("train"),
                "validation": split_labels.count("validation"),
                "test": split_labels.count("test"),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    positive_accounts = sum(account_labels.values())
    return {
        "rows": canonical.num_rows,
        "institutions": len(institutions),
        "clients": client_count,
        "positive_accounts": positive_accounts,
        "blind_spot": blind_spot,
        "split_counts": {
            "train": split_labels.count("train"),
            "validation": split_labels.count("validation"),
            "test": split_labels.count("test"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build initial Phase 2 AMLworld graph artefacts.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--client-count", type=int, default=6)
    args = parser.parse_args()
    print(json.dumps(build_amlworld_graph(args.input_dir, args.output_dir, client_count=args.client_count), sort_keys=True))


if __name__ == "__main__":
    main()
