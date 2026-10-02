# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Independently verified on 2026-09-29: 27 tests passed, 1 opt-in Judge0 test skipped; Alembic is at `20260929_0004 (head)` with no schema drift. Event immutability is enforced by normal service/API behavior, not against direct database writes.
- Phase 4B v1 — Replayable single-skill binary BKT and assisted-activity reporting; migration `20260929_0005`.
- Phase 6 — Six AI Tutor routes with immutable learner/tutor evidence, replaceable provider, deterministic hint gate, and minimal understanding check. Offline tests pass; live model quality remains unverified.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

Phase 6 AI Tutor is implemented to the frozen `docs/architecture/PHASE6_AI_TUTOR_CONTRACT.md`: six routes, replaceable provider, deterministic hint gate/fallback, diagnosis, reasoning feedback, post-attempt explanation, and understanding checks. Tutor events retain separate evidence, labels, and provenance without changing mastery. Offline verification on 2026-10-02: 67 tests passed, 1 opt-in Judge0 test skipped; Alembic `20260929_0005 (head)` and no schema drift. Gemini quality and live-provider behavior have not been validated against a real account. Phase 4B v1 remains binary, independent, single-skill BKT; fractional hints and multi-skill mastery remain research.

## Next

- Validate tutor output quality, safety, latency, and structured-output reliability through explicitly opt-in model tests/benchmarks before production use. Evaluate Phase 4B estimates before accepting new mastery or multi-skill attribution policies. Phase 7 adaptive work requires separate authorization.

## Later

Adaptive Engine, UI, research validation/experiments, and external practice integration.
