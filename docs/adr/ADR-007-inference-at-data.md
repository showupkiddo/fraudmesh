# ADR 007: inference runs beside each institution's data

- Status: Accepted
- Date: 2026-11-15

## Context

A central inference API can create accidental leakage or a mismatch between local data residency and the model service.

## Decision

Inference runs beside each institution's data; the consortium service holds only weights, metrics, the privacy ledger, and aggregate summaries.

## Consequences

- Local data remains the tenant boundary for operational privacy.
- The consortium is reduced to coordination and aggregation, not raw-data access.
- The architecture aligns with the project's federated privacy assumptions.
