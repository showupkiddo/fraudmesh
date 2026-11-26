from __future__ import annotations

import argparse
import csv
import heapq
import json
from pathlib import Path
from collections import Counter, defaultdict
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import tempfile
from typing import cast

import pyarrow.dataset as ds
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import numpy as np


@dataclass
class _AccountHistory:
    windows: dict[int, deque[tuple[datetime, float]]] = field(
        default_factory=lambda: {
            3600: deque(),
            86400: deque(),
            604800: deque(),
        }
    )
    sums: dict[int, float] = field(default_factory=lambda: {3600: 0.0, 86400: 0.0, 604800: 0.0})
    last_timestamp: datetime | None = None
    outgoing_degree: int = 0
    incoming_degree: int = 0
    outgoing_amount: float = 0.0
    incoming_amount: float = 0.0

    def features(self, timestamp: datetime) -> tuple[float, float, float, float, float, float, float]:
        if self.last_timestamp is not None and self.last_timestamp > timestamp:
            raise ValueError("account history contains an event at or after the current edge")
        for seconds, events in self.windows.items():
            cutoff = timestamp - timedelta(seconds=seconds)
            while events and events[0][0] < cutoff:
                _, amount = events.popleft()
                self.sums[seconds] -= amount
        since = (
            (timestamp - self.last_timestamp).total_seconds()
            if self.last_timestamp is not None
            else 0.0
        )
        return (
            since,
            float(len(self.windows[3600])),
            self.sums[3600],
            float(len(self.windows[86400])),
            self.sums[86400],
            float(len(self.windows[604800])),
            self.sums[604800],
        )

    def degree_features(self) -> tuple[int, int, float, float]:
        return (
            self.outgoing_degree,
            self.incoming_degree,
            self.outgoing_amount,
            self.incoming_amount,
        )

    def record(
        self,
        timestamp: datetime,
        amount: float,
        *,
        outgoing: bool,
        incoming: bool,
    ) -> None:
        for seconds, events in self.windows.items():
            events.append((timestamp, amount))
            self.sums[seconds] += amount
        self.last_timestamp = timestamp
        if outgoing:
            self.outgoing_degree += 1
            self.outgoing_amount += amount
        if incoming:
            self.incoming_degree += 1
            self.incoming_amount += amount


def _timestamp_value(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _write_timestamp_sorted_parquet(
    dataset: ds.Dataset,
    output_path: Path,
    columns: list[str],
    *,
    batch_size: int = 50_000,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([dataset.schema.field(column) for column in columns])
    with tempfile.TemporaryDirectory(prefix="fraudmesh-sort-") as temporary_dir:
        runs: list[Path] = []
        for index, batch in enumerate(
            dataset.scanner(columns=columns, batch_size=batch_size).to_batches()
        ):
            table = pa.Table.from_batches([batch])
            ordered = pc.take(
                table,
                pc.sort_indices(table, sort_keys=[("timestamp", "ascending")]),
            )
            run_path = Path(temporary_dir) / f"run-{index:05d}.parquet"
            pq.write_table(ordered, run_path, compression="zstd")
            runs.append(run_path)
        if not runs:
            raise ValueError("canonical Phase 2 input is empty")

        iterators = [
            iter(pq.ParquetFile(run_path).iter_batches(batch_size=2_048))
            for run_path in runs
        ]
        batches: list[dict[str, list[object]] | None] = [None] * len(runs)
        row_indexes = [0] * len(runs)
        heap: list[tuple[datetime, int]] = []
        for run_index, iterator in enumerate(iterators):
            batch = next(iterator, None)
            if batch is not None:
                run_rows = batch.to_pydict()
                batches[run_index] = run_rows
                heapq.heappush(
                    heap,
                    (_timestamp_value(run_rows["timestamp"][0]), run_index),
                )

        writer: pq.ParquetWriter | None = None
        buffer: dict[str, list[object]] = {column: [] for column in columns}

        def flush() -> None:
            nonlocal writer
            if not buffer["timestamp"]:
                return
            table = pa.Table.from_pydict(buffer, schema=schema)
            if writer is None:
                writer = pq.ParquetWriter(output_path, schema, compression="zstd")
            writer.write_table(table)
            for values in buffer.values():
                values.clear()

        try:
            while heap:
                _, run_index = heapq.heappop(heap)
                run_batch = batches[run_index]
                if run_batch is None:
                    raise AssertionError("sorted run is unexpectedly empty")
                row_index = row_indexes[run_index]
                for column in columns:
                    buffer[column].append(run_batch[column][row_index])
                row_index += 1
                if row_index == len(run_batch["timestamp"]):
                    next_batch = next(iterators[run_index], None)
                    if next_batch is None:
                        batches[run_index] = None
                    else:
                        batches[run_index] = next_batch.to_pydict()
                        row_index = 0
                if batches[run_index] is not None:
                    row_indexes[run_index] = row_index
                    next_rows = batches[run_index]
                    if next_rows is None:
                        raise AssertionError("sorted run failed to load its next batch")
                    heapq.heappush(
                        heap,
                        (
                            _timestamp_value(next_rows["timestamp"][row_index]),
                            run_index,
                        ),
                    )
                else:
                    row_indexes[run_index] = 0
                if len(buffer["timestamp"]) >= batch_size:
                    flush()
            flush()
        finally:
            if writer is not None:
                writer.close()


def balanced_partition(institutions: list[str], client_count: int) -> dict[str, int]:
    unique = sorted(set(institutions))
    if client_count < 1:
        raise ValueError("client_count must be positive")
    return {institution: index % client_count for index, institution in enumerate(unique)}


def size_skewed_partition(
    institutions: list[str],
    institution_edge_counts: dict[str, int],
    client_count: int,
) -> dict[str, int]:
    if client_count < 1:
        raise ValueError("client_count must be positive")
    ranked = sorted(set(institutions), key=lambda item: (-institution_edge_counts.get(item, 0), item))
    assignment: dict[str, int] = {}
    client_totals = [0] * client_count
    for institution in ranked:
        client = min(range(client_count), key=lambda index: (client_totals[index], index))
        assignment[institution] = client
        client_totals[client] += institution_edge_counts.get(institution, 0)
    return assignment


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
    for source, destination in zip(source_institutions, destination_institutions):
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


def build_ring_negative_report(
    timestamps: list[str],
    source_accounts: list[str],
    destination_accounts: list[str],
    edge_labels: list[int],
    ring_ids: list[str | None],
    *,
    window_hours: int = 24,
) -> dict[str, object]:
    if not (len(timestamps) == len(source_accounts) == len(destination_accounts) == len(edge_labels) == len(ring_ids)):
        raise ValueError("ring-negative inputs must have equal lengths")

    positive_accounts: dict[str, set[str]] = defaultdict(set)
    for source, destination, ring_id in zip(source_accounts, destination_accounts, ring_ids):
        if ring_id:
            positive_accounts[ring_id].update((source, destination))
    target_sizes = Counter(len(accounts) for accounts in positive_accounts.values())
    max_size = max(target_sizes, default=0)

    buckets: dict[int, list[tuple[str, str, str, int]]] = defaultdict(list)
    for edge_index, (timestamp, source, destination, label) in enumerate(
        zip(timestamps, source_accounts, destination_accounts, edge_labels)
    ):
        if int(label) == 1:
            continue
        parsed = _timestamp_value(timestamp)
        bucket = int(parsed.timestamp() // timedelta(hours=window_hours).total_seconds())
        buckets[bucket].append((source, destination, parsed.strftime("%Y-%m-%d"), edge_index))

    candidates: list[dict[str, object]] = []
    for bucket, edges in sorted(buckets.items()):
        parent: dict[str, str] = {}
        component_size: dict[str, int] = {}
        component_edges: dict[str, int] = {}
        spanning_tree_edges: dict[str, list[int]] = {}

        def find(account: str) -> str:
            parent.setdefault(account, account)
            component_size.setdefault(account, 1)
            component_edges.setdefault(account, 0)
            spanning_tree_edges.setdefault(account, [])
            while parent[account] != account:
                parent[account] = parent[parent[account]]
                account = parent[account]
            return account

        day = edges[0][2]
        for source, destination, _, edge_index in edges:
            source_root = find(source)
            destination_root = find(destination)
            if source_root == destination_root:
                component_edges[source_root] += 1
                continue
            combined_size = component_size[source_root] + component_size[destination_root]
            if max_size and combined_size > max_size:
                continue
            parent[destination_root] = source_root
            component_size[source_root] = combined_size
            component_edges[source_root] += component_edges[destination_root] + 1
            spanning_tree_edges[source_root].extend(spanning_tree_edges[destination_root])
            spanning_tree_edges[source_root].append(edge_index)
        emitted_sizes: Counter[int] = Counter()
        for root, size in component_size.items():
            if parent[root] != root or size not in target_sizes:
                continue
            if emitted_sizes[size] >= target_sizes[size]:
                continue
            emitted_sizes[size] += 1
            candidates.append(
                {
                    "candidate_id": f"negative-{bucket:08d}-{size}-{emitted_sizes[size]}",
                    "day": day,
                    "edge_count": component_edges[root],
                    "account_count": size,
                    "laundering_edges": 0,
                    "spanning_tree_edge_indices": spanning_tree_edges[root],
                }
            )

    return {
        "positive_ring_count": len(positive_accounts),
        "candidate_count": len(candidates),
        "candidate_window_hours": window_hours,
        "positive_account_size_distribution": dict(target_sizes),
        "candidates": candidates,
    }


def build_edge_features(
    canonical_dir: str | Path,
    output_path: str | Path,
    *,
    train_cutoff: datetime,
    validation_cutoff: datetime,
) -> dict[str, object]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    history: dict[str, _AccountHistory] = defaultdict(_AccountHistory)

    scanner = ds.dataset(Path(canonical_dir), format="parquet", partitioning="hive").scanner(
        columns=[
            "transaction_id",
            "timestamp",
            "source_account",
            "destination_account",
            "source_institution",
            "destination_institution",
            "amount_inr",
            "original_currency",
            "channel",
            "edge_label",
            "ring_id",
        ],
        batch_size=50_000,
    )

    writer: pq.ParquetWriter | None = None
    row_count = 0
    previous_timestamp: datetime | None = None
    feature_names = (
        "amount_log",
        "time_since_source_seconds",
        "source_count_1h",
        "source_sum_1h",
        "source_count_24h",
        "source_sum_24h",
        "source_count_7d",
        "source_sum_7d",
        "destination_count_1h",
        "destination_sum_1h",
        "destination_count_24h",
        "destination_sum_24h",
        "destination_count_7d",
        "destination_sum_7d",
        "source_out_degree",
        "source_in_degree",
        "source_out_amount_inr",
        "source_in_amount_inr",
        "source_in_out_amount_ratio",
        "destination_out_degree",
        "destination_in_degree",
        "destination_out_amount_inr",
        "destination_in_amount_inr",
        "destination_in_out_amount_ratio",
        "time_of_day_sin",
        "time_of_day_cos",
    )
    categorical_feature_names = ("original_currency", "channel")
    pending_timestamp: datetime | None = None
    pending_events: dict[str, list[tuple[float, bool, bool]]] = defaultdict(list)

    def commit_pending_events() -> None:
        if pending_timestamp is None:
            return
        for account, pending_records in pending_events.items():
            for pending_amount, outgoing, incoming in pending_records:
                history[account].record(
                    pending_timestamp,
                    pending_amount,
                    outgoing=outgoing,
                    incoming=incoming,
                )
        pending_events.clear()

    for batch in scanner.to_batches():
        table = batch.to_pydict()
        rows: list[dict[str, object]] = []
        timestamps = table["timestamp"]
        for index, timestamp in enumerate(timestamps):
            parsed = _timestamp_value(timestamp)
            if previous_timestamp is not None and parsed < previous_timestamp:
                raise ValueError("canonical transactions are not timestamp ordered")
            previous_timestamp = parsed
            if pending_timestamp is not None and parsed != pending_timestamp:
                commit_pending_events()
            pending_timestamp = parsed
            source = str(table["source_account"][index])
            destination = str(table["destination_account"][index])
            amount = float(table["amount_inr"][index])
            split = "train" if parsed < train_cutoff else "validation" if parsed < validation_cutoff else "test"

            source_features = history[source].features(parsed)
            destination_features = (
                source_features if destination == source else history[destination].features(parsed)
            )
            source_degrees = history[source].degree_features()
            destination_degrees = (
                source_degrees
                if destination == source
                else history[destination].degree_features()
            )
            pending_events[source].append((amount, True, destination == source))
            if destination != source:
                pending_events[destination].append((amount, False, True))
            day_phase = (
                parsed.hour * 3600
                + parsed.minute * 60
                + parsed.second
                + parsed.microsecond / 1_000_000
            ) / 86_400
            time_angle = 2 * math.pi * day_phase
            rows.append(
                {
                    "transaction_id": str(table["transaction_id"][index]),
                    "timestamp": parsed,
                    "source_account": source,
                    "destination_account": destination,
                    "source_institution": str(table["source_institution"][index]),
                    "destination_institution": str(table["destination_institution"][index]),
                    "original_currency": str(table["original_currency"][index]),
                    "channel": str(table["channel"][index]),
                    "split": split,
                    "train_mask": split == "train",
                    "validation_mask": split == "validation",
                    "test_mask": split == "test",
                    "edge_label": int(table["edge_label"][index]),
                    "amount_log": math.log1p(max(amount, 0.0)),
                    "time_since_source_seconds": source_features[0],
                    "source_count_1h": source_features[1],
                    "source_sum_1h": source_features[2],
                    "source_count_24h": source_features[3],
                    "source_sum_24h": source_features[4],
                    "source_count_7d": source_features[5],
                    "source_sum_7d": source_features[6],
                    "destination_count_1h": destination_features[1],
                    "destination_sum_1h": destination_features[2],
                    "destination_count_24h": destination_features[3],
                    "destination_sum_24h": destination_features[4],
                    "destination_count_7d": destination_features[5],
                    "destination_sum_7d": destination_features[6],
                    "source_out_degree": float(source_degrees[0]),
                    "source_in_degree": float(source_degrees[1]),
                    "source_out_amount_inr": source_degrees[2],
                    "source_in_amount_inr": source_degrees[3],
                    "source_in_out_amount_ratio": (
                        source_degrees[3] / source_degrees[2]
                        if source_degrees[2] > 0
                        else 0.0
                    ),
                    "destination_out_degree": float(destination_degrees[0]),
                    "destination_in_degree": float(destination_degrees[1]),
                    "destination_out_amount_inr": destination_degrees[2],
                    "destination_in_amount_inr": destination_degrees[3],
                    "destination_in_out_amount_ratio": (
                        destination_degrees[3] / destination_degrees[2]
                        if destination_degrees[2] > 0
                        else 0.0
                    ),
                    "time_of_day_sin": math.sin(time_angle),
                    "time_of_day_cos": math.cos(time_angle),
                }
            )
        if not rows:
            continue
        table_out = pa.Table.from_pylist(rows)
        if writer is None:
            writer = pq.ParquetWriter(output, table_out.schema, compression="zstd", version="2.6")
        elif not table_out.schema.equals(writer.schema):
            raise ValueError("edge-feature batches have inconsistent schemas")
        writer.write_table(table_out)
        row_count += len(rows)
    commit_pending_events()
    if writer is not None:
        writer.close()
    if row_count == 0:
        raise ValueError("no edge features generated")

    forbidden = {"ring_id", "typology", "timestamp_future", "edge_label"}
    if forbidden.intersection((*feature_names, *categorical_feature_names)):
        raise AssertionError("ring or future-time leakage column detected")
    return {
        "rows": row_count,
        "parquet_path": str(output),
        "feature_columns": list(feature_names),
        "categorical_feature_columns": list(categorical_feature_names),
        "target_column": "edge_label",
        "metadata_columns": [
            "transaction_id",
            "timestamp",
            "source_account",
            "destination_account",
            "source_institution",
            "destination_institution",
            "split",
        ],
        "history_is_strictly_prior": True,
    }


def build_local_client_edges(
    canonical_dir: str | Path,
    partition_specs: dict[str, tuple[Path, dict[str, int], int]],
    *,
    train_cutoff: datetime,
    validation_cutoff: datetime,
) -> dict[str, object]:
    for output_dir, _, _ in partition_specs.values():
        output_dir.mkdir(parents=True, exist_ok=True)
    scanner = ds.dataset(Path(canonical_dir), format="parquet", partitioning="hive").scanner(
        columns=[
            "transaction_id",
            "timestamp",
            "source_account",
            "destination_account",
            "source_institution",
            "destination_institution",
            "amount_inr",
            "edge_label",
            "ring_id",
            "original_currency",
            "channel",
        ],
        batch_size=50_000,
    )

    writers: dict[tuple[str, int], pq.ParquetWriter] = {}
    buffers: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    counts = {
        name: {client: 0 for client in range(client_count)}
        for name, (_, _, client_count) in partition_specs.items()
    }
    positive_counts = {
        name: {client: 0 for client in range(client_count)}
        for name, (_, _, client_count) in partition_specs.items()
    }
    validation_rows_written = {name: 0 for name in partition_specs}
    cross_edge_counts = {
        name: {client: 0 for client in range(client_count)}
        for name, (_, _, client_count) in partition_specs.items()
    }
    node_sets: dict[str, dict[int, set[str]]] = {
        name: {client: set() for client in range(client_count)}
        for name, (_, _, client_count) in partition_specs.items()
    }
    ring_sets: dict[str, dict[int, set[str]]] = {
        name: {client: set() for client in range(client_count)}
        for name, (_, _, client_count) in partition_specs.items()
    }

    def flush_client_buffer(name: str, client: int) -> None:
        rows = buffers[(name, client)]
        if not rows:
            return
        validation_rows_written[name] += sum(
            row["validation_mask"] is True for row in rows
        )
        row_table = pa.Table.from_pylist(rows)
        writer = writers.get((name, client))
        if writer is None:
            output_dir, _, _ = partition_specs[name]
            writer = pq.ParquetWriter(
                output_dir / f"client-{client}.parquet",
                row_table.schema,
                compression="zstd",
                version="2.6",
            )
            writers[(name, client)] = writer
        writer.write_table(row_table)
        rows.clear()

    for batch in scanner.to_batches():
        table = batch.to_pydict()
        for index, source_inst in enumerate(table["source_institution"]):
            destination_inst = str(table["destination_institution"][index])
            source_inst = str(source_inst)
            timestamp = _timestamp_value(table["timestamp"][index])
            if train_cutoff <= timestamp < validation_cutoff:
                continue
            split = "train" if timestamp < train_cutoff else "test"
            for name, (_, institution_to_client, _) in partition_specs.items():
                source_client = institution_to_client.get(source_inst)
                destination_client = institution_to_client.get(destination_inst)
                local_clients = {
                    client
                    for client in (source_client, destination_client)
                    if client is not None
                }
                for client in local_clients:
                    source_stub = (
                        str(table["source_account"][index])
                        if source_client == client
                        else f"stub:{str(table['source_account'][index])}"
                    )
                    destination_stub = (
                        str(table["destination_account"][index])
                        if destination_client == client
                        else f"stub:{str(table['destination_account'][index])}"
                    )
                    row = {
                        "transaction_id": str(table["transaction_id"][index]),
                        "timestamp": timestamp,
                        "source_node": source_stub,
                        "destination_node": destination_stub,
                        "amount_inr": float(table["amount_inr"][index]),
                        "edge_label": int(table["edge_label"][index]),
                        "split": split,
                        "train_mask": split == "train",
                        "validation_mask": split == "validation",
                        "test_mask": split == "test",
                        "original_currency": str(table["original_currency"][index]),
                        "channel": str(table["channel"][index]),
                    }
                    buffers[(name, client)].append(row)
                    counts[name][client] += 1
                    positive_counts[name][client] += int(table["edge_label"][index])
                    cross_edge_counts[name][client] += int(source_inst != destination_inst)
                    node_sets[name][client].update((source_stub, destination_stub))
                    ring_id = table["ring_id"][index]
                    if ring_id:
                        ring_sets[name][client].add(str(ring_id))
                    if len(buffers[(name, client)]) >= 50_000:
                        flush_client_buffer(name, client)

    for name, (_, _, client_count) in partition_specs.items():
        for client in range(client_count):
            flush_client_buffer(name, client)
    for writer in writers.values():
        writer.close()
    if any(validation_rows_written.values()):
        raise AssertionError("neutral validation edges were written into a client graph")
    for name, (output_dir, _, client_count) in partition_specs.items():
        for client in range(client_count):
            if counts[name][client] == 0:
                pq.write_table(
                    pa.table(
                        {
                            "transaction_id": pa.array([], type=pa.string()),
                            "timestamp": pa.array([], type=pa.timestamp("ns", tz="UTC")),
                            "source_node": pa.array([], type=pa.string()),
                            "destination_node": pa.array([], type=pa.string()),
                            "amount_inr": pa.array([], type=pa.float64()),
                            "edge_label": pa.array([], type=pa.int64()),
                            "split": pa.array([], type=pa.string()),
                            "train_mask": pa.array([], type=pa.bool_()),
                            "validation_mask": pa.array([], type=pa.bool_()),
                            "test_mask": pa.array([], type=pa.bool_()),
                            "original_currency": pa.array([], type=pa.string()),
                            "channel": pa.array([], type=pa.string()),
                        }
                    ),
                    output_dir / f"client-{client}.parquet",
                )
    client_stats = {
        name: {
            client: {
                "edges": counts[name][client],
                "nodes": len(node_sets[name][client]),
                "positive_edges": positive_counts[name][client],
                "positive_edge_rate": (
                    positive_counts[name][client] / counts[name][client]
                    if counts[name][client]
                    else 0.0
                ),
                "visible_rings": len(ring_sets[name][client]),
                "cross_institution_edges": cross_edge_counts[name][client],
                "cross_institution_edge_share": (
                    cross_edge_counts[name][client] / counts[name][client]
                    if counts[name][client]
                    else 0.0
                ),
            }
            for client in range(partition_specs[name][2])
        }
        for name in partition_specs
    }
    return {
        "client_edge_counts": counts,
        "client_stats": client_stats,
        "validation_rows_written": validation_rows_written,
    }


def export_k6_balanced_graphs(
    graph_dir: str | Path,
    currency_categories: list[str],
    channel_categories: list[str],
) -> None:
    graph_root = Path(graph_dir) / "k6" / "balanced_local"
    neo4j_root = Path(graph_dir) / "k6" / "neo4j"
    currency_ids = {value: index for index, value in enumerate(currency_categories)}
    channel_ids = {value: index for index, value in enumerate(channel_categories)}
    for client_path in sorted(graph_root.glob("client-*.parquet")):
        client_name = client_path.stem
        export_dir = client_path.parent / f"{client_name}-pyg"
        export_dir.mkdir(parents=True, exist_ok=True)
        parquet = pq.ParquetFile(client_path)
        edge_count = parquet.metadata.num_rows
        nodes: set[str] = set()
        for batch in parquet.iter_batches(
            columns=["source_node", "destination_node"],
            batch_size=50_000,
        ):
            table = batch.to_pydict()
            nodes.update(str(node) for node in table["source_node"])
            nodes.update(str(node) for node in table["destination_node"])
        node_ids = sorted(nodes)
        node_indexes = {node: index for index, node in enumerate(node_ids)}
        np.save(export_dir / "node_ids.npy", np.asarray(node_ids, dtype=str))
        np.save(
            export_dir / "stub_mask.npy",
            np.asarray([node.startswith("stub:") for node in node_ids], dtype=np.bool_),
        )

        def create_array(name: str, dtype: str, shape: tuple[int, ...]) -> np.ndarray:
            path = export_dir / f"{name}.npy"
            numpy_dtype = np.dtype(dtype)
            if edge_count:
                return np.lib.format.open_memmap(path, mode="w+", dtype=numpy_dtype, shape=shape)
            array = np.empty(shape, dtype=numpy_dtype)
            np.save(path, array)
            return array

        edge_index = create_array("edge_index", "int64", (2, edge_count))
        edge_attributes = create_array("edge_attr", "float64", (edge_count, 3))
        timestamps = create_array("timestamps", "int64", (edge_count,))
        labels = create_array("edge_labels", "int8", (edge_count,))
        train_mask = create_array("train_mask", "bool", (edge_count,))
        validation_mask = create_array("validation_mask", "bool", (edge_count,))
        test_mask = create_array("test_mask", "bool", (edge_count,))

        neo4j_root.mkdir(parents=True, exist_ok=True)
        node_csv_path = neo4j_root / f"{client_name}-nodes.csv"
        edge_csv_path = neo4j_root / f"{client_name}-edges.csv"
        with node_csv_path.open("w", newline="", encoding="utf-8") as node_file:
            node_writer = csv.writer(node_file)
            node_writer.writerow(["node_id:ID", "is_stub:boolean", ":LABEL"])
            for node in node_ids:
                is_stub = node.startswith("stub:")
                node_writer.writerow([node, str(is_stub).lower(), "FraudMeshNode;Stub" if is_stub else "FraudMeshNode"])

        row_offset = 0
        with edge_csv_path.open("w", newline="", encoding="utf-8") as edge_file:
            edge_writer = csv.writer(edge_file)
            edge_writer.writerow(
                [
                    ":START_ID",
                    ":END_ID",
                    "transaction_id:string",
                    "timestamp:datetime",
                    "amount_inr:float",
                    "edge_label:int",
                    "split:string",
                    "original_currency:string",
                    "channel:string",
                    ":TYPE",
                ]
            )
            for batch in parquet.iter_batches(batch_size=50_000):
                rows = batch.to_pydict()
                for index, transaction_id in enumerate(rows["transaction_id"]):
                    source = str(rows["source_node"][index])
                    destination = str(rows["destination_node"][index])
                    timestamp = _timestamp_value(rows["timestamp"][index])
                    amount = float(rows["amount_inr"][index])
                    currency = str(rows["original_currency"][index])
                    channel = str(rows["channel"][index])
                    split = str(rows["split"][index])
                    edge_label = int(rows["edge_label"][index])
                    edge_index[0, row_offset] = node_indexes[source]
                    edge_index[1, row_offset] = node_indexes[destination]
                    edge_attributes[row_offset] = (
                        amount,
                        currency_ids[currency],
                        channel_ids[channel],
                    )
                    timestamps[row_offset] = int(timestamp.timestamp() * 1_000_000)
                    labels[row_offset] = edge_label
                    train_mask[row_offset] = split == "train"
                    validation_mask[row_offset] = split == "validation"
                    test_mask[row_offset] = split == "test"
                    edge_writer.writerow(
                        [
                            source,
                            destination,
                            transaction_id,
                            timestamp.isoformat(),
                            amount,
                            edge_label,
                            split,
                            currency,
                            channel,
                            "FRAUDMESH_EDGE",
                        ]
                    )
                    row_offset += 1
        if row_offset != edge_count:
            raise AssertionError(f"{client_name} exported {row_offset} edges; expected {edge_count}")
        for array in (
            edge_index,
            edge_attributes,
            timestamps,
            labels,
            train_mask,
            validation_mask,
            test_mask,
        ):
            if isinstance(array, np.memmap):
                array.flush()
        metadata = {
            "node_count": len(node_ids),
            "edge_count": edge_count,
            "edge_index_orientation": ["source_node", "destination_node"],
            "edge_attributes": ["amount_inr", "original_currency_id", "channel_id"],
            "timestamp_unit": "microseconds since Unix epoch, UTC",
            "currency_categories": currency_categories,
            "channel_categories": channel_categories,
            "arrays": [
                "node_ids.npy",
                "stub_mask.npy",
                "edge_index.npy",
                "edge_attr.npy",
                "timestamps.npy",
                "edge_labels.npy",
                "train_mask.npy",
                "validation_mask.npy",
                "test_mask.npy",
            ],
        }
        (export_dir / "metadata.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


def build_phase2_artefacts(
    canonical_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, object]:
    dataset = ds.dataset(Path(canonical_dir), format="parquet", partitioning="hive")
    sort_columns = [
        "transaction_id",
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "amount_inr",
        "original_currency",
        "channel",
        "edge_label",
        "ring_id",
    ]
    required = {
        "timestamp", "source_account", "destination_account", "source_institution",
        "destination_institution", "amount_inr", "original_currency", "channel",
        "edge_label", "ring_id", "transaction_id",
    }
    missing = required.difference(dataset.schema.names)
    if missing:
        raise ValueError(f"canonical Phase 2 input is missing columns: {sorted(missing)}")
    with tempfile.TemporaryDirectory(prefix="fraudmesh-phase2-") as temporary_dir:
        sorted_path = Path(temporary_dir) / "timestamp-sorted.parquet"
        _write_timestamp_sorted_parquet(dataset, sorted_path, sort_columns)
        return _build_phase2_artefacts_sorted(sorted_path, output_dir)


def _build_phase2_artefacts_sorted(
    canonical_dir: str | Path,
    output_dir: str | Path,
) -> dict[str, object]:
    dataset = ds.dataset(Path(canonical_dir), format="parquet", partitioning="hive")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    scan_columns = [
        "transaction_id",
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "edge_label",
        "ring_id",
        "original_currency",
        "channel",
    ]
    account_labels: dict[str, int] = {}
    institution_edge_counts: Counter[str] = Counter()
    ring_accounts: dict[str, set[str]] = defaultdict(set)
    ring_institutions: dict[str, set[str]] = defaultdict(set)
    ring_edge_counts: Counter[str] = Counter()
    ring_first_timestamp: dict[str, datetime] = {}
    ring_last_timestamp: dict[str, datetime] = {}
    currency_categories_seen: set[str] = set()
    channel_categories_seen: set[str] = set()
    row_count = 0
    timestamp_min: datetime | None = None
    timestamp_max: datetime | None = None
    for batch in dataset.scanner(columns=scan_columns, batch_size=50_000).to_batches():
        rows = batch.to_pydict()
        for index, timestamp in enumerate(rows["timestamp"]):
            parsed = _timestamp_value(timestamp)
            timestamp_min = parsed if timestamp_min is None or parsed < timestamp_min else timestamp_min
            timestamp_max = parsed if timestamp_max is None or parsed > timestamp_max else timestamp_max
            source = str(rows["source_account"][index])
            destination = str(rows["destination_account"][index])
            source_institution = str(rows["source_institution"][index])
            destination_institution = str(rows["destination_institution"][index])
            label = int(rows["edge_label"][index])
            currency_categories_seen.add(str(rows["original_currency"][index]))
            channel_categories_seen.add(str(rows["channel"][index]))
            account_labels[source] = max(account_labels.get(source, 0), label)
            account_labels[destination] = max(account_labels.get(destination, 0), label)
            institution_edge_counts[source_institution] += 1
            institution_edge_counts[destination_institution] += 1
            ring_id = rows["ring_id"][index]
            if ring_id:
                ring_key = str(ring_id)
                ring_accounts[ring_key].update((source, destination))
                ring_institutions[ring_key].update((source_institution, destination_institution))
                ring_edge_counts[ring_key] += 1
                ring_first_timestamp[ring_key] = min(
                    parsed,
                    ring_first_timestamp.get(ring_key, parsed),
                )
                ring_last_timestamp[ring_key] = max(
                    parsed,
                    ring_last_timestamp.get(ring_key, parsed),
                )
            row_count += 1
    if timestamp_min is None or timestamp_max is None:
        raise ValueError("canonical Phase 2 input is empty")
    span = timestamp_max - timestamp_min
    train_cutoff = timestamp_min + span * 0.6
    validation_cutoff = timestamp_min + span * 0.8
    institutions = sorted(institution_edge_counts)
    max_positive_size = max((len(accounts) for accounts in ring_accounts.values()), default=2)

    split_account_labels: dict[str, dict[str, int]] = {
        "train": {},
        "validation": {},
        "test": {},
    }
    split_account_seen: dict[str, set[str]] = {
        "train": set(),
        "validation": set(),
        "test": set(),
    }
    split_counts = {"train": 0, "validation": 0, "test": 0}
    neutral_validation = output / "neutral_validation_edges.parquet"
    neutral_schema = pa.schema(
        [
            ("transaction_id", pa.string()),
            ("timestamp", pa.timestamp("ns", tz="UTC")),
            ("source_account", pa.string()),
            ("destination_account", pa.string()),
            ("source_institution", pa.string()),
            ("destination_institution", pa.string()),
            ("amount_inr", pa.float64()),
            ("edge_label", pa.int64()),
            ("ring_id", pa.string()),
            ("split", pa.string()),
            ("train_mask", pa.bool_()),
            ("validation_mask", pa.bool_()),
            ("test_mask", pa.bool_()),
        ]
    )
    neutral_writer = pq.ParquetWriter(neutral_validation, neutral_schema, compression="zstd")
    neutral_buffer: list[dict[str, object]] = []
    neutral_rows = 0

    def flush_neutral_buffer() -> None:
        nonlocal neutral_rows
        if not neutral_buffer:
            return
        neutral_writer.write_table(pa.Table.from_pylist(neutral_buffer, schema=neutral_schema))
        neutral_rows += len(neutral_buffer)
        neutral_buffer.clear()

    label_scanner = dataset.scanner(
        columns=[
            "transaction_id",
            "timestamp",
            "source_account",
            "destination_account",
            "source_institution",
            "destination_institution",
            "amount_inr",
            "edge_label",
            "ring_id",
        ],
        batch_size=50_000,
    )
    try:
        for batch in label_scanner.to_batches():
            rows = batch.to_pydict()
            for index, timestamp in enumerate(rows["timestamp"]):
                parsed = _timestamp_value(timestamp)
                split = (
                    "train"
                    if parsed < train_cutoff
                    else "validation"
                    if parsed < validation_cutoff
                    else "test"
                )
                split_counts[split] += 1
                label = int(rows["edge_label"][index])
                source_account = str(rows["source_account"][index])
                destination_account = str(rows["destination_account"][index])
                for account in (source_account, destination_account):
                    split_account_seen[split].add(account)
                    split_account_labels[split][account] = max(
                        split_account_labels[split].get(account, 0), label
                    )
                if split == "validation":
                    neutral_buffer.append(
                        {
                            "transaction_id": str(rows["transaction_id"][index]),
                            "timestamp": parsed,
                            "source_account": source_account,
                            "destination_account": destination_account,
                            "source_institution": str(rows["source_institution"][index]),
                            "destination_institution": str(rows["destination_institution"][index]),
                            "amount_inr": float(rows["amount_inr"][index]),
                            "edge_label": label,
                            "ring_id": rows["ring_id"][index],
                            "split": split,
                            "train_mask": False,
                            "validation_mask": True,
                            "test_mask": False,
                        }
                    )
                    if len(neutral_buffer) >= 50_000:
                        flush_neutral_buffer()
        flush_neutral_buffer()
    finally:
        neutral_writer.close()

    account_path = output / "account_labels.parquet"
    account_writer: pq.ParquetWriter | None = None
    account_buffer: list[dict[str, object]] = []
    try:
        for account, label in account_labels.items():
            account_buffer.append(
                {
                    "account_id": account,
                    "account_label": label,
                    "account_label_train": split_account_labels["train"].get(account, 0),
                    "account_label_validation": split_account_labels["validation"].get(account, 0),
                    "account_label_test": split_account_labels["test"].get(account, 0),
                    "train_label_mask": account in split_account_seen["train"],
                    "validation_label_mask": account in split_account_seen["validation"],
                    "test_label_mask": account in split_account_seen["test"],
                }
            )
            if len(account_buffer) >= 50_000:
                table = pa.Table.from_pylist(account_buffer)
                if account_writer is None:
                    account_writer = pq.ParquetWriter(account_path, table.schema, compression="zstd")
                account_writer.write_table(table)
                account_buffer.clear()
        if account_buffer:
            table = pa.Table.from_pylist(account_buffer)
            if account_writer is None:
                account_writer = pq.ParquetWriter(account_path, table.schema, compression="zstd")
            account_writer.write_table(table)
    finally:
        if account_writer is not None:
            account_writer.close()

    positive_size_targets = Counter(len(accounts) for accounts in ring_accounts.values())
    candidate_counts: Counter[int] = Counter()
    negative_candidates: list[dict[str, object]] = []
    bucket_key: int | None = None
    parent: dict[str, str] = {}
    component_sizes: dict[str, int] = {}
    component_edges: dict[str, int] = {}
    spanning_tree_transactions: dict[str, list[str]] = {}
    bucket_day = ""
    windows = int(timedelta(days=1).total_seconds())

    def find(account: str) -> str:
        parent.setdefault(account, account)
        component_sizes.setdefault(account, 1)
        component_edges.setdefault(account, 0)
        spanning_tree_transactions.setdefault(account, [])
        root = account
        while parent[root] != root:
            root = parent[root]
        while parent[account] != account:
            next_account = parent[account]
            parent[account] = root
            account = next_account
        return root

    def finish_negative_bucket(current_bucket: int | None, day: str) -> None:
        if current_bucket is None:
            return
        emitted: Counter[int] = Counter()
        for root, size in component_sizes.items():
            if parent[root] != root or size not in positive_size_targets:
                continue
            if candidate_counts[size] >= positive_size_targets[size]:
                continue
            emitted[size] += 1
            candidate_counts[size] += 1
            negative_candidates.append(
                {
                    "candidate_id": f"negative-{current_bucket}-{size}-{candidate_counts[size]}",
                    "window_day": day,
                    "window_start_utc": datetime.fromtimestamp(
                        current_bucket * windows,
                        tz=timezone.utc,
                    ).isoformat(),
                    "account_count": size,
                    "edge_count": component_edges[root],
                    "positive_edges": 0,
                    "label": 0,
                    "spanning_tree_edge_transaction_ids": spanning_tree_transactions[root],
                }
            )
        parent.clear()
        component_sizes.clear()
        component_edges.clear()
        spanning_tree_transactions.clear()

    negative_scanner = dataset.scanner(
        columns=["transaction_id", "timestamp", "source_account", "destination_account", "edge_label"],
        batch_size=50_000,
    )
    previous_timestamp: datetime | None = None
    for batch in negative_scanner.to_batches():
        rows = batch.to_pydict()
        for index, timestamp in enumerate(rows["timestamp"]):
            parsed = _timestamp_value(timestamp)
            if previous_timestamp is not None and parsed < previous_timestamp:
                raise ValueError("canonical transactions are not timestamp ordered")
            previous_timestamp = parsed
            current_bucket = int(parsed.timestamp()) // windows
            if bucket_key is None:
                bucket_key = current_bucket
                bucket_day = parsed.strftime("%Y-%m-%d")
            elif current_bucket != bucket_key:
                finish_negative_bucket(bucket_key, bucket_day)
                bucket_key = current_bucket
                bucket_day = parsed.strftime("%Y-%m-%d")
            if int(rows["edge_label"][index]) == 1:
                continue
            source = str(rows["source_account"][index])
            destination = str(rows["destination_account"][index])
            transaction_id = str(rows["transaction_id"][index])
            source_root = find(source)
            destination_root = find(destination)
            if source_root == destination_root:
                component_edges[source_root] += 1
                continue
            new_size = component_sizes[source_root] + component_sizes[destination_root]
            if new_size > max_positive_size:
                continue
            parent[destination_root] = source_root
            component_sizes[source_root] = new_size
            component_edges[source_root] += component_edges[destination_root] + 1
            spanning_tree_transactions[source_root].extend(
                spanning_tree_transactions[destination_root]
            )
            spanning_tree_transactions[source_root].append(transaction_id)
    finish_negative_bucket(bucket_key, bucket_day)

    ring_report = {
        "positive_ring_count": len(ring_accounts),
        "positive_account_size_distribution": dict(positive_size_targets),
        "candidate_count": len(negative_candidates),
        "candidate_window_hours": 24,
        "candidate_method": "negative-only weakly connected components in deterministic UTC 24-hour windows, capped to observed positive ring sizes",
        "positive_ring_split_assignment": "Assign each ring to the split containing its first labelled transaction; mark rings crossing either temporal cutoff.",
        "positive_ring_split_straddlers": sum(
            any(
                ring_first_timestamp[ring_id] < cutoff <= ring_last_timestamp[ring_id]
                for cutoff in (train_cutoff, validation_cutoff)
            )
            for ring_id in ring_accounts
        ),
        "candidates": negative_candidates,
    }
    (output / "ring_negatives.json").write_text(
        json.dumps(ring_report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    ring_label_rows: list[dict[str, object]] = []
    for ring_id, accounts in ring_accounts.items():
        first_timestamp = ring_first_timestamp[ring_id]
        last_timestamp = ring_last_timestamp[ring_id]
        split = (
            "train"
            if first_timestamp < train_cutoff
            else "validation"
            if first_timestamp < validation_cutoff
            else "test"
        )
        ring_label_rows.append(
            {
                "ring_id": ring_id,
                "ring_label": 1,
                "account_count": len(accounts),
                "edge_count": ring_edge_counts[ring_id],
                "split": split,
                "crosses_temporal_boundary": any(
                    first_timestamp < cutoff <= last_timestamp
                    for cutoff in (train_cutoff, validation_cutoff)
                ),
                "first_timestamp": first_timestamp,
                "last_timestamp": last_timestamp,
                "spanning_tree_edge_transaction_ids": [],
            }
        )
    for candidate in negative_candidates:
        first_timestamp = datetime.fromisoformat(
            str(candidate["window_start_utc"])
        )
        split = (
            "train"
            if first_timestamp < train_cutoff
            else "validation"
            if first_timestamp < validation_cutoff
            else "test"
        )
        ring_label_rows.append(
            {
                "ring_id": candidate["candidate_id"],
                "ring_label": 0,
                "account_count": candidate["account_count"],
                "edge_count": candidate["edge_count"],
                "split": split,
                "crosses_temporal_boundary": False,
                "first_timestamp": first_timestamp,
                "last_timestamp": first_timestamp,
                "spanning_tree_edge_transaction_ids": candidate[
                    "spanning_tree_edge_transaction_ids"
                ],
            }
        )
    ring_label_schema = pa.schema(
        [
            ("ring_id", pa.string()),
            ("ring_label", pa.int8()),
            ("account_count", pa.int64()),
            ("edge_count", pa.int64()),
            ("split", pa.string()),
            ("crosses_temporal_boundary", pa.bool_()),
            ("first_timestamp", pa.timestamp("ns", tz="UTC")),
            ("last_timestamp", pa.timestamp("ns", tz="UTC")),
            ("spanning_tree_edge_transaction_ids", pa.list_(pa.string())),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(ring_label_rows, schema=ring_label_schema),
        output / "ring_labels.parquet",
        compression="zstd",
    )

    edge_features = build_edge_features(
        canonical_dir,
        output / "edge_features.parquet",
        train_cutoff=train_cutoff,
        validation_cutoff=validation_cutoff,
    )
    partition_specs: dict[str, tuple[Path, dict[str, int], int]] = {}
    partitions_by_k: dict[str, dict[str, dict[str, int]]] = {}
    for client_count in (3, 6, 8):
        variant = f"k{client_count}"
        variant_dir = output / variant
        balanced = balanced_partition(institutions, client_count)
        skewed = size_skewed_partition(institutions, dict(institution_edge_counts), client_count)
        (variant_dir).mkdir(parents=True, exist_ok=True)
        (variant_dir / "balanced_partition.json").write_text(
            json.dumps(balanced, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (variant_dir / "size_skewed_partition.json").write_text(
            json.dumps(skewed, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        balanced_name = f"{variant}/balanced_local"
        skewed_name = f"{variant}/size_skewed_local"
        partition_specs[balanced_name] = (
            variant_dir / "balanced_local",
            balanced,
            client_count,
        )
        partition_specs[skewed_name] = (
            variant_dir / "size_skewed_local",
            skewed,
            client_count,
        )
        partitions_by_k[variant] = {"balanced": balanced, "size_skewed": skewed}

    local_outputs = build_local_client_edges(
        canonical_dir,
        partition_specs,
        train_cutoff=train_cutoff,
        validation_cutoff=validation_cutoff,
    )
    currency_categories = sorted(currency_categories_seen)
    channel_categories = sorted(channel_categories_seen)
    export_k6_balanced_graphs(output, currency_categories, channel_categories)
    local_counts = cast(dict[str, dict[int, int]], local_outputs["client_edge_counts"])
    local_stats = cast(
        dict[str, dict[int, dict[str, object]]],
        local_outputs["client_stats"],
    )
    validation_rows_written = cast(
        dict[str, int],
        local_outputs["validation_rows_written"],
    )
    client_summary: dict[str, object] = {}
    ring_visibility_by_k: dict[str, object] = {}
    for variant, partitions in partitions_by_k.items():
        variant_dir = output / variant

        def local_result(partition_name: str) -> dict[str, object]:
            spec = f"{variant}/{partition_name}_local"
            return {
                "client_edge_counts": local_counts[spec],
                "client_stats": local_stats[spec],
            }

        balanced_local = local_result("balanced")
        skewed_local = local_result("size_skewed")

        def visibility(partition: dict[str, int]) -> dict[str, object]:
            fully_visible = sum(
                len({partition[bank] for bank in banks}) <= 1
                for banks in ring_institutions.values()
            )
            total_rings = len(ring_institutions)
            split_rings = total_rings - fully_visible
            return {
                "ring_count": total_rings,
                "fully_visible_rings": fully_visible,
                "split_across_clients_rings": split_rings,
                "fully_visible_share": fully_visible / total_rings if total_rings else 0.0,
                "split_across_clients_share": split_rings / total_rings if total_rings else 0.0,
            }

        blind_spot = {
            "institution_count": len(institutions),
            "institution_edge_count": sum(institution_edge_counts.values()),
            "balanced": visibility(partitions["balanced"]),
            "size_skewed": visibility(partitions["size_skewed"]),
            "balanced_clients": balanced_local["client_stats"],
            "size_skewed_clients": skewed_local["client_stats"],
        }
        (variant_dir / "blind_spot_report.json").write_text(
            json.dumps(blind_spot, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        client_summary[variant] = {
            "balanced": balanced_local,
            "size_skewed": skewed_local,
            "blind_spot": blind_spot,
        }
        ring_visibility_by_k[variant] = {
            "balanced": blind_spot["balanced"],
            "size_skewed": blind_spot["size_skewed"],
        }

    (output / "chronological_split.json").write_text(
        json.dumps(
            {
                "split_counts": split_counts,
                "train_cutoff_exclusive": train_cutoff.isoformat(),
                "validation_cutoff_exclusive": validation_cutoff.isoformat(),
                "neutral_validation_rows": neutral_rows,
            },
            sort_keys=True,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    edge_feature_columns = cast(list[str], edge_features["feature_columns"])
    leakage_assertions = {
        "ring_id_in_edge_features": "ring_id" not in edge_feature_columns,
        "typology_in_edge_features": "typology" not in edge_feature_columns,
        "label_not_in_feature_columns": "edge_label" not in edge_feature_columns,
        "neutral_validation_excluded_from_client_graphs": not any(
            validation_rows_written.values()
        ),
        "feature_timestamp_not_after_edge": edge_features["history_is_strictly_prior"],
    }
    if not all(leakage_assertions.values()):
        raise AssertionError(f"Phase 2 leakage assertion failed: {leakage_assertions}")
    (output / "leakage_assertions.json").write_text(
        json.dumps(leakage_assertions, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "rows": row_count,
        "institutions": len(institutions),
        "positive_accounts": sum(account_labels.values()),
        "ring_negatives": ring_report,
        "edge_features": edge_features,
        "chronological": split_counts,
        "neutral_validation_rows": neutral_rows,
        "variants": client_summary,
        "pyg_exports": str(output / "k6" / "balanced_local"),
        "neo4j_exports": str(output / "k6" / "neo4j"),
        "ring_visibility_by_k": ring_visibility_by_k,
        "leakage_assertions": leakage_assertions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build initial Phase 2 AMLworld graph artefacts.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--client-count", type=int, default=6)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    if args.complete:
        result = build_phase2_artefacts(args.input_dir, args.output_dir)
    else:
        result = build_amlworld_graph(args.input_dir, args.output_dir, client_count=args.client_count)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
