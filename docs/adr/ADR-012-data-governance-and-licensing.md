# ADR 012: record dataset access, licences, and use constraints

- Status: Accepted
- Date: 2026-11-15

## Context

Research datasets often come with licences, access rules, and restrictions that affect redistribution and downstream use.

## Decision

Every dataset receives a data card with source, licence, download date, row and column counts, label definition, and usage constraints. Raw data stays read-only, and the project does not distribute unapproved data.

## Consequences

- The project remains legally and ethically credible.
- Downstream model release choices are grounded in documented access policies.
- Data provenance becomes part of the reproducibility story.
