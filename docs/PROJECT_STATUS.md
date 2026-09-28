# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Independently verified on 2026-09-29: 27 tests passed, 1 opt-in Judge0 test skipped; Alembic is at `20260929_0004 (head)` with no schema drift. Event immutability is enforced by normal service/API behavior, not against direct database writes.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

Phase 4B is in progress. Pure single-skill BKT math and versioned experimental parameters are implemented; SkillState persistence and evidence-to-state integration are not yet implemented. Attempt-linked APIs enforce the single-learner MVP assumption by rejecting ambiguous databases with multiple User rows. Authentication for a multi-user or public deployment remains outside this phase.

## Next

- Persist SkillState and connect eligible, single-skill Attempt completion evidence to deterministic BKT replay. Do not apply a multi-skill attribution policy without an accepted decision.

## Later

AI Tutor, Adaptive Engine, UI, research validation/experiments, and external practice integration.
