# ADR 002: two-stage pipeline for tabular and graph models

- Status: Accepted
- Date: 2026-11-15

## Context

Different datasets support different model types; a single model cannot consume them uniformly without distorting the task.

## Decision

Use two stages: M4 as a federated tabular per-transaction scorer for IEEE-CIS, BAF, PaySim, and ULB, and M3 as a federated graph model for AMLworld, SAML-D, and Elliptic++.

## Consequences

- The project matches realistic fraud-stack design.
- Data and model responsibilities are clear and auditable.
- Out-of-domain graph results remain valid as a transfer or robustness test, not as a primary production claim.
