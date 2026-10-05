# Project Status

## Completed Implementation

- Phase 1 — Foundation.
- Phase 2 — Problem catalogue.
- Phase 3 — Execution/evaluation, including replaceable Judge0 execution, deterministic evaluation, persisted submissions/test results, and hidden-test redaction. Phase 3 migration is applied and tests passed, per the verified project state.
- Phase 4A — Attempt lifecycle and persistent LearningEvent evidence. Independently verified on 2026-09-29: 27 tests passed, 1 opt-in Judge0 test skipped; Alembic is at `20260929_0004 (head)` with no schema drift. Event immutability is enforced by normal service/API behavior, not against direct database writes.
- Phase 4B v1 — Replayable single-skill binary BKT and assisted-activity reporting; migration `20260929_0005`.
- Phase 6 — Complete for development: all six AI Tutor endpoints implemented with immutable learner/tutor evidence, replaceable provider, deterministic hint gate, and minimal understanding check. Live provider verification is externally blocked.
- Phase 7 — Deterministic Adaptive Engine: five recommendation actions, scheduled review, evidenced weak-skill targeting, immutable persisted decisions, and atomic Attempt-start consumption. Migration `20261003_0006`.
- Phase 8 — Streamlit Home/Progress and Problem Workspace, safe recovery reads, non-authoritative public-sample Run, explicit demo provisioning, all six targeted tutor flows and backend-owned recommendations. No migration.
- Phase 9 offline evaluation foundation — 25 versioned tutor cases, strict provider-neutral invocation, evaluation-only persistence, human rubric/review, comparison/export and a bounded offline-first CLI. Real-model comparison and production selection remain pending.

## Research Completed

- LLM/model strategy.
- Execution architecture and Phase 3 implementation contract (`docs/research/phase3/`).
- Learner-model architecture and learner-model implementation contract — now present at `docs/research/learner-model/`.

## Current

**Phase 9 offline foundation complete.** `docs/architecture/PHASE9_EVALUATION_CONTRACT.md` is implemented. Verification on 2026-10-05: **462 passed, 1 opt-in Judge0 test skipped**, with zero live model/Judge0 calls. Alembic is `20261003_0007 (head)` with no schema drift; disposable PostgreSQL upgrade/downgrade/re-upgrade passed. Two synthetic candidates completed 25 cases each in local PostgreSQL; comparison/export passed and learner row counts were unchanged. Synthetic results do not establish tutor quality. Human review and production selection remain pending; missing usage/cost is unavailable. Evaluation never writes learner events/state/recommendations.

Phase 8 remains complete: Streamlit uses public HTTP, sample Run creates no history, and refresh restores committed backend state. Browser visual verification was unavailable and remains recommended.

Thresholds remain uncalibrated MVP defaults. Scheduled review does not establish forgetting; abandonment is not struggle evidence; low prior mastery alone is not confirmed weakness. Skill targeting requires a single unit-weight mapping. Retention modelling, recent-error targeting, multi-skill mastery and recommendation-quality evaluation remain deferred. Explicit local demo provisioning added six mapped Problems across two Skills; the original unmapped Problem was preserved. Provisioning created no learner history or projections and a rerun created no rows. The prototype is local, single-learner and unauthenticated; unsaved drafts may be lost on full refresh.

Live Gemini smoke verification reached the Gemini HTTP service with the configured authentication, but `gemini-3.8-flash` returned `503 UNAVAILABLE` and `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No implementation defect was established. Failure handling behaved correctly, preserving learner evidence and using safe hint fallback where available. Successful live structured outputs and model quality remain unverified. Phase 4B v1 remains binary, independent, single-skill BKT; fractional hints and multi-skill mastery remain research.

## Next

- Agree explicit candidate providers/models and an API/cost budget before any live Phase 9 comparison. All candidates must use the same suite/controls; complete human review before considering selection. Only Gemini is currently registered for future live evaluation; another provider requires a conforming adapter. No live/paid calls, production selection or later-phase implementation are authorized in this completed run.

- Measure learner outcomes separately: hint dependency, retention, learner-state quality and recommendation quality are not established by tutor-output benchmarks. Manual Phase 8 browser visual/accessibility review remains recommended.

- Retry opt-in live Gemini verification later, then validate tutor output quality, safety, latency, and structured-output reliability before production use. This external blocker did not block Phase 7 completion. Evaluate Phase 4B estimates before accepting new mastery or multi-skill attribution policies.

## Later

Research validation/experiments, production deployment/authentication, and external practice integration require separate scope acceptance.
