# ADR 005: differentially private privacy unit

- Status: Accepted
- Date: 2026-11-15

## Context

A graph model cannot treat a node or an entire graph as a trivial SGD example, because neighbourhood structure creates dependencies.

## Decision

The privacy unit is one degree-capped ego-subgraph per example, with Poisson sampling, per-sample gradient validation, and no BatchNorm. The privacy claim is bounded to the stated unit and remains conservative.

## Consequences

- The DP guarantee is rooted in a defensible unit.
- Privacy auditing is more honest and easier to explain in the final report.
- We avoid claiming stronger guarantees than the method actually provides.
