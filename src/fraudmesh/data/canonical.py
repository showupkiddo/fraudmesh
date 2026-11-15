from __future__ import annotations

import os
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import pandera as pa


@dataclass(frozen=True)
class CanonicalTransaction:
    dataset: str
    transaction_id: str
    timestamp: str
    source_account: str
    destination_account: str
    source_institution: str
    destination_institution: str
    amount_inr: float
    original_amount: float
    original_currency: str
    channel: str
    edge_label: int
    ring_id: str | None = None
    typology: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset.strip() or not self.transaction_id.strip():
            raise ValueError("dataset and transaction_id are required")
        if not self.source_account.strip() or not self.destination_account.strip():
            raise ValueError("source and destination account IDs are required")
        if not self.source_institution.strip() or not self.destination_institution.strip():
            raise ValueError("source and destination institutions are required")
        if not self.original_currency.strip() or not self.channel.strip():
            raise ValueError("original currency and channel are required")
        if (
            not math.isfinite(self.amount_inr)
            or not math.isfinite(self.original_amount)
            or self.amount_inr < 0
            or self.original_amount < 0
        ):
            raise ValueError("transaction amounts must be finite and non-negative")
        if self.edge_label not in {0, 1}:
            raise ValueError("edge_label must be 0 or 1")
        try:
            parsed = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid ISO timestamp: {self.timestamp}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        offset = parsed.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must be normalized to UTC")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["timestamp"] = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        return record


@dataclass(frozen=True)
class TabularExample:
    dataset: str
    transaction_id: str
    timestamp: str
    label: int
    features: dict[str, str | float | int | bool | None]
    entity_keys: dict[str, str]


@dataclass(frozen=True)
class DataCard:
    dataset: str
    priority: str
    source_url: str
    licence: str
    licence_status: str
    download_date: str
    row_count: str
    column_count: str
    label_definition: str
    known_quirks: str
    intended_use: str
    prohibited_use: str


class CanonicalSchema:
    REQUIRED_FIELDS = (
        "dataset",
        "transaction_id",
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "amount_inr",
        "original_amount",
        "original_currency",
        "channel",
        "edge_label",
    )

    _schema = pa.DataFrameSchema(
        {
            "dataset": pa.Column(str, nullable=False),
            "transaction_id": pa.Column(str, nullable=False),
            "timestamp": pa.Column(pd.DatetimeTZDtype(unit="ns", tz="UTC"), nullable=False),
            "source_account": pa.Column(str, nullable=False),
            "destination_account": pa.Column(str, nullable=False),
            "source_institution": pa.Column(str, nullable=False),
            "destination_institution": pa.Column(str, nullable=False),
            "amount_inr": pa.Column(float, checks=pa.Check.ge(0), nullable=False),
            "original_amount": pa.Column(float, checks=pa.Check.ge(0), nullable=False),
            "original_currency": pa.Column(str, nullable=False),
            "channel": pa.Column(str, nullable=False),
            "edge_label": pa.Column(int, checks=pa.Check.isin([0, 1]), nullable=False),
            "ring_id": pa.Column(str, nullable=True),
            "typology": pa.Column(str, nullable=True),
        },
        strict=True,
        coerce=True,
    )

    @classmethod
    def validate_records(cls, records: list[CanonicalTransaction]) -> pd.DataFrame:
        frame = pd.DataFrame([record.to_record() for record in records])
        if frame.empty:
            raise ValueError("canonical dataset must contain at least one row")
        return cls._schema.validate(frame, lazy=True)


_LEAKAGE_COLUMNS = {
    "paysim": {"isfraud", "isflaggedfraud"},
    "ieee-cis": {"isfraud", "transactionid"},
    "baf": {"fraud_bool", "fraud_time"},
    "ulb": {"class"},
}


def audit_feature_columns(dataset: str, feature_columns: list[str]) -> list[str]:
    forbidden = {
        re.sub(r"[^a-z0-9]", "", column.casefold())
        for column in _LEAKAGE_COLUMNS.get(dataset.casefold(), set())
    }
    return [
        column
        for column in feature_columns
        if re.sub(r"[^a-z0-9]", "", column.casefold()) in forbidden
    ]


def require_no_label_leakage(dataset: str, feature_columns: list[str]) -> None:
    leaked = audit_feature_columns(dataset, feature_columns)
    if leaked:
        raise ValueError(f"{dataset} feature list includes label/leakage columns: {leaked}")


def parse_utc_timestamp(value: str, *, naive_timezone: timezone | None = None) -> str:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if naive_timezone is None:
            raise ValueError("timezone-naive source timestamp requires an explicit timezone")
        parsed = parsed.replace(tzinfo=naive_timezone)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def pseudonymizer_from_environment() -> "Pseudonymizer":
    key = os.environ.get("FRAUDMESH_PSEUDONYMIZATION_KEY")
    if not key:
        raise RuntimeError("FRAUDMESH_PSEUDONYMIZATION_KEY must be configured outside the repository")
    return Pseudonymizer(key.encode("utf-8"))


class Pseudonymizer:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("pseudonymization key must contain at least 32 bytes")
        self._key = key

    def account_id(self, raw_account_id: str) -> str:
        import hashlib
        import hmac

        normalized = raw_account_id.strip()
        if not normalized:
            raise ValueError("account ID cannot be empty")
        digest = hmac.new(self._key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"acct_{digest}"
