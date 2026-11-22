from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile

import pyarrow as pa
import pyarrow.parquet as pq

from .data.adapters import (
    _open_csv_text,
    adapt_baf_row,
    adapt_ieee_cis_row,
    adapt_paysim_tabular_row,
    adapt_ulb_row,
    validate_tabular_examples,
)
from .data.canonical import TabularExample, pseudonymizer_from_environment

RELATIVE_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
BAF_FILES = {
    "base": "Base.csv",
    "variant-i": "Variant I.csv",
    "variant-ii": "Variant II.csv",
    "variant-iii": "Variant III.csv",
    "variant-iv": "Variant IV.csv",
    "variant-v": "Variant V.csv",
}


def _baf_timestamp(month_value: str) -> str:
    month_index = int(month_value)
    if month_index < 0:
        raise ValueError("BAF month index must be non-negative")
    timestamp = datetime(
        1970 + month_index // 12,
        month_index % 12 + 1,
        1,
        tzinfo=timezone.utc,
    )
    return timestamp.isoformat().replace("+00:00", "Z")


def write_tabular_parquet_stream(
    examples: Iterable[TabularExample],
    output_path: str | Path,
    *,
    batch_size: int = 50_000,
    check_unique_ids: bool = True,
) -> dict[str, object]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    batch: list[TabularExample] = []
    writer: pq.ParquetWriter | None = None
    expected_schema: tuple[str, tuple[str, ...], tuple[str, ...]] | None = None
    seen_ids: set[tuple[str, str]] | None = set() if check_unique_ids else None
    feature_names: tuple[str, ...] = ()
    entity_names: tuple[str, ...] = ()
    missing_values: dict[str, int] = {}
    row_count = 0
    positive_count = 0
    min_timestamp: str | None = None
    max_timestamp: str | None = None

    def flush() -> None:
        nonlocal writer, row_count, positive_count, expected_schema
        nonlocal feature_names, entity_names, min_timestamp, max_timestamp
        if not batch:
            return
        issues = validate_tabular_examples(batch)
        if issues:
            raise ValueError(f"tabular validation failed: {issues[:5]}")
        for example in batch:
            current_schema = (
                example.dataset,
                tuple(example.features),
                tuple(example.entity_keys),
            )
            if expected_schema is None:
                expected_schema = current_schema
                feature_names = current_schema[1]
                entity_names = current_schema[2]
                reserved = {"dataset", "transaction_id", "timestamp", "label"}
                entity_columns = {f"entity_{name}" for name in entity_names}
                collisions = reserved.intersection(feature_names) | set(feature_names).intersection(
                    entity_columns
                )
                if collisions:
                    raise ValueError(f"tabular feature names collide with contract fields: {sorted(collisions)}")
                missing_values.update({name: 0 for name in feature_names})
            elif current_schema != expected_schema:
                raise ValueError("tabular examples do not share one ordered dataset schema")
            if seen_ids is not None:
                key = (example.dataset, example.transaction_id)
                if key in seen_ids:
                    raise ValueError(f"duplicate tabular transaction_id: {example.dataset}/{example.transaction_id}")
                seen_ids.add(key)
            row_count += 1
            positive_count += example.label
            min_timestamp = min(min_timestamp, example.timestamp) if min_timestamp else example.timestamp
            max_timestamp = max(max_timestamp, example.timestamp) if max_timestamp else example.timestamp
            for name, value in example.features.items():
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing_values[name] += 1

        rows: list[dict[str, object]] = []
        for example in batch:
            row: dict[str, object] = {
                "dataset": example.dataset,
                "transaction_id": example.transaction_id,
                "timestamp": datetime.fromisoformat(example.timestamp.replace("Z", "+00:00")),
                "label": example.label,
                **example.features,
            }
            row.update({f"entity_{name}": value for name, value in example.entity_keys.items()})
            rows.append(row)
        table = pa.Table.from_pylist(rows)
        if writer is None:
            writer = pq.ParquetWriter(path, table.schema, compression="zstd", version="2.6")
        elif not table.schema.equals(writer.schema):
            raise ValueError("tabular Parquet batches have inconsistent Arrow schemas")
        writer.write_table(table)
        batch.clear()

    try:
        for example in examples:
            batch.append(example)
            if len(batch) >= batch_size:
                flush()
        flush()
    finally:
        if writer is not None:
            writer.close()

    if row_count == 0:
        raise ValueError("refusing to write an empty tabular dataset")

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "rows": row_count,
        "positive_labels": positive_count,
        "feature_columns": list(feature_names),
        "entity_columns": list(entity_names),
        "missing_values": missing_values,
        "timestamp_min": min_timestamp,
        "timestamp_max": max_timestamp,
        "sha256": digest.hexdigest(),
        "parquet_path": str(path),
    }


def convert_paysim(
    input_path: str | Path,
    output_path: str | Path,
    *,
    row_limit: int | None = None,
    batch_size: int = 50_000,
) -> dict[str, object]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")
    pseudonymizer = pseudonymizer_from_environment()
    with _open_csv_text(input_path) as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("PaySim CSV is missing a header")
        required = {"step", "nameOrig", "nameDest", "isFraud", "isFlaggedFraud"}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"PaySim CSV is missing required columns: {sorted(missing)}")
        excluded = {
            "step",
            "nameOrig",
            "nameDest",
            "isFraud",
            "isFlaggedFraud",
        }
        feature_fields = tuple(name for name in reader.fieldnames if name not in excluded)

        def examples() -> Iterable[TabularExample]:
            for row_number, row in enumerate(reader, start=1):
                if row_limit is not None and row_number > row_limit:
                    break
                yield adapt_paysim_tabular_row(
                    row,
                    row_number=row_number,
                    epoch_origin=RELATIVE_EPOCH,
                    feature_fields=feature_fields,
                    pseudonymizer=pseudonymizer,
                )

        # IDs are generated from source row numbers, so global duplicate tracking is redundant.
        result = write_tabular_parquet_stream(
            examples(),
            output_path,
            batch_size=batch_size,
            check_unique_ids=False,
        )
        result["timestamp_basis"] = "step-hours relative to the source; anchored at 1970-01-01 UTC"
        result["source_unit_policy"] = "source amount features are not INR-denominated monetary outputs"
        return result


def convert_ulb(
    input_path: str | Path,
    output_path: str | Path,
    *,
    row_limit: int | None = None,
    batch_size: int = 50_000,
) -> dict[str, object]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")
    with _open_csv_text(input_path) as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("ULB CSV is missing a header")
        required = {"Time", "Class"}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"ULB CSV is missing required columns: {sorted(missing)}")
        feature_fields = tuple(name for name in reader.fieldnames if name not in {"Time", "Class"})

        def examples() -> Iterable[TabularExample]:
            for row_number, row in enumerate(reader, start=1):
                if row_limit is not None and row_number > row_limit:
                    break
                yield adapt_ulb_row(
                    row,
                    row_number=row_number,
                    epoch_origin=RELATIVE_EPOCH,
                    feature_fields=feature_fields,
                )

        # IDs are generated from source row numbers, so global duplicate tracking is redundant.
        result = write_tabular_parquet_stream(
            examples(),
            output_path,
            batch_size=batch_size,
            check_unique_ids=False,
        )
        result["timestamp_basis"] = "source seconds relative to the first transaction; anchored at 1970-01-01 UTC"
        result["source_unit_policy"] = "source Amount feature is not reported as INR"
        return result


def convert_ieee_cis_train(
    transaction_path: str | Path,
    identity_path: str | Path,
    output_path: str | Path,
    *,
    row_limit: int | None = None,
    batch_size: int = 5_000,
) -> dict[str, object]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")
    pseudonymizer = pseudonymizer_from_environment()
    identity_rows: dict[str, dict[str, str]] = {}
    with Path(identity_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "TransactionID" not in reader.fieldnames:
            raise ValueError("IEEE-CIS identity CSV is missing TransactionID")
        if "DeviceInfo" not in reader.fieldnames:
            raise ValueError("IEEE-CIS identity CSV is missing DeviceInfo")
        for row in reader:
            transaction_id = (row.get("TransactionID") or "").strip()
            if not transaction_id:
                raise ValueError("IEEE-CIS identity row is missing TransactionID")
            if transaction_id in identity_rows:
                raise ValueError(f"duplicate IEEE-CIS identity TransactionID: {transaction_id}")
            identity_rows[transaction_id] = row
        identity_fields = tuple(reader.fieldnames)

    identity_matches = 0
    transaction_rows = 0
    missing_entity_values = {"card1": 0, "DeviceInfo": 0}
    joined_identity_ids: set[str] = set()
    with Path(transaction_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("IEEE-CIS transaction CSV is missing a header")
        required = {"TransactionID", "TransactionDT", "TransactionAmt", "isFraud", "card1"}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"IEEE-CIS transaction CSV is missing required columns: {sorted(missing)}")
        transaction_fields = tuple(reader.fieldnames)
        excluded_fields = {"TransactionID", "TransactionDT", "isFraud", "card1", "DeviceInfo"}
        all_fields = tuple(dict.fromkeys((*transaction_fields, *identity_fields)))
        feature_fields = tuple(name for name in all_fields if name not in excluded_fields)

        def examples() -> Iterable[TabularExample]:
            nonlocal identity_matches, transaction_rows
            for row_number, transaction in enumerate(reader, start=1):
                if row_limit is not None and row_number > row_limit:
                    break
                transaction_rows += 1
                transaction_id = (transaction.get("TransactionID") or "").strip()
                if not transaction_id:
                    raise ValueError("IEEE-CIS transaction row is missing TransactionID")
                identity = identity_rows.get(transaction_id)
                combined = dict(transaction)
                if identity is not None:
                    identity_matches += 1
                    joined_identity_ids.add(transaction_id)
                    if (identity.get("TransactionID") or "").strip() != transaction_id:
                        raise ValueError("IEEE-CIS identity row does not match TransactionID")
                    combined.update(identity)
                for field_name in feature_fields:
                    combined.setdefault(field_name, "")
                example = adapt_ieee_cis_row(
                    combined,
                    None,
                    epoch_origin=RELATIVE_EPOCH,
                    feature_fields=feature_fields,
                    entity_fields=(),
                    pseudonymizer=pseudonymizer,
                )
                entities: dict[str, str] = {}
                for field_name in ("card1", "DeviceInfo"):
                    raw_value = (combined.get(field_name) or "").strip()
                    if raw_value.casefold() in {"", "nan", "none", "null"}:
                        missing_entity_values[field_name] += 1
                        raw_value = f"missing:{transaction_id}:{field_name}"
                    else:
                        raw_value = f"value:{field_name}:{raw_value}"
                    entities[field_name] = pseudonymizer.account_id(f"ieee-cis\0{raw_value}")
                yield TabularExample(
                    dataset=example.dataset,
                    transaction_id=example.transaction_id,
                    timestamp=example.timestamp,
                    label=example.label,
                    features=example.features,
                    entity_keys=entities,
                )

        result = write_tabular_parquet_stream(examples(), output_path, batch_size=batch_size)
    result["timestamp_basis"] = (
        "TransactionDT seconds anchored at 1970-01-01 UTC for ordering; not a source calendar date"
    )
    result["source_unit_policy"] = (
        "TransactionAmt remains a source feature with unverified currency and is not reported as INR"
    )
    result["identity_rows"] = len(identity_rows)
    result["transactions_with_identity"] = identity_matches
    result["transactions_without_identity"] = transaction_rows - identity_matches
    result["identity_rows_without_transaction"] = (
        None if row_limit is not None else len(identity_rows) - len(joined_identity_ids)
    )
    result["missing_entity_values"] = missing_entity_values
    result["excluded_source_columns"] = sorted(excluded_fields)
    return result


def convert_baf_archive(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    row_limit: int | None = None,
    batch_size: int = 50_000,
) -> dict[str, dict[str, object]]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, object]] = {}
    with ZipFile(input_path) as archive:
        members = {
            Path(name).name.casefold(): name
            for name in archive.namelist()
            if Path(name).suffix.casefold() == ".csv"
        }
        for variant, expected_name in BAF_FILES.items():
            member = members.get(expected_name.casefold())
            if member is None:
                raise ValueError(f"BAF archive is missing {expected_name}")
            with archive.open(member) as binary:
                with TextIOWrapper(binary, encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames is None:
                        raise ValueError(f"{expected_name} is missing a header")
                    required = {"fraud_bool", "month"}
                    missing = required.difference(reader.fieldnames)
                    if missing:
                        raise ValueError(f"{expected_name} is missing required columns: {sorted(missing)}")
                    excluded_fields = {
                        name
                        for name in reader.fieldnames
                        if name.casefold() in {"fraud_bool", "month", "fraud_time", "x1", "x2"}
                    }
                    feature_fields = tuple(
                        name
                        for name in reader.fieldnames
                        if name not in excluded_fields
                    )

                    def examples() -> Iterable[TabularExample]:
                        for row_number, row in enumerate(reader, start=1):
                            if row_limit is not None and row_number > row_limit:
                                break
                            row["__fraudmesh_transaction_id"] = f"baf:{variant}:{row_number}"
                            yield adapt_baf_row(
                                row,
                                transaction_id_field="__fraudmesh_transaction_id",
                                normalized_timestamp=_baf_timestamp(row["month"]),
                                feature_fields=feature_fields,
                            )

                    # IDs include the variant and source row number.
                    result = write_tabular_parquet_stream(
                        examples(),
                        output_root / f"{variant}.parquet",
                        batch_size=batch_size,
                        check_unique_ids=False,
                    )
                    result["timestamp_basis"] = (
                        "source month index mapped to relative months from 1970-01; not a source calendar date"
                    )
                    result["excluded_source_columns"] = sorted(excluded_fields)
                    result["excluded_column_reason"] = (
                        "target/leakage, relative-time, and undocumented x1/x2 columns"
                    )
                    results[variant] = result
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Build full-data Phase 1 tabular Parquet artefacts.")
    parser.add_argument("--source", choices=("paysim", "ulb", "baf", "ieee-cis"), required=True)
    parser.add_argument("--input-path", type=Path, required=True)
    parser.add_argument("--identity-path", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.source == "paysim":
        result: object = convert_paysim(args.input_path, args.output_dir / "paysim.parquet")
    elif args.source == "ulb":
        result = convert_ulb(args.input_path, args.output_dir / "ulb.parquet")
    elif args.source == "ieee-cis":
        if args.identity_path is None:
            parser.error("ieee-cis requires --identity-path")
        result = convert_ieee_cis_train(
            args.input_path,
            args.identity_path,
            args.output_dir / "ieee-cis-train.parquet",
        )
    else:
        result = convert_baf_archive(args.input_path, args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
