# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Independently verified on 2026-09-29: 27 tests passed, 1 opt-in Judge0 test skipped; Alembic is at `20260929_0004 (head)` with no schema drift. Event immutability is enforced by normal service/API behavior, not against direct database writes.
- Phase 4B v1 — Replayable single-skill binary BKT and assisted-activity reporting; migration `20260929_0005`.
- Phase 6 — Complete for development: all six AI Tutor endpoints implemented with immutable learner/tutor evidence, replaceable provider, deterministic hint gate, and minimal understanding check. Live provider verification is externally blocked.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

**Phase 6 complete — live provider verification externally blocked.** The frozen `docs/architecture/PHASE6_AI_TUTOR_CONTRACT.md` is implemented: six endpoints, replaceable provider, deterministic hint gate/fallback, diagnosis, reasoning feedback, post-attempt explanation, and understanding checks. Tutor events retain separate evidence, labels, and provenance without changing mastery. Offline verification: 67 tests passed, 1 opt-in Judge0 test skipped; Alembic remains `20260929_0005 (head)` with no schema drift.

Live Gemini smoke verification reached the Gemini HTTP service with the configured authentication, but `gemini-3.8-flash` returned `503 UNAVAILABLE` and `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No implementation defect was established. Failure handling behaved correctly, preserving learner evidence and using safe hint fallback where available. Successful live structured outputs and model quality remain unverified. Phase 4B v1 remains binary, independent, single-skill BKT; fractional hints and multi-skill mastery remain research.

## Next

- Retry opt-in live Gemini verification later, then validate tutor output quality, safety, latency, and structured-output reliability before production use. This external blocker does not block Phase 7 development; Phase 7 adaptive implementation still requires separate authorization. Evaluate Phase 4B estimates before accepting new mastery or multi-skill attribution policies.

## Later

Adaptive Engine, UI, research validation/experiments, and external practice integration.
