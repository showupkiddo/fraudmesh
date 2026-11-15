from fraudmesh.data import DATASET_CATALOG, build_fixture_transactions, validate_dataset


def test_fixture_transactions_are_valid() -> None:
    transactions = build_fixture_transactions()
    assert len(transactions) == 15
    assert transactions[0].transaction_id == "TXN_001"
    assert transactions[0].edge_label == 0
    assert validate_dataset(transactions) == []


def test_dataset_catalog_contains_primary_sources() -> None:
    names = [card.dataset for card in DATASET_CATALOG]
    assert "AMLworld HI-Small" in names
    assert "AMLworld LI-Small" in names
    assert "IEEE-CIS" in names
    assert "ULB" in names
