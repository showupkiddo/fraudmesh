# ADR 015: canonical transaction schema and amount policy

- Status: Accepted for implementation; source-specific validation pending data access
- Date: 2026-11-15

## Context

The source datasets vary in identifier shape, time representation, currencies, and labels. A shared graph-oriented schema is needed without implying that tabular-only benchmarks contain money-flow edges.

## Decision

Graph transaction records use a dataset-qualified transaction ID, UTC timestamp, keyed pseudonyms for both endpoint accounts, source and destination institutions, `amount_inr` (always INR), the source amount and ISO currency for lineage, a normalized channel, a binary transaction-level edge label, and nullable ring ID and typology. AMLworld uses `Amount Paid` with `Payment Currency`; SAML-D uses `Amount` with `Payment_currency`. Both use an explicitly reviewed, year-specific rate table. Ring IDs are sourced only from AMLworld pattern files. Account pseudonyms use keyed HMAC-SHA-256 and the same key across participating clients; the key is provided outside the repository.

Tabular-only sources use a separate example contract with features and separately stored pseudonymized entity keys for history-feature construction. Target and leakage columns are not model features. PaySim simulation units and ULB's unspecified `Amount` remain benchmark input features, not INR-denominated monetary outputs. ULB remains tabular-only; IEEE-CIS is not treated as a money-flow graph.

## Consequences

- Canonical timestamps are timezone-aware UTC and validation fails on missing or inconsistent values.
- Canonical monetary output is `amount_inr`; source amounts and currencies are provenance only and must not be reported as INR.
- Missing currency rates, privacy keys, source columns, or invalid labels fail explicitly.
- Annual FX inputs are explicitly period averages, not transaction-date spot prices. Source-specific mappings, data-card facts, and EDA checks remain pending until the actual source files are reviewed.
