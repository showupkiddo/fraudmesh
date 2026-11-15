# ADR 003: temporal decay is applied inside the attention logit

- Status: Accepted
- Date: 2026-11-15

## Context

The original formulation multiplied decay after softmax, which breaks the probability-normalization story and allows pathologies.

## Decision

Temporal decay is applied inside the attention logit as an additive term, with `lambda = softplus(parameter)` per head and normalized delta-t. Causal masking remains in place.

## Consequences

- Attention remains normalized and interpretable.
- Older edges cannot gain more attention than newer ones through parameter drift.
- The model behaviour is easier to reason about and test in ablations.
