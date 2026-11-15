# ADR 013: handle compute and external approvals explicitly

- Status: Accepted
- Date: 2026-11-15

## Context

Critical project steps depend on external access, token creation, and access to compute resources that cannot be self-provisioned in the project repository.

## Decision

The team does not fabricate external access. Where Kaggle, competition-rule acceptance, GPU access, or DVC remote configuration is required, the project pauses and asks for the missing human action while continuing CPU-first fixture work in the meantime.

## Consequences

- CI and development remain unblocked by missing data access or GPU provisioning.
- The repository keeps making progress even when external approvals are pending.
- The final research story remains honest about what was and was not run locally.
