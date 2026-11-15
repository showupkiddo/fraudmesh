from __future__ import annotations

from csv import DictReader
from pathlib import Path

from .canonical import CanonicalSchema, CanonicalTransaction, DataCard

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "fraud_fixture.csv"


def build_fixture_transactions() -> list[CanonicalTransaction]:
    transactions: list[CanonicalTransaction] = []
    with FIXTURE_PATH.open("r", encoding="utf-8", newline="") as handle:
        reader = DictReader(handle)
        for row in reader:
            transactions.append(
                CanonicalTransaction(
                    transaction_id=row["transaction_id"],
                    timestamp=row["timestamp"],
                    source_account=row["source_account"],
                    destination_account=row["destination_account"],
                    source_institution=row["source_institution"],
                    destination_institution=row["destination_institution"],
                    amount=float(row["amount"]),
                    amount_currency=row.get("amount_currency", "USD"),
                    channel=row.get("channel", "wire"),
                    edge_label=int(row.get("edge_label", 0)),
                    ring_id=row.get("ring_id"),
                    typology=row.get("typology"),
                )
            )
    return transactions


def validate_dataset(records: list[CanonicalTransaction]) -> list[str]:
    issues: list[str] = []
    seen_ids: set[str] = set()
    for record in records:
        if record.transaction_id in seen_ids:
            issues.append(f"duplicate transaction_id: {record.transaction_id}")
        seen_ids.add(record.transaction_id)
        for issue in CanonicalSchema.validate_record(record):
            issues.append(f"{record.transaction_id}: {issue}")
    return issues


def _dataset_card(dataset: str, url: str, licence: str, row_count: str, label_definition: str) -> DataCard:
    return DataCard(
        dataset=dataset,
        source_url=url,
        licence=licence,
        download_date="not yet downloaded",
        row_count=row_count,
        label_definition=label_definition,
        known_quirks="pending dataset review",
        intended_use="phase-1 canonical schema validation and model planning",
        disallowed_use="not for production deployment without explicit data-access review",
    )


DATASET_CATALOG = (
    _dataset_card(
        "AMLworld HI-Small",
        "https://www.ibm.com/products/financial-services-asset-management",
        "research-use with institution-specific access review",
        "not yet downloaded",
        "ring pattern files supply laundering instance labels; edge labels are provided by the source dataset",
    ),
    _dataset_card(
        "AMLworld LI-Small",
        "https://www.ibm.com/products/financial-services-asset-management",
        "research-use with institution-specific access review",
        "not yet downloaded",
        "low-incident variant for transfer and ring recall benchmarking",
    ),
    _dataset_card(
        "SAML-D",
        "pending",
        "pending licence review",
        "not yet downloaded",
        "money-laundering graph labels designed for graph benchmark comparisons",
    ),
    _dataset_card(
        "PaySim",
        "pending Kaggle access",
        "pending licence review",
        "not yet downloaded",
        "synthetic payment graph with transaction-level fraud labels",
    ),
    _dataset_card(
        "IEEE-CIS",
        "pending Kaggle access and competition rules acceptance",
        "competition terms apply",
        "not yet downloaded",
        "tabular fraud detection labels for transaction-level scoring",
    ),
    _dataset_card(
        "BAF",
        "pending",
        "pending licence review",
        "not yet downloaded",
        "banking transaction features for tabular baseline evaluation",
    ),
    _dataset_card(
        "ULB",
        "pending",
        "pending licence review",
        "not yet downloaded",
        "anonymised tabular credit-card benchmark; not a graph-native dataset",
    ),
    _dataset_card(
        "Elliptic++",
        "pending",
        "pending licence review",
        "not yet downloaded",
        "out-of-domain graph benchmark with transaction and account labels",
    ),
)
