# ADR 014: use a clearly named FedFraud-style baseline

- Status: Accepted
- Date: 2026-11-15

## Context

Papers that are lightly specified or not fully reproduced can produce a misleading baseline when implemented from memory.

## Decision

Any method aligned with the paper’s idea but not fully reproduced is called a `FedFraud-style` baseline, with assumptions documented and a limited implementation budget. The baseline is not claimed to be the exact paper implementation unless the team re-implements it faithfully.

## Consequences

- The evaluation remains interpretable and defensible.
- We do not overstate our comparative literature coverage.
- The project keeps enough time to deliver the primary production-grade result.
