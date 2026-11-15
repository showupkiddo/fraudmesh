# ADR 011: federated training uses a single schema per client

- Status: Accepted
- Date: 2026-11-15

## Context

FedAvg requires identical tensor shapes. A heterogeneous client schema can silently break model aggregation.

## Decision

Use one primary federated experiment with a single graph schema partitioned by bank or segment. If auxiliary sources have different feature sets, keep them in local encoders or comparable stage-1 settings rather than mixing incompatible features into the same aggregate model.

## Consequences

- Federation is mathematically sound and easier to interpret.
- The project retains a clearer story for the main result.
- Mixed-data experiments are framed as optional supplements rather than part of the primary claim.
