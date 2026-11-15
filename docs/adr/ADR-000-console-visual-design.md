# ADR 000: console visual design reference

- Status: Accepted
- Date: 2026-11-15

## Context

The saved HTML console bundle is noisy and contains embedded runtime metadata, but the design intent is still clear from the application structure, the design tokens provided in the production plan, and the phase-11 screen descriptions.

## Decision

Use the design tokens and the five-screen specification as the source of truth for the frontend styling and interactions, and treat the rendered HTML as a visual reference rather than a hand-authored source file.

## Consequences

- The console will follow the approved financing design language: page background `#ECEEEB`, surface white, teal primary `#0B6B64`, amber warnings, and the specified sidebar/table behaviour.
- The app will follow the Phase 11 route structure and ensure the alert queue, graph explorer, cases, reports, and model/privacy screens match the product brief.
- The design is intentionally documented in a way that remains implementable even when the HTML bundle itself is noisy.
