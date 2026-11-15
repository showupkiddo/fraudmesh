from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import (
    build_fixture_transactions,
    convert_amlworld_csv,
    convert_samld_csv,
    load_currency_rates_csv,
    validate_dataset,
    write_partitioned_parquet,
)
from .canonical import pseudonymizer_from_environment

SAMLD_COLUMN_MAP = {
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
}


def run_fixture_pipeline(output_dir: Path) -> dict[str, object]:
    records = build_fixture_transactions()
    issues = validate_dataset(records)
    if issues:
        raise ValueError(f"fixture validation failed: {issues}")
    count, data_hash = write_partitioned_parquet(records, output_dir)
    return {"rows": count, "sha256": data_hash, "output_dir": str(output_dir)}


def run_amlworld_pipeline(
    input_path: Path,
    pattern_path: Path,
    output_dir: Path,
    *,
    dataset: str,
    rates_path: Path,
) -> dict[str, object]:
    count, data_hash = convert_amlworld_csv(
        input_path,
        output_dir,
        dataset=dataset,
        rates=load_currency_rates_csv(rates_path),
        pseudonymizer=pseudonymizer_from_environment(),
        pattern_path=pattern_path,
    )
    return {"dataset": dataset, "rows": count, "sha256": data_hash, "output_dir": str(output_dir)}


def run_samld_pipeline(
    input_path: Path,
    output_dir: Path,
    *,
    rates_path: Path,
) -> dict[str, object]:
    dataset = "samld"
    count, data_hash = convert_samld_csv(
        input_path,
        output_dir,
        dataset=dataset,
        column_map=SAMLD_COLUMN_MAP,
        rates=load_currency_rates_csv(rates_path),
        pseudonymizer=pseudonymizer_from_environment(),
    )
    return {"dataset": dataset, "rows": count, "sha256": data_hash, "output_dir": str(output_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Phase 1 canonical data artefacts.")
    parser.add_argument("--source", choices=("fixture", "amlworld", "samld"), default="fixture")
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed/fixture"))
    parser.add_argument("--dataset")
    parser.add_argument("--input-path", type=Path)
    parser.add_argument("--pattern-path", type=Path)
    parser.add_argument("--rates-path", type=Path, default=Path("data/config/currency-rates.csv"))
    args = parser.parse_args()
    if args.source == "fixture":
        result = run_fixture_pipeline(args.output_dir)
    elif args.source == "amlworld":
        if not args.dataset or args.input_path is None or args.pattern_path is None:
            parser.error("amlworld requires --dataset, --input-path, and --pattern-path")
        result = run_amlworld_pipeline(
            args.input_path,
            args.pattern_path,
            args.output_dir,
            dataset=args.dataset,
            rates_path=args.rates_path,
        )
    else:
        if args.input_path is None:
            parser.error("samld requires --input-path")
        result = run_samld_pipeline(args.input_path, args.output_dir, rates_path=args.rates_path)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
