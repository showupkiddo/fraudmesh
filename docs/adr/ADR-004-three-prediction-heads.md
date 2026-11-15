# ADR 004: three prediction heads with explicit label derivations

- Status: Accepted
- Date: 2026-11-15

## Context

The model must score the correct unit consistently. A graph model can be edge-based, account-based, or ring-based, but the tasks must not be mixed.

## Decision

Define three prediction heads: edge, account, and ring. Edge labels come from laundering transactions; account labels are derived from whether an account sends or receives a laundering edge; ring labels follow the instance-level grouping in the AMLworld pattern file.

## Consequences

- Metrics align with the task formulation.
- The reporting stack can compare the appropriate units without unfair mixing.
- The account head remains explainable and derived from the underlying edge truth.
