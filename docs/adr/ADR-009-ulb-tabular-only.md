# ADR 009: treat ULB as a tabular benchmark only

- Status: Accepted
- Date: 2026-11-15

## Context

ULB contains only time, amount, and anonymised PCA features. It cannot support a realistic money-flow graph without inventing a graph construction that is not grounded in the data.

## Decision

Use ULB only in the tabular stage-1 M4 scorer. It is a standalone benchmark and not a graph-source dataset for AML ring detection.

## Consequences

- We avoid over-claiming graph structure where there is none.
- The tabular model remains valuable for production-style fraud detection signals.
- Results are framed honestly as a benchmark for a tabular detector, not a graph detector.
