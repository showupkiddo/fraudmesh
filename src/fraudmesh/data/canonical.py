from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CanonicalTransaction:
    transaction_id: str
    timestamp: str
    source_account: str
    destination_account: str
    source_institution: str
    destination_institution: str
    amount: float
    amount_currency: str = "USD"
    channel: str = "wire"
    edge_label: int = 0
    ring_id: str | None = None
    typology: str | None = None

    def __post_init__(self) -> None:
        if not self.transaction_id:
            raise ValueError("transaction_id is required")
        if not self.source_account or not self.destination_account:
            raise ValueError("source and destination accounts are required")
        if self.amount < 0:
            raise ValueError("amount cannot be negative")
        try:
            datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid ISO timestamp: {self.timestamp}") from exc


@dataclass(frozen=True)
class DataCard:
    dataset: str
    source_url: str
    licence: str
    download_date: str
    row_count: str
    label_definition: str
    known_quirks: str
    intended_use: str
    disallowed_use: str


class CanonicalSchema:
    REQUIRED_FIELDS = (
        "transaction_id",
        "timestamp",
        "source_account",
        "destination_account",
        "source_institution",
        "destination_institution",
        "amount",
        "amount_currency",
        "channel",
        "edge_label",
    )

    @classmethod
    def validate_record(cls, record: CanonicalTransaction) -> list[str]:
        issues: list[str] = []
        if record.source_institution == record.destination_institution and record.edge_label == 1:
            issues.append("self-transfers should not be flagged as laundering edges")
        if record.amount <= 0:
            issues.append("amount must be strictly positive for a transaction")
        if record.edge_label not in {0, 1}:
            issues.append("edge_label must be 0 or 1")
        return issues
