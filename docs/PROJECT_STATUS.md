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

Phase 4B v1 is the latest implemented checkpoint. `SkillState` replays eligible independent, single-skill evidence through versioned binary BKT; assisted and abandoned activity contributes descriptive reporting without changing mastery. Fractional hint BKT and multi-skill mastery credit remain research. The last implementation verification recorded 45 passed, 1 opt-in Judge0 test skipped, and Alembic `20260929_0005 (head)` with no drift. The Phase 6 AI Tutor architecture is now frozen in `docs/architecture/PHASE6_AI_TUTOR_CONTRACT.md`; no tutor functionality is implemented yet.

## Next

- When implementation is separately started, follow the frozen Phase 6 contract for bounded provider access, deterministic hint gating, tutor events, and the minimal post-attempt understanding check. Provider output must not change mastery. Evaluate Phase 4B estimates before accepting new mastery or multi-skill attribution policies.

## Later

Adaptive Engine, UI, research validation/experiments, and external practice integration.
