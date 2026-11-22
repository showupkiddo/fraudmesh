from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest

from fraudmesh.data import (
    CurrencyRateTable,
    Pseudonymizer,
    adapt_baf_row,
    adapt_ieee_cis_row,
    adapt_paysim_tabular_row,
    adapt_tabular_row,
    adapt_ulb_row,
    audit_feature_columns,
    iter_amlworld_rows,
    load_currency_rates_csv,
    load_amlworld_pattern_signatures,
    load_ring_labels_csv,
    normalize_amlworld_row,
    normalize_samld_row,
    require_no_label_leakage,
    write_tabular_parquet,
    write_partitioned_parquet,
    convert_amlworld_csv,
    convert_samld_csv,
)


def test_pseudonyms_are_stable_across_clients_and_not_plaintext() -> None:
    key = b"k" * 32
    client_a = Pseudonymizer(key)
    client_b = Pseudonymizer(key)

    account_a = client_a.account_id("bank-1:account-7")
    account_b = client_b.account_id("bank-1:account-7")

    assert account_a == account_b
    assert "account-7" not in account_a
    assert account_a.startswith("acct_")


def test_amlworld_duplicate_account_headers_and_paid_currency_policy(
    tmp_path,
) -> None:
    source = tmp_path / "aml-sample.csv"
    source.write_text(
        "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
        "Amount Paid,Payment Currency,Payment Format,Is Laundering\n"
        "2022-01-02 03:04:05,bank-a,source-1,bank-b,dest-1,12,USD,10,EUR,Wire,1\n",
        encoding="utf-8",
    )
    rows = list(iter_amlworld_rows(source))
    rates = CurrencyRateTable("INR", {"INR": 1.0, "EUR": 1.2}, "reviewed fixture rates")
    record = normalize_amlworld_row(
        rows[0],
        dataset="amlworld-hi-small",
        rates=rates,
        pseudonymizer=Pseudonymizer(b"k" * 32),
        ring_labels={f"{source.stem}:2": ("ring-1", "cycle")},
    )

    assert record.source_institution == "bank-a"
    assert record.destination_institution == "bank-b"
    assert record.original_amount == 10.0
    assert record.original_currency == "EUR"
    assert record.amount_inr == 12.0
    assert record.ring_id == "ring-1"
    assert record.timestamp == "2022-01-02T03:04:05Z"


def test_amlworld_pattern_file_assigns_official_ring_and_typology(tmp_path) -> None:
    source = tmp_path / "HI-Small_Trans.csv"
    source_row = (
        "2022/09/01 00:06,021174,800737690,012,80011F990,2848.96,Euro,"
        "2848.96,Euro,ACH,1"
    )
    source.write_text(
        "Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,"
        "Amount Paid,Payment Currency,Payment Format,Is Laundering\n"
        + source_row
        + "\n",
        encoding="utf-8",
    )
    pattern_file = tmp_path / "HI-Small_Patterns.txt"
    pattern_file.write_text(
        "BEGIN LAUNDERING ATTEMPT - FAN-OUT: Max 16-degree Fan-Out\n"
        + source_row
        + "\nEND LAUNDERING ATTEMPT - FAN-OUT\n",
        encoding="utf-8",
    )

    rates = CurrencyRateTable("INR", {"INR": 1.0, "EUR": 1.2}, "reviewed fixture rates")
    count, _ = convert_amlworld_csv(
        source,
        tmp_path / "canonical",
        dataset="amlworld-hi-small",
        rates=rates,
        pseudonymizer=Pseudonymizer(b"k" * 32),
        pattern_path=pattern_file,
    )
    labels = load_amlworld_pattern_signatures(
        pattern_file,
        dataset="amlworld-hi-small",
    )
    table = ds.dataset(tmp_path / "canonical", format="parquet", partitioning="hive").to_table()

    assert count == 1
    assert len(labels) == 1
    assert table["ring_id"].to_pylist() == ["amlworld-hi-small:pattern-00001"]
    assert table["typology"].to_pylist() == ["FAN-OUT"]


def test_currency_conversion_fails_when_rate_is_missing() -> None:
    rates = CurrencyRateTable("INR", {"INR": 1.0}, "reviewed fixture rates")

    with pytest.raises(ValueError, match="no approved INR conversion rate"):
        rates.convert(2.0, "EUR")


def test_currency_conversion_uses_the_transaction_year() -> None:
    rates = CurrencyRateTable(
        "INR",
        {},
        "reviewed fixture rates",
        {
            ("INR", 2022): 1.0,
            ("USD", 2022): 80.0,
            ("INR", 2023): 1.0,
            ("USD", 2023): 82.0,
        },
    )

    assert rates.convert(2.0, "USD", year=2022) == 160.0
    assert rates.convert(2.0, "USD", year=2023) == 164.0
    with pytest.raises(ValueError, match="no approved INR conversion rate for USD in 2024"):
        rates.convert(2.0, "USD", year=2024)


def test_currency_rate_table_rejects_non_inr_base() -> None:
    with pytest.raises(ValueError, match="must use INR as the base currency"):
        CurrencyRateTable("USD", {"USD": 1.0}, "reviewed fixture rates")


def test_project_rate_table_covers_all_graph_source_currencies() -> None:
    rates_path = Path(__file__).resolve().parents[1] / "data" / "config" / "currency-rates.csv"
    rates = load_currency_rates_csv(rates_path)
    amlworld_currencies = {
        "AUD", "BTC", "BRL", "CAD", "EUR", "MXN", "RUB", "INR",
        "SAR", "ILS", "CHF", "GBP", "USD", "JPY", "CNY",
    }
    samld_currencies = {
        "ALL", "AED", "EUR", "INR", "MXN", "MAD", "NGN",
        "PKR", "CHF", "TRY", "GBP", "USD", "JPY",
    }

    assert rates.base_currency == "INR"
    for currency in amlworld_currencies:
        rates.convert(1.0, currency, year=2022)
    for currency in samld_currencies:
        for year in (2022, 2023):
            rates.convert(1.0, currency, year=year)


def test_reviewed_rate_and_pattern_label_csvs_are_loaded_explicitly(tmp_path) -> None:
    rates_path = tmp_path / "rates.csv"
    rates_path.write_text(
        "currency,base_currency,units_per_source_unit,source,year\n"
        "INR,INR,1.0,base-currency,2022\n"
        "EUR,INR,1.2,reviewed-source-v1,2022\n"
        "INR,INR,1.0,base-currency,2023\n"
        "EUR,INR,1.3,reviewed-source-v2,2023\n",
        encoding="utf-8",
    )
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text(
        "transaction_id,ring_id,typology\n"
        "tx-1,ring-1,cycle\n",
        encoding="utf-8",
    )

    rates = load_currency_rates_csv(rates_path)
    labels = load_ring_labels_csv(
        labels_path,
        transaction_id_field="transaction_id",
        ring_id_field="ring_id",
        typology_field="typology",
    )
    row = normalize_samld_row(
        {
            "time": "2022-01-02T03:04:05Z",
            "sender": "a-1",
            "receiver": "b-1",
            "sender_bank": "bank-a",
            "receiver_bank": "bank-b",
            "paid": "10",
            "currency": "EUR",
            "payment_type": "wire",
            "suspicious": "1",
        },
        dataset="samld",
        transaction_id="tx-1",
        column_map={
            "timestamp": "time",
            "source_account": "sender",
            "destination_account": "receiver",
            "source_institution": "sender_bank",
            "destination_institution": "receiver_bank",
            "amount": "paid",
            "currency": "currency",
            "channel": "payment_type",
            "edge_label": "suspicious",
        },
        rates=rates,
        pseudonymizer=Pseudonymizer(b"k" * 32),
        ring_labels=labels,
    )

    assert row.amount_inr == 12.0
    assert row.ring_id == "ring-1"
    assert row.typology == "cycle"


def test_samld_converter_combines_date_and_time_before_rate_lookup(tmp_path) -> None:
    source = tmp_path / "samld.zip"
    with ZipFile(source, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "SAML-D.csv",
            "Time,Date,Sender_account,Receiver_account,Sender_bank_location,"
            "Receiver_bank_location,Amount,Payment_currency,Payment_type,Is_laundering,"
            "Laundering_type\n"
            "10:35:19,2023-08-23,sender,receiver,UK,UK,10,Indian rupee,Wire,1,structuring\n",
        )
    rates = CurrencyRateTable(
        "INR",
        {},
        "reviewed fixture rates",
        {("INR", 2023): 1.0},
    )

    count, _ = convert_samld_csv(
        source,
        tmp_path / "canonical",
        column_map={
            "timestamp": "Date",
            "source_account": "Sender_account",
            "destination_account": "Receiver_account",
            "source_institution": "Sender_bank_location",
            "destination_institution": "Receiver_bank_location",
            "amount": "Amount",
            "currency": "Payment_currency",
            "channel": "Payment_type",
            "edge_label": "Is_laundering",
            "typology": "Laundering_type",
        },
        rates=rates,
        pseudonymizer=Pseudonymizer(b"k" * 32),
    )
    table = ds.dataset(tmp_path / "canonical", format="parquet", partitioning="hive").to_table()

    assert count == 1
    assert table["timestamp"].to_pylist()[0].isoformat() == "2023-08-23T10:35:19+00:00"
    assert table["transaction_id"].to_pylist() == ["samld:1"]
    assert table["amount_inr"].to_pylist() == [10.0]
    assert table["typology"].to_pylist() == ["structuring"]


def test_tabular_adapter_keeps_entity_ids_out_of_features_and_rejects_leakage() -> None:
    example = adapt_tabular_row(
        {
            "TransactionID": "t-1",
            "Timestamp": "2022-01-02T03:04:05Z",
            "isFraud": "1",
            "card1": "card-secret",
            "amount": "5.5",
        },
        dataset="ieee-cis",
        transaction_id_field="TransactionID",
        timestamp_field="Timestamp",
        label_field="isFraud",
        feature_fields=("amount",),
        entity_fields=("card1",),
        pseudonymizer=Pseudonymizer(b"k" * 32),
    )

    assert example.label == 1
    assert example.features == {"amount": "5.5"}
    assert example.entity_keys["card1"].startswith("acct_")
    assert audit_feature_columns("paysim", ["type", "isFlaggedFraud"]) == ["isFlaggedFraud"]
    assert audit_feature_columns("baf", ["age", "fraud_bool"]) == ["fraud_bool"]
    with pytest.raises(ValueError, match="label/leakage columns"):
        require_no_label_leakage("paysim", ["isFlaggedFraud"])
    with pytest.raises(ValueError, match="label/leakage columns"):
        require_no_label_leakage("baf", ["fraud_bool"])


def test_partitioned_parquet_round_trip_and_hash(tmp_path) -> None:
    from fraudmesh.data import build_fixture_transactions

    output = tmp_path / "canonical"
    count, content_hash = write_partitioned_parquet(
        build_fixture_transactions(),
        output,
        batch_size=4,
    )

    files = sorted(output.glob("dataset=*/year=*/part-*.parquet"))
    assert count == 15
    assert len(content_hash) == 64
    assert files
    table = ds.dataset(output, format="parquet", partitioning="hive").to_table()
    assert table.num_rows == count
    assert set(table["dataset"].to_pylist()) == {"fixture"}
    repeat_count, repeat_hash = write_partitioned_parquet(
        build_fixture_transactions(),
        tmp_path / "canonical-repeat",
        batch_size=4,
    )
    assert repeat_count == count
    assert repeat_hash == content_hash


def test_tabular_dataset_adapters_respect_label_and_time_contracts(tmp_path) -> None:
    key = Pseudonymizer(b"k" * 32)
    origin = datetime(2017, 12, 1, tzinfo=timezone.utc)
    ieee = adapt_ieee_cis_row(
        {
            "TransactionID": "101",
            "TransactionDT": "60",
            "isFraud": "1",
            "card1": "card-a",
            "TransactionAmt": "5.2",
        },
        {"TransactionID": "101", "DeviceInfo": "device-a"},
        epoch_origin=origin,
        feature_fields=("TransactionAmt",),
        entity_fields=("card1", "DeviceInfo"),
        pseudonymizer=key,
    )
    paysim = adapt_paysim_tabular_row(
        {
            "step": "1",
            "type": "TRANSFER",
            "amount": "7.0",
            "nameOrig": "origin-a",
            "nameDest": "dest-a",
            "isFraud": "0",
            "isFlaggedFraud": "0",
        },
        row_number=1,
        epoch_origin=origin,
        feature_fields=("type", "amount"),
        pseudonymizer=key,
    )
    ulb = adapt_ulb_row(
        {"Time": "30", "Amount": "9.0", "V1": "0.5", "Class": "0"},
        row_number=1,
        epoch_origin=origin,
        feature_fields=("Amount", "V1"),
    )
    baf = adapt_baf_row(
        {
            "application_id": "app-1",
            "fraud_bool": "1",
            "month": "2022-01",
            "income": "4",
        },
        transaction_id_field="application_id",
        normalized_timestamp="2022-01-01T00:00:00Z",
        feature_fields=("income",),
    )

    assert ieee.timestamp == "2017-12-01T00:01:00Z"
    assert ieee.label == 1
    assert "isFraud" not in ieee.features
    assert paysim.timestamp == "2017-12-01T01:00:00Z"
    assert ulb.timestamp == "2017-12-01T00:00:30Z"
    assert baf.label == 1

    count, data_hash = write_tabular_parquet([ieee, adapt_ieee_cis_row(
        {
            "TransactionID": "102",
            "TransactionDT": "120",
            "isFraud": "0",
            "card1": "card-b",
            "TransactionAmt": "12.1",
        },
        {"TransactionID": "102", "DeviceInfo": "device-b"},
        epoch_origin=origin,
        feature_fields=("TransactionAmt",),
        entity_fields=("card1", "DeviceInfo"),
        pseudonymizer=key,
    )], tmp_path / "ieee.parquet")
    assert count == 2
    assert len(data_hash) == 64
    assert pq.ParquetFile(tmp_path / "ieee.parquet").metadata.num_rows == 2
