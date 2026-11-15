from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Iterable, Iterator, Mapping, TextIO
from zipfile import ZipFile, is_zipfile

import pyarrow as pa
import pyarrow.parquet as pq
from pandera.errors import SchemaError, SchemaErrors

from .canonical import (
    CanonicalSchema,
    CanonicalTransaction,
    DataCard,
    Pseudonymizer,
    TabularExample,
    audit_feature_columns,
    parse_utc_timestamp,
    require_no_label_leakage,
)

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "fraud_fixture.csv"
AMLWORLD_URL = (
    "https://www.kaggle.com/datasets/ealtman2019/"
    "ibm-transactions-for-anti-money-laundering-aml"
)


@dataclass(frozen=True)
class CurrencyRateTable:
    base_currency: str
    units_per_source_unit: Mapping[str, float]
    source: str
    rates_by_year: Mapping[tuple[str, int], float] = dataclass_field(default_factory=dict)

    def __post_init__(self) -> None:
        base = self.base_currency.upper()
        if base != "INR":
            raise ValueError("canonical currency-rate tables must use INR as the base currency")
        normalized_rates: dict[str, float] = {}
        for currency, rate in self.units_per_source_unit.items():
            code = currency.strip().upper()
            if code in normalized_rates:
                raise ValueError(f"duplicate currency code after normalization: {code}")
            normalized_rates[code] = rate
        normalized_year_rates: dict[tuple[str, int], float] = {}
        for (currency, year), rate in self.rates_by_year.items():
            code = currency.strip().upper()
            key = (code, year)
            if key in normalized_year_rates:
                raise ValueError(f"duplicate rate for {code} in {year}")
            normalized_year_rates[key] = rate
        if not self.source.strip():
            raise ValueError("currency-rate source must be documented")
        if normalized_rates.get(base, 1.0) != 1.0:
            raise ValueError(f"{base} must have an explicit rate of 1.0")
        for currency, rate in normalized_rates.items():
            if not currency.strip() or not math.isfinite(rate) or rate <= 0:
                raise ValueError("currency rates must have non-empty codes and positive finite values")
        years = {year for _, year in normalized_year_rates}
        if base not in normalized_rates and not years:
            raise ValueError(f"{base} must have an explicit rate of 1.0")
        if any(normalized_year_rates.get((base, year)) != 1.0 for year in years):
            raise ValueError(f"{base} must have an explicit rate of 1.0 for each year")
        for (currency, year), rate in normalized_year_rates.items():
            if not currency or year < 1 or not math.isfinite(rate) or rate <= 0:
                raise ValueError("yearly currency rates must have valid codes, years, and positive values")
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "units_per_source_unit", normalized_rates)
        object.__setattr__(self, "rates_by_year", normalized_year_rates)

    def convert(self, amount: float, currency: str, *, year: int | None = None) -> float:
        code = currency.strip().upper()
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("amount must be finite and non-negative")
        if year is not None and (code, year) in self.rates_by_year:
            rate = self.rates_by_year[(code, year)]
        elif code in self.units_per_source_unit:
            rate = self.units_per_source_unit[code]
        elif any(rate_currency == code for rate_currency, _ in self.rates_by_year):
            if year is None:
                raise ValueError(f"a year is required for the approved {self.base_currency} rate for {code}")
            raise ValueError(f"no approved {self.base_currency} conversion rate for {code} in {year}")
        else:
            raise ValueError(f"no approved {self.base_currency} conversion rate for {code}")
        return amount * rate


def load_currency_rates_csv(path: str | Path) -> CurrencyRateTable:
    required = {"currency", "base_currency", "units_per_source_unit", "source"}
    rates: dict[str, float] = {}
    rates_by_year: dict[tuple[str, int], float] = {}
    base_currency: str | None = None
    sources: set[str] = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"currency-rate CSV must contain columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            currency = (row["currency"] or "").strip().upper()
            row_base = (row["base_currency"] or "").strip().upper()
            source = (row["source"] or "").strip()
            if not currency or not row_base or not source:
                raise ValueError(f"{path}:{line_number}: currency, base_currency, and source are required")
            if base_currency is not None and row_base != base_currency:
                raise ValueError(f"{path}:{line_number}: mixed base currencies are not allowed")
            base_currency = row_base
            sources.add(source)
            try:
                rate = float(row["units_per_source_unit"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_number}: invalid conversion rate") from exc
            year_text = (row.get("year") or "").strip()
            if year_text:
                try:
                    year = int(year_text)
                except ValueError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid rate year") from exc
                key = (currency, year)
                if key in rates_by_year:
                    raise ValueError(f"{path}:{line_number}: duplicate rate for {currency} in {year}")
                rates_by_year[key] = rate
            else:
                if currency in rates:
                    raise ValueError(f"{path}:{line_number}: duplicate rate for {currency}")
                rates[currency] = rate
    if (not rates and not rates_by_year) or base_currency is None:
        raise ValueError("currency-rate CSV has no rates")
    return CurrencyRateTable(base_currency, rates, "; ".join(sorted(sources)), rates_by_year)


def load_ring_labels_csv(
    path: str | Path,
    *,
    transaction_id_field: str,
    ring_id_field: str,
    typology_field: str,
) -> dict[str, tuple[str, str]]:
    labels: dict[str, tuple[str, str]] = {}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {transaction_id_field, ring_id_field, typology_field}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"ring-label CSV must contain columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            transaction_id = (row[transaction_id_field] or "").strip()
            ring_id = (row[ring_id_field] or "").strip()
            typology = (row[typology_field] or "").strip()
            if not transaction_id or not ring_id or not typology:
                raise ValueError(f"{path}:{line_number}: ring label fields cannot be empty")
            if transaction_id in labels:
                raise ValueError(f"{path}:{line_number}: duplicate transaction label {transaction_id}")
            labels[transaction_id] = (ring_id, typology)
    if not labels:
        raise ValueError("ring-label CSV has no records")
    return labels


def build_fixture_transactions() -> list[CanonicalTransaction]:
    transactions: list[CanonicalTransaction] = []
    with FIXTURE_PATH.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            amount = float(row["amount"])
            currency = row.get("amount_currency", "INR").strip().upper()
            if currency != "INR":
                raise ValueError("fixture amounts must already be denominated in INR")
            transactions.append(
                CanonicalTransaction(
                    dataset="fixture",
                    transaction_id=row["transaction_id"],
                    timestamp=parse_utc_timestamp(row["timestamp"]),
                    source_account=row["source_account"],
                    destination_account=row["destination_account"],
                    source_institution=row["source_institution"],
                    destination_institution=row["destination_institution"],
                    amount_inr=amount,
                    original_amount=amount,
                    original_currency=currency,
                    channel=row.get("channel", "other"),
                    edge_label=int(row.get("edge_label", 0)),
                    ring_id=row.get("ring_id") or None,
                    typology=row.get("typology") or None,
                )
            )
    return transactions


def validate_dataset(records: list[CanonicalTransaction]) -> list[str]:
    issues: list[str] = []
    seen_ids: set[tuple[str, str]] = set()
    for record in records:
        key = (record.dataset, record.transaction_id)
        if key in seen_ids:
            issues.append(f"duplicate transaction_id: {record.dataset}/{record.transaction_id}")
        seen_ids.add(key)
    if issues:
        return issues
    try:
        CanonicalSchema.validate_records(records)
    except (SchemaError, SchemaErrors) as exc:
        issues.append(str(exc))
    return issues


def _normalized_columns(row: Mapping[str, str]) -> dict[str, str]:
    return {re.sub(r"[^a-z0-9]", "", key.casefold()): value for key, value in row.items()}


def _field(row: Mapping[str, str], *names: str) -> str:
    normalized = _normalized_columns(row)
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.casefold())
        if key in normalized:
            return normalized[key].strip()
    raise ValueError(f"missing required source column; expected one of {names}")


@contextmanager
def _open_csv_text(path: str | Path) -> Iterator[TextIO]:
    source_path = Path(path)
    if is_zipfile(source_path):
        with ZipFile(source_path) as archive:
            members = [name for name in archive.namelist() if Path(name).suffix.casefold() == ".csv"]
            if len(members) != 1:
                raise ValueError(f"{source_path}: expected exactly one CSV member, found {len(members)}")
            with archive.open(members[0]) as binary:
                with TextIOWrapper(binary, encoding="utf-8-sig", newline="") as handle:
                    yield handle
        return
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield handle


def _label(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "laundering", "fraud"}:
        return 1
    if normalized in {"0", "false", "no", "legitimate", "normal"}:
        return 0
    raise ValueError(f"unsupported binary label: {value!r}")


_CURRENCY_CODES = {
    "albanianlek": "ALL",
    "australiandollar": "AUD",
    "bitcoin": "BTC",
    "brazilreal": "BRL",
    "canadiandollar": "CAD",
    "chineseyuan": "CNY",
    "dirham": "AED",
    "euro": "EUR",
    "indianrupee": "INR",
    "mexicanpeso": "MXN",
    "moroccandirham": "MAD",
    "naira": "NGN",
    "pakistanirupee": "PKR",
    "ruble": "RUB",
    "rupee": "INR",
    "saudiriyal": "SAR",
    "shekel": "ILS",
    "swissfranc": "CHF",
    "turkishlira": "TRY",
    "ukpound": "GBP",
    "ukpounds": "GBP",
    "usdollar": "USD",
    "yen": "JPY",
    "yuan": "CNY",
}


def _currency_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    return _CURRENCY_CODES.get(normalized, value.strip().upper())


def _amlworld_timestamp(value: str) -> str:
    try:
        return parse_utc_timestamp(value, naive_timezone=timezone.utc)
    except ValueError as iso_error:
        try:
            parsed = datetime.strptime(value.strip(), "%Y/%m/%d %H:%M")
        except ValueError:
            raise iso_error
        return parsed.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _channel(value: str) -> str:
    normalized = value.strip().casefold().replace("-", " ").replace("_", " ")
    if "wire" in normalized:
        return "wire"
    if "card" in normalized:
        return "card"
    if "ach" in normalized or "automated clearing" in normalized:
        return "ach"
    if "cash" in normalized:
        return "cash"
    if "mobile" in normalized or "upi" in normalized:
        return "mobile_money"
    return "other"


def amlworld_header_indices(header: list[str]) -> dict[str, int]:
    normalized = [re.sub(r"[^a-z0-9]", "", name.casefold()) for name in header]

    def find(*aliases: str, occurrence: int = 0) -> int:
        choices = {re.sub(r"[^a-z0-9]", "", item.casefold()) for item in aliases}
        matches = [index for index, name in enumerate(normalized) if name in choices]
        if len(matches) <= occurrence:
            raise ValueError(f"AMLworld CSV is missing column occurrence {occurrence}: {aliases}")
        return matches[occurrence]

    return {
        "timestamp": find("Timestamp"),
        "source_institution": find("From Bank", "From Institution"),
        "source_account": find("Account", "From Account", occurrence=0),
        "destination_institution": find("To Bank", "To Institution"),
        "destination_account": find("Account", "To Account", occurrence=1),
        "amount": find("Amount Paid"),
        "currency": find("Payment Currency"),
        "channel": find("Payment Format"),
        "edge_label": find("Is Laundering"),
    }


def iter_amlworld_rows(path: str | Path) -> Iterator[dict[str, str]]:
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"empty AMLworld source file: {source_path}") from exc
        indices = amlworld_header_indices(header)
        for line_number, values in enumerate(reader, start=2):
            if not values or all(not value.strip() for value in values):
                continue
            if len(values) != len(header):
                raise ValueError(
                    f"{source_path}:{line_number}: expected {len(header)} columns, got {len(values)}"
                )
            row = {name: values[index] for name, index in indices.items()}
            row["transaction_id"] = f"{source_path.stem}:{line_number}"
            row["__source_signature"] = json.dumps(values, separators=(",", ":"), ensure_ascii=False)
            yield row


def load_amlworld_pattern_signatures(
    path: str | Path,
    *,
    dataset: str,
) -> dict[str, tuple[str, str]]:
    labels: dict[str, tuple[str, str]] = {}
    ring_number = 0
    current_label: tuple[str, str] | None = None
    ring_rows = 0

    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            if text.startswith("BEGIN LAUNDERING ATTEMPT - "):
                if current_label is not None:
                    raise ValueError(f"{path}:{line_number}: nested laundering pattern")
                description = text.removeprefix("BEGIN LAUNDERING ATTEMPT - ").split(":", 1)[0].strip()
                if not description:
                    raise ValueError(f"{path}:{line_number}: laundering pattern has no typology")
                ring_number += 1
                current_label = (f"{dataset}:pattern-{ring_number:05d}", description)
                ring_rows = 0
                continue
            if text.startswith("END LAUNDERING ATTEMPT"):
                if current_label is None or ring_rows == 0:
                    raise ValueError(f"{path}:{line_number}: unmatched or empty laundering pattern")
                current_label = None
                continue
            if current_label is None:
                raise ValueError(f"{path}:{line_number}: transaction row outside a laundering pattern")

            values = next(csv.reader([line]))
            if len(values) != 11:
                raise ValueError(
                    f"{path}:{line_number}: expected 11 pattern fields, got {len(values)}"
                )
            signature = json.dumps(values, separators=(",", ":"), ensure_ascii=False)
            existing = labels.get(signature)
            if existing is not None and existing != current_label:
                raise ValueError(f"{path}:{line_number}: transaction occurs in multiple patterns")
            labels[signature] = current_label
            ring_rows += 1

    if current_label is not None:
        raise ValueError(f"{path}: unterminated laundering pattern")
    if not labels:
        raise ValueError(f"{path}: no laundering transactions found")
    return labels


def normalize_amlworld_row(
    row: Mapping[str, str],
    *,
    dataset: str,
    rates: CurrencyRateTable,
    pseudonymizer: Pseudonymizer,
    ring_labels: Mapping[str, tuple[str, str]] | None = None,
) -> CanonicalTransaction:
    source_bank = _field(row, "source_institution")
    destination_bank = _field(row, "destination_institution")
    source_account = _field(row, "source_account")
    destination_account = _field(row, "destination_account")
    source_amount = float(_field(row, "amount"))
    source_currency = _currency_code(_field(row, "currency"))
    transaction_id = _field(row, "transaction_id", "transaction id", "id")
    ring_id, typology = (ring_labels or {}).get(transaction_id, (None, None))
    timestamp = _amlworld_timestamp(_field(row, "timestamp"))
    year = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).year
    return CanonicalTransaction(
        dataset=dataset,
        transaction_id=transaction_id,
        timestamp=timestamp,
        source_account=pseudonymizer.account_id(f"{source_bank}\0{source_account}"),
        destination_account=pseudonymizer.account_id(f"{destination_bank}\0{destination_account}"),
        source_institution=source_bank,
        destination_institution=destination_bank,
        amount_inr=rates.convert(source_amount, source_currency, year=year),
        original_amount=source_amount,
        original_currency=source_currency,
        channel=_channel(_field(row, "channel")),
        edge_label=_label(_field(row, "edge_label")),
        ring_id=ring_id,
        typology=typology,
    )


def convert_amlworld_csv(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    dataset: str,
    rates: CurrencyRateTable,
    pseudonymizer: Pseudonymizer,
    ring_labels: Mapping[str, tuple[str, str]] | None = None,
    pattern_path: str | Path | None = None,
    row_limit: int | None = None,
    batch_size: int = 50_000,
) -> tuple[int, str]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")
    if pattern_path is not None and ring_labels is not None:
        raise ValueError("provide either pattern_path or ring_labels, not both")
    pattern_labels = (
        load_amlworld_pattern_signatures(pattern_path, dataset=dataset)
        if pattern_path is not None
        else None
    )
    matched_patterns: set[str] = set()

    def normalized_rows() -> Iterator[CanonicalTransaction]:
        for index, row in enumerate(iter_amlworld_rows(input_path), start=1):
            transaction_id = row["transaction_id"]
            signature = row.pop("__source_signature")
            row_ring_labels = ring_labels
            if pattern_labels is not None:
                pattern_label = pattern_labels.get(signature)
                if pattern_label is not None:
                    if _label(row["edge_label"]) != 1:
                        raise ValueError(f"{transaction_id}: laundering pattern row has a negative edge label")
                    if signature in matched_patterns:
                        raise ValueError(f"{transaction_id}: duplicate source row makes ring match ambiguous")
                    matched_patterns.add(signature)
                    row_ring_labels = {transaction_id: pattern_label}
            yield normalize_amlworld_row(
                row,
                dataset=dataset,
                rates=rates,
                pseudonymizer=pseudonymizer,
                ring_labels=row_ring_labels,
            )
            if row_limit is not None and index >= row_limit:
                break
        if pattern_labels is not None and row_limit is None:
            unmatched = len(pattern_labels) - len(matched_patterns)
            if unmatched:
                raise ValueError(f"{unmatched} AMLworld pattern rows were not found in the transaction file")

    return write_partitioned_parquet(normalized_rows(), output_dir, batch_size=batch_size)


def adapt_tabular_row(
    row: Mapping[str, str],
    *,
    dataset: str,
    transaction_id_field: str,
    timestamp_field: str,
    label_field: str,
    feature_fields: tuple[str, ...],
    entity_fields: tuple[str, ...] = (),
    pseudonymizer: Pseudonymizer | None = None,
) -> TabularExample:
    require_no_label_leakage(dataset, list(feature_fields))
    if label_field in feature_fields:
        raise ValueError(f"label field {label_field!r} cannot be a model feature")
    timestamp = parse_utc_timestamp(_field(row, timestamp_field), naive_timezone=timezone.utc)
    features: dict[str, str | float | int | bool | None] = {}
    for field in feature_fields:
        features[field] = row[field]
    entity_keys: dict[str, str] = {}
    for field in entity_fields:
        raw_value = row.get(field, "").strip()
        if raw_value:
            if pseudonymizer is None:
                raise ValueError("entity fields require a keyed pseudonymizer")
            entity_keys[field] = pseudonymizer.account_id(raw_value)
    return TabularExample(
        dataset=dataset,
        transaction_id=_field(row, transaction_id_field),
        timestamp=timestamp,
        label=_label(_field(row, label_field)),
        features=features,
        entity_keys=entity_keys,
    )


def _relative_timestamp(value: str, *, origin: datetime, unit_seconds: float) -> str:
    if origin.tzinfo is None or origin.utcoffset() is None:
        raise ValueError("relative time origin must be timezone-aware")
    offset = float(value)
    if not math.isfinite(offset) or offset < 0:
        raise ValueError("relative time value must be finite and non-negative")
    return (origin.astimezone(timezone.utc) + timedelta(seconds=offset * unit_seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def adapt_paysim_tabular_row(
    row: Mapping[str, str],
    *,
    row_number: int,
    epoch_origin: datetime,
    feature_fields: tuple[str, ...],
    pseudonymizer: Pseudonymizer,
) -> TabularExample:
    if row_number < 1:
        raise ValueError("row_number must be a positive source-file row number")
    prepared = dict(row)
    prepared.setdefault("transaction_id", f"paysim:{row_number}")
    prepared["__fraudmesh_timestamp"] = _relative_timestamp(
        _field(row, "step"), origin=epoch_origin, unit_seconds=3600
    )
    return adapt_tabular_row(
        prepared,
        dataset="paysim",
        transaction_id_field="transaction_id",
        timestamp_field="__fraudmesh_timestamp",
        label_field="isFraud",
        feature_fields=feature_fields,
        entity_fields=("nameOrig", "nameDest"),
        pseudonymizer=pseudonymizer,
    )


def adapt_ieee_cis_row(
    transaction: Mapping[str, str],
    identity: Mapping[str, str] | None,
    *,
    epoch_origin: datetime,
    feature_fields: tuple[str, ...],
    entity_fields: tuple[str, ...] = ("card1", "DeviceInfo"),
    pseudonymizer: Pseudonymizer,
) -> TabularExample:
    transaction_id = _field(transaction, "TransactionID")
    combined = dict(transaction)
    if identity is not None:
        if _field(identity, "TransactionID") != transaction_id:
            raise ValueError("IEEE-CIS identity row does not match TransactionID")
        combined.update(identity)
    combined["__fraudmesh_timestamp"] = _relative_timestamp(
        _field(transaction, "TransactionDT"), origin=epoch_origin, unit_seconds=1
    )
    return adapt_tabular_row(
        combined,
        dataset="ieee-cis",
        transaction_id_field="TransactionID",
        timestamp_field="__fraudmesh_timestamp",
        label_field="isFraud",
        feature_fields=feature_fields,
        entity_fields=entity_fields,
        pseudonymizer=pseudonymizer,
    )


def adapt_ulb_row(
    row: Mapping[str, str],
    *,
    row_number: int,
    epoch_origin: datetime,
    feature_fields: tuple[str, ...],
) -> TabularExample:
    if row_number < 1:
        raise ValueError("row_number must be a positive source-file row number")
    prepared = dict(row)
    prepared["__fraudmesh_timestamp"] = _relative_timestamp(
        _field(row, "Time"), origin=epoch_origin, unit_seconds=1
    )
    prepared["__fraudmesh_id"] = f"ulb:{row_number}"
    return adapt_tabular_row(
        prepared,
        dataset="ulb",
        transaction_id_field="__fraudmesh_id",
        timestamp_field="__fraudmesh_timestamp",
        label_field="Class",
        feature_fields=feature_fields,
    )


def adapt_baf_row(
    row: Mapping[str, str],
    *,
    transaction_id_field: str,
    normalized_timestamp: str,
    feature_fields: tuple[str, ...],
    entity_fields: tuple[str, ...] = (),
    pseudonymizer: Pseudonymizer | None = None,
) -> TabularExample:
    prepared = dict(row)
    prepared["__fraudmesh_timestamp"] = parse_utc_timestamp(
        normalized_timestamp, naive_timezone=timezone.utc
    )
    return adapt_tabular_row(
        prepared,
        dataset="baf",
        transaction_id_field=transaction_id_field,
        timestamp_field="__fraudmesh_timestamp",
        label_field="fraud_bool",
        feature_fields=feature_fields,
        entity_fields=entity_fields,
        pseudonymizer=pseudonymizer,
    )


def normalize_samld_row(
    row: Mapping[str, str],
    *,
    dataset: str,
    transaction_id: str,
    column_map: Mapping[str, str],
    rates: CurrencyRateTable,
    pseudonymizer: Pseudonymizer,
    ring_labels: Mapping[str, tuple[str, str]] | None = None,
) -> CanonicalTransaction:
    required = {
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "amount",
        "currency",
        "channel",
        "edge_label",
    }
    missing = required.difference(column_map)
    if missing:
        raise ValueError(f"SAML-D column map is missing keys: {sorted(missing)}")
    mapped = {key: _field(row, source_name) for key, source_name in column_map.items()}
    timestamp = parse_utc_timestamp(mapped["timestamp"], naive_timezone=timezone.utc)
    year = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).year
    currency = _currency_code(mapped["currency"])
    amount = float(mapped["amount"])
    edge_label = _label(mapped["edge_label"])
    ring_id, ring_typology = (ring_labels or {}).get(transaction_id, (None, None))
    if ring_id is not None and not edge_label:
        raise ValueError(f"{transaction_id}: ring label assigned to a negative edge")
    raw_typology = mapped.get("typology", "").strip()
    source_typology: str | None = (
        raw_typology if raw_typology.casefold() not in {"", "normal", "none", "nan"} else None
    )
    return CanonicalTransaction(
        dataset=dataset,
        transaction_id=transaction_id,
        timestamp=timestamp,
        source_account=pseudonymizer.account_id(
            f"{mapped['source_institution']}\0{mapped['source_account']}"
        ),
        destination_account=pseudonymizer.account_id(
            f"{mapped['destination_institution']}\0{mapped['destination_account']}"
        ),
        source_institution=mapped["source_institution"],
        destination_institution=mapped["destination_institution"],
        amount_inr=rates.convert(amount, currency, year=year),
        original_amount=amount,
        original_currency=currency,
        channel=_channel(mapped["channel"]),
        edge_label=edge_label,
        ring_id=ring_id,
        typology=ring_typology if ring_typology is not None else (
            source_typology if edge_label else None
        ),
    )


def convert_samld_csv(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    column_map: Mapping[str, str],
    rates: CurrencyRateTable,
    pseudonymizer: Pseudonymizer,
    dataset: str = "samld",
    ring_labels: Mapping[str, tuple[str, str]] | None = None,
    row_limit: int | None = None,
    batch_size: int = 50_000,
) -> tuple[int, str]:
    if row_limit is not None and row_limit <= 0:
        raise ValueError("row_limit must be positive when provided")

    def normalized_rows() -> Iterator[CanonicalTransaction]:
        with _open_csv_text(input_path) as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=1):
                mapped_columns = column_map
                normalized_row = _normalized_columns(row)
                if "date" in normalized_row and "time" in normalized_row:
                    row = dict(row)
                    row["__fraudmesh_timestamp"] = f"{_field(row, 'date')}T{_field(row, 'time')}"
                    mapped_columns = {**column_map, "timestamp": "__fraudmesh_timestamp"}
                yield normalize_samld_row(
                    row,
                    dataset=dataset,
                    transaction_id=f"{dataset}:{row_number}",
                    column_map=mapped_columns,
                    rates=rates,
                    pseudonymizer=pseudonymizer,
                    ring_labels=ring_labels,
                )
                if row_limit is not None and row_number >= row_limit:
                    break

    return write_partitioned_parquet(normalized_rows(), output_dir, batch_size=batch_size)


def validate_tabular_examples(examples: list[TabularExample]) -> list[str]:
    if not examples:
        return ["tabular dataset must contain at least one example"]
    issues: list[str] = []
    seen_ids: set[tuple[str, str]] = set()
    expected_features = set(examples[0].features)
    expected_entities = set(examples[0].entity_keys)
    dataset = examples[0].dataset
    for example in examples:
        key = (example.dataset, example.transaction_id)
        if key in seen_ids:
            issues.append(f"duplicate tabular transaction_id: {example.dataset}/{example.transaction_id}")
        seen_ids.add(key)
        if example.dataset != dataset:
            issues.append("one tabular Parquet file cannot mix dataset schemas")
        if set(example.features) != expected_features or set(example.entity_keys) != expected_entities:
            issues.append("tabular examples do not share one feature/entity schema")
        if example.label not in {0, 1}:
            issues.append(f"{example.transaction_id}: label must be 0 or 1")
        leaked = audit_feature_columns(example.dataset, list(example.features))
        if leaked:
            issues.append(f"{example.transaction_id}: leakage columns used as features: {leaked}")
        try:
            parse_utc_timestamp(example.timestamp)
        except ValueError as exc:
            issues.append(f"{example.transaction_id}: {exc}")
        if any(not value.startswith("acct_") for value in example.entity_keys.values()):
            issues.append(f"{example.transaction_id}: entity keys must be keyed pseudonyms")
    return issues


def write_tabular_parquet(examples: list[TabularExample], output_path: str | Path) -> tuple[int, str]:
    issues = validate_tabular_examples(examples)
    if issues:
        raise ValueError(f"tabular validation failed: {issues}")
    reserved = {"dataset", "transaction_id", "timestamp", "label"}
    feature_names = set(examples[0].features)
    entity_names = {f"entity_{name}" for name in examples[0].entity_keys}
    collisions = reserved.intersection(feature_names) | feature_names.intersection(entity_names)
    if collisions:
        raise ValueError(f"tabular feature names collide with contract fields: {sorted(collisions)}")
    rows: list[dict[str, object]] = []
    for example in examples:
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
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd", version="2.6")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return len(rows), digest


_ARROW_SCHEMA = pa.schema(
    [
        pa.field("transaction_id", pa.string(), nullable=False),
        pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("source_account", pa.string(), nullable=False),
        pa.field("destination_account", pa.string(), nullable=False),
        pa.field("source_institution", pa.string(), nullable=False),
        pa.field("destination_institution", pa.string(), nullable=False),
        pa.field("amount_inr", pa.float64(), nullable=False),
        pa.field("original_amount", pa.float64(), nullable=False),
        pa.field("original_currency", pa.string(), nullable=False),
        pa.field("channel", pa.string(), nullable=False),
        pa.field("edge_label", pa.int8(), nullable=False),
        pa.field("ring_id", pa.string()),
        pa.field("typology", pa.string()),
    ]
)


def write_partitioned_parquet(
    records: Iterable[CanonicalTransaction],
    output_dir: str | Path,
    *,
    batch_size: int = 50_000,
) -> tuple[int, str]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    root = Path(output_dir)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"canonical output directory is not empty: {root}")
    buffers: dict[Path, list[CanonicalTransaction]] = {}
    part_numbers: dict[Path, int] = {}
    seen_ids: set[tuple[str, str]] = set()
    written = 0
    digest = hashlib.sha256()

    def flush(partition: Path, batch: list[CanonicalTransaction]) -> None:
        nonlocal written
        if not batch:
            return
        CanonicalSchema.validate_records(batch)
        partition.mkdir(parents=True, exist_ok=True)
        part = part_numbers.get(partition, 0)
        path = partition / f"part-{part:05d}.parquet"
        rows: list[dict[str, object]] = []
        for record in batch:
            row = record.to_record()
            row.pop("dataset")
            rows.append(row)
        table = pa.Table.from_pylist(rows, schema=_ARROW_SCHEMA)
        pq.write_table(table, path, compression="zstd", version="2.6")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        written += len(batch)
        part_numbers[partition] = part + 1
        batch.clear()

    for record in records:
        key = (record.dataset, record.transaction_id)
        if key in seen_ids:
            raise ValueError(f"duplicate transaction_id: {record.dataset}/{record.transaction_id}")
        seen_ids.add(key)
        year = datetime.fromisoformat(record.timestamp.replace("Z", "+00:00")).year
        partition = root / f"dataset={record.dataset}" / f"year={year}"
        batch = buffers.setdefault(partition, [])
        batch.append(record)
        if len(batch) >= batch_size:
            flush(partition, batch)

    for partition, rows in buffers.items():
        flush(partition, rows)
    if written == 0:
        raise ValueError("refusing to write an empty canonical dataset")
    return written, digest.hexdigest()


def _card(
    dataset: str,
    priority: str,
    url: str,
    label_definition: str,
    quirks: str,
    intended_use: str,
    prohibited_use: str,
    *,
    licence: str = "not yet verified; record the provider's terms before use",
    licence_status: str = "pending human review",
    download_date: str = "not yet recorded",
    row_count: str = "not yet measured",
    column_count: str = "not yet measured",
) -> DataCard:
    return DataCard(
        dataset=dataset,
        priority=priority,
        source_url=url,
        licence=licence,
        licence_status=licence_status,
        download_date=download_date,
        row_count=row_count,
        column_count=column_count,
        label_definition=label_definition,
        known_quirks=quirks,
        intended_use=intended_use,
        prohibited_use=prohibited_use,
    )


DATASET_CATALOG = (
    _card(
        "AMLworld HI-Small",
        "P0",
        AMLWORLD_URL,
        "Transaction laundering label plus laundering-pattern records for ring membership.",
        "Separate paid and received currencies; amount_inr uses Amount Paid and Payment Currency with year-specific rates.",
        "Primary graph model dataset and cross-institution ring evaluation.",
        "Do not infer ring labels by connected components or propagate labels.",
        row_count="5078345",
        column_count="11",
    ),
    _card(
        "AMLworld LI-Small",
        "P0",
        AMLWORLD_URL,
        "Transaction laundering label plus laundering-pattern records for ring membership.",
        "Low-incident variant; preserve patterns files; amount_inr uses Amount Paid and Payment Currency.",
        "Primary graph transfer and low-prevalence evaluation.",
        "Do not infer ring labels by connected components or propagate labels.",
        row_count="6924049",
        column_count="11",
    ),
    _card(
        "SAML-D",
        "P1",
        "https://www.kaggle.com/datasets/berkanoztas/synthetic-transaction-monitoring-dataset-aml",
        "Source transaction suspicious label and typology, subject to raw schema verification.",
        "Synthetic source; Date and Time are separate; payment currency is converted to amount_inr using annual rates.",
        "Second graph data source and schema-adapter stress test.",
        "Do not present generator-defined labels as real-world ground truth.",
        licence="CC-BY-NC-SA-4.0",
        licence_status="Kaggle metadata verified; terms reviewed by user",
        download_date="2026-11-15",
        row_count="9504852",
        column_count="12",
    ),
    _card(
        "PaySim",
        "P1",
        "https://www.kaggle.com/datasets/ealaxi/paysim1",
        "isFraud transaction label; isFlaggedFraud is excluded from model features.",
        "Synthetic mobile-money data; step is relative time; amount is a simulation-unit feature and is not reported as INR.",
        "M4 tabular benchmark and secondary schema exercise.",
        "Do not treat synthetic labels as real-world laundering-ring ground truth.",
        row_count="6362620",
        column_count="11",
    ),
    _card(
        "IEEE-CIS",
        "P1",
        "https://www.kaggle.com/competitions/ieee-fraud-detection",
        "isFraud transaction target; transaction/identity tables require a documented join.",
        "Competition access terms apply; TransactionDT is relative time; TransactionAmt currency is unverified and is not reported as INR.",
        "M4 tabular benchmark, with entity keys for history features where available.",
        "Do not claim money-flow ring detection from shared attributes.",
    ),
    _card(
        "BAF",
        "P1",
        "https://www.kaggle.com/datasets/sgpjesus/bank-account-fraud-dataset-neurips-2022",
        "fraud_bool application target; six variants are distributed separately.",
        "Synthetic benchmark with distribution variants and a month field; income is not treated as an INR amount.",
        "M4 distribution-shift and drift benchmark.",
        "Do not present application fraud as transaction-graph ring ground truth.",
        licence="CC-BY-NC-SA-4.0",
        licence_status="Kaggle metadata verified; terms reviewed by user",
        download_date="2026-11-15",
        row_count="1000000 per variant (Base and Variants I-V)",
        column_count="32 in Base, I, II, IV; 34 in III, V",
    ),
    _card(
        "ULB",
        "P1",
        "https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud",
        "Class is the transaction fraud target.",
        "Time, Amount, and anonymised PCA columns only; Amount currency is unspecified and is not reported as INR.",
        "Standalone M4 tabular sanity benchmark.",
        "Do not construct a money-flow graph or claim ring metrics.",
        licence="DbCL-1.0",
        licence_status="Kaggle metadata verified; terms reviewed by user",
        download_date="2026-11-15",
        row_count="284807",
        column_count="31",
    ),
)


def write_data_cards(output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(card) for card in DATASET_CATALOG]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
