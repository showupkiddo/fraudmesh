from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

import pyarrow.parquet as pq
import pytest

from fraudmesh.data.canonical import TabularExample
from fraudmesh.tabular_pipeline import (
    BAF_FILES,
    convert_baf_archive,
    convert_ieee_cis_train,
    convert_paysim,
    convert_ulb,
    write_tabular_parquet_stream,
)


def _write_csv_archive(path: Path, members: dict[str, tuple[list[str], list[list[str]]]]) -> None:
    with ZipFile(path, "w") as archive:
        for name, (fieldnames, rows) in members.items():
            buffer = StringIO()
            writer = csv.writer(buffer)
            writer.writerow(fieldnames)
            writer.writerows(rows)
            archive.writestr(name, buffer.getvalue())


def _write_csv(path: Path, fieldnames: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fieldnames)
        writer.writerows(rows)


def test_streaming_tabular_writer_validates_across_batch_boundaries(tmp_path: Path) -> None:
    examples = [
        TabularExample("test", "row-1", "2024-01-01T00:00:00Z", 1, {"category": "a"}, {}),
        TabularExample("test", "row-1", "2024-01-01T00:00:00Z", 0, {"category": "b"}, {}),
    ]

    with pytest.raises(ValueError, match="duplicate tabular transaction_id"):
        write_tabular_parquet_stream(examples, tmp_path / "duplicate.parquet", batch_size=1)

    output = tmp_path / "valid.parquet"
    result = write_tabular_parquet_stream(examples[:1], output, batch_size=1)
    assert result["rows"] == 1
    assert result["positive_labels"] == 1
    assert isinstance(result["sha256"], str)
    assert len(result["sha256"]) == 64
    assert pq.ParquetFile(output).metadata.num_rows == 1


def test_paysim_conversion_preserves_entities_and_excludes_leakage(tmp_path: Path, monkeypatch) -> None:
    archive_path = tmp_path / "paysim.zip"
    _write_csv_archive(
        archive_path,
        {
            "paysim.csv": (
                [
                    "step",
                    "type",
                    "amount",
                    "nameOrig",
                    "oldbalanceOrg",
                    "newbalanceOrig",
                    "nameDest",
                    "oldbalanceDest",
                    "newbalanceDest",
                    "isFraud",
                    "isFlaggedFraud",
                ],
                [
                    ["1", "TRANSFER", "7.0", "origin-a", "7", "0", "dest-a", "0", "7", "1", "0"],
                    ["2", "PAYMENT", "3.0", "origin-b", "3", "0", "dest-b", "0", "3", "0", "0"],
                ],
            )
        },
    )
    monkeypatch.setenv("FRAUDMESH_PSEUDONYMIZATION_KEY", "k" * 32)
    output = tmp_path / "paysim.parquet"

    result = convert_paysim(archive_path, output, batch_size=1)

    table = pq.read_table(output)
    assert result["rows"] == 2
    assert result["positive_labels"] == 1
    assert isinstance(result["timestamp_basis"], str)
    assert result["timestamp_basis"].startswith("step-hours")
    assert "isFlaggedFraud" not in table.column_names
    assert "isFraud" not in table.column_names
    assert table["entity_nameOrig"].to_pylist()[0].startswith("acct_")
    assert table["entity_nameDest"].to_pylist()[0].startswith("acct_")


def test_ulb_conversion_keeps_relative_time_and_label(tmp_path: Path) -> None:
    archive_path = tmp_path / "ulb.zip"
    _write_csv_archive(
        archive_path,
        {
            "creditcard.csv": (
                ["Time", "Amount", "V1", "Class"],
                [["0", "9.0", "0.5", "0"], ["60", "4.0", "0.2", "1"]],
            )
        },
    )
    output = tmp_path / "ulb.parquet"

    result = convert_ulb(archive_path, output, batch_size=1)

    table = pq.read_table(output)
    assert result["rows"] == 2
    assert result["positive_labels"] == 1
    assert isinstance(result["timestamp_basis"], str)
    assert result["timestamp_basis"].startswith("source seconds")
    assert table["timestamp"].to_pylist()[1].isoformat().startswith("1970-01-01T00:01:00")
    assert "Class" not in table.column_names


def test_ieee_cis_conversion_joins_identity_and_pseudonymizes_missing_keys(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transaction_path = tmp_path / "train_transaction.csv"
    identity_path = tmp_path / "train_identity.csv"
    _write_csv(
        transaction_path,
        ["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD", "card1"],
        [
            ["101", "1", "60", "5.2", "W", "card-a"],
            ["102", "0", "120", "12.1", "C", ""],
        ],
    )
    _write_csv(
        identity_path,
        ["TransactionID", "DeviceType", "DeviceInfo", "id_01"],
        [["101", "desktop", "device-a", "-5"]],
    )
    monkeypatch.setenv("FRAUDMESH_PSEUDONYMIZATION_KEY", "k" * 32)
    output = tmp_path / "ieee-cis.parquet"

    result = convert_ieee_cis_train(transaction_path, identity_path, output, batch_size=1)

    table = pq.read_table(output)
    assert result["rows"] == 2
    assert result["positive_labels"] == 1
    assert result["transactions_with_identity"] == 1
    assert result["transactions_without_identity"] == 1
    assert result["identity_rows_without_transaction"] == 0
    assert result["missing_entity_values"] == {"card1": 1, "DeviceInfo": 1}
    assert "TransactionID" not in table.column_names
    assert "TransactionDT" not in table.column_names
    assert "isFraud" not in table.column_names
    assert "card1" not in table.column_names
    assert "DeviceInfo" not in table.column_names
    assert all(value.startswith("acct_") for value in table["entity_card1"].to_pylist())
    assert table["entity_card1"].to_pylist()[0] != table["entity_card1"].to_pylist()[1]


def test_baf_conversion_writes_and_validates_all_six_variants(tmp_path: Path) -> None:
    archive_path = tmp_path / "baf.zip"
    members = {}
    for variant, name in BAF_FILES.items():
        fieldnames = ["fraud_bool", "month", "income"]
        rows = [["0", "0", "0.4"], ["1", "1", "0.8"]]
        if variant in {"variant-iii", "variant-v"}:
            fieldnames.extend(["x1", "x2"])
            rows = [["0", "0", "0.4", "1", "2"], ["1", "1", "0.8", "3", "4"]]
        members[name] = (fieldnames, rows)
    _write_csv_archive(archive_path, members)
    output_dir = tmp_path / "baf"

    results = convert_baf_archive(archive_path, output_dir, batch_size=1)

    assert set(results) == set(BAF_FILES)
    for variant, result in results.items():
        output = output_dir / f"{variant}.parquet"
        columns = pq.read_table(output).column_names
        assert output.is_file()
        assert result["rows"] == 2
        assert result["positive_labels"] == 1
        assert result["timestamp_min"] == "1970-01-01T00:00:00Z"
        assert result["timestamp_max"] == "1970-02-01T00:00:00Z"
        assert "x1" not in columns
        assert "x2" not in columns
        if variant in {"variant-iii", "variant-v"}:
            assert result["excluded_source_columns"] == ["fraud_bool", "month", "x1", "x2"]
