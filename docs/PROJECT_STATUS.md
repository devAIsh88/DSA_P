# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Independently verified on 2026-09-29: 27 tests passed, 1 opt-in Judge0 test skipped; Alembic is at `20260929_0004 (head)` with no schema drift. Event immutability is enforced by normal service/API behavior, not against direct database writes.
- Phase 4B v1 — Replayable single-skill binary BKT and assisted-activity reporting; migration `20260929_0005`.
- Phase 6 — Complete for development: all six AI Tutor endpoints implemented with immutable learner/tutor evidence, replaceable provider, deterministic hint gate, and minimal understanding check. Live provider verification is externally blocked.
- Phase 7 — Deterministic Adaptive Engine: five recommendation actions, scheduled review, evidenced weak-skill targeting, immutable persisted decisions, and atomic Attempt-start consumption. Migration `20261003_0006`.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

**Phase 7 complete.** `docs/architecture/PHASE7_ADAPTIVE_ENGINE_CONTRACT.md` is implemented: pure versioned policy, `GET /recommendations/next`, one active persisted recommendation per learner, evidence/config/catalogue/deadline invalidation, and transactional recommendation consumption through `POST /attempts/start`. Recommendations never mutate learner state, mastery or historical evidence. Verification on 2026-10-03: **263 passed, 1 opt-in Judge0 test skipped**; Alembic `20261003_0006 (head)` with no schema drift. Local PostgreSQL concurrent issuance/start checks passed.

Thresholds remain uncalibrated MVP defaults. Scheduled review does not establish forgetting; abandonment is not struggle evidence; low prior mastery alone is not confirmed weakness. Skill targeting requires a single unit-weight mapping. Retention modelling, recent-error targeting, multi-skill mastery and recommendation-quality evaluation remain deferred. The local catalogue still has one Easy unmapped problem and no learner/activity rows; isolated tests provide coverage without fabricated persistent learner history.

Live Gemini smoke verification reached the Gemini HTTP service with the configured authentication, but `gemini-3.8-flash` returned `503 UNAVAILABLE` and `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No implementation defect was established. Failure handling behaved correctly, preserving learner evidence and using safe hint fallback where available. Successful live structured outputs and model quality remain unverified. Phase 4B v1 remains binary, independent, single-skill BKT; fractional hints and multi-skill mastery remain research.

## Next

- Phase 8 readiness/architecture review only; UI implementation requires separate authorization.

- Retry opt-in live Gemini verification later, then validate tutor output quality, safety, latency, and structured-output reliability before production use. This external blocker did not block Phase 7 completion. Evaluate Phase 4B estimates before accepting new mastery or multi-skill attribution policies.

## Later

UI after separate implementation authorization, research validation/experiments (including Phase 9 recommendation-quality evaluation), and external practice integration.
