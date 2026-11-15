# ADR 001: use AMLworld as the primary graph dataset

- Status: Accepted
- Date: 2026-11-15

## Context

The original design used several tabular datasets for graph-oriented claims even though the real ring labels and a natural bank partition are only available in AMLworld.

## Decision

Use AMLworld HI-Small and LI-Small as the primary graph training dataset. Partition by bank and use the pattern files to provide ring labels. Do not derive ring labels by graph propagation.

## Consequences

- Cross-institution ring structure is realistic and defensible.
- The graph partitioning story is stronger for the federation argument.
- Other datasets remain useful, but they are secondary or stage-1 inputs rather than primary graph ground truth.
