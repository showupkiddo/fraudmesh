# ADR 006: neutral validation slice for RAP-FedAvg

- Status: Accepted
- Date: 2026-11-15

## Context

A custom federated strategy that uses client reputation must not use the same validation slice that clients train on, or the model selection process becomes self-referential.

## Decision

RAP-FedAvg uses a neutral validation slice that no client trains on. Reputation and weighting are evaluated without leaking a client-specific validation advantage.

## Consequences

- Client reputation is more credible and less prone to overfitting.
- The evaluation stack can compare against FedAvg/FedProx with a fair slice.
- We avoid mixing secure aggregation claims with per-client reputation methods.
