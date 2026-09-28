# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Migration `20260929_0004` is applied; the full test suite passed.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

Phase 4A is implemented. Attempt-linked APIs enforce the single-learner MVP assumption by rejecting ambiguous databases with multiple User rows. Authentication for a multi-user or public deployment remains outside this phase.

## Next

- Phase 4B — Learner Model / Knowledge Tracing (implementation PRD Phase 5).

## Later

AI Tutor, Adaptive Engine, UI, research validation/experiments, and external practice integration.
