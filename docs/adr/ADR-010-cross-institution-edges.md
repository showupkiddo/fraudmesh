# ADR 010: preserve cross-institution edges with stub nodes

- Status: Accepted
- Date: 2026-11-15

## Context

A local-only graph removes the foreign half of a cross-institution laundering pattern and loses the main signal of the project.

## Decision

Every client graph keeps edges where either endpoint belongs to the client. The foreign endpoint is represented as a hashed stub node with only transaction-level information, without local institutional knowledge beyond what the edge itself reveals.

## Consequences

- The federated task remains meaningful.
- Cross-institution laundering patterns can be observed in a realistic way.
- The project gets a better explanation for the blind-spot table and the federation value proposition.
