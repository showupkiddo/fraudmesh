# ADR 008: evaluation metrics and split policy

- Status: Accepted
- Date: 2026-11-15

## Context

A model can overstate its performance if it is evaluated on random splits with ROC-AUC on highly imbalanced data.

## Decision

Primary metric is PR-AUC. Secondary metrics include minority F1, precision@k, ring recall, and false alerts per 1,000 transactions. Splits are chronological and validation slices are tuned only on validation data. Use 5+ seeds and bootstrap confidence intervals.

## Consequences

- Results are harder to overclaim and more representative of real-world deployment.
- The evaluation harness is a central, fair comparator for all later models.
- The final write-up is backed by more defensible statistical evidence.
