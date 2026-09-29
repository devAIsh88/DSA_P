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

Phase 4B is in progress. The first single-skill slice persists `SkillState` from eligible, unassisted `ATTEMPT_COMPLETED` events using versioned binary BKT and deterministic replay. Only one `ProblemSkill` mapping with unit weight qualifies. The accepted v1 policy retains this mastery boundary and calls for separate, replayable assistance reporting. Fractional hint-weight BKT and normalized multi-skill mastery credit remain research only. Migration `20260929_0005` is applied locally, upgrade/downgrade/upgrade passed, and the last recorded full suite passed (43 passed, 1 opt-in Judge0 test skipped). Attempt-linked and learner-state APIs reject ambiguous databases with multiple User rows. Authentication for a multi-user or public deployment remains outside this phase.

## Next

- Implement v1 assistance reporting from immutable events without changing binary mastery, then validate replay and the full suite. Add mistake and retention signals only when source rules are established. Multi-skill mastery attribution remains deferred; do not infer weights.

## Later

AI Tutor, Adaptive Engine, UI, research validation/experiments, and external practice integration.
