# Current Implementation Plan

This plan records completed implementation and the next development boundaries. Phase 8 is complete; Phase 6 live provider verification remains externally blocked. Product PRD v0.3 (`DEV Placement OS.docx`) governs long-term direction; Python MVP Implementation PRD v0.1 governs MVP scope and order. Phase 4A/4B split its learning-event and learner-model work without changing the sequence. Frozen implementation contracts are in `docs/architecture/`; `LEARNER_EVIDENCE_AND_STATE.md` remains the evidence/state boundary. Architecture acceptance does not itself begin implementation.

## Current State

- Phase 1 foundation is complete: FastAPI, PostgreSQL/SQLAlchemy, Alembic, health endpoint, and tests.
- Phase 2 problem system is complete: Skill, Problem, TestCase, and problem retrieval.
- Phase 3 execution/evaluation is complete: existing Submission and TestResult persistence, replaceable `ExecutionProvider` with Judge0 adapter, deterministic evaluation, and hidden-test redaction. The Phase 3 migration is applied and its tests passed, per the verified project state. Execution architecture and implementation contract are in `docs/research/phase3/`.
- Phase 4A Learning Evidence / Session Vault is complete: Attempt lifecycle, append-only LearningEvents, Attempt-linked Submission evidence, ordering, idempotency, and learner-safe event responses. Migration `20260929_0004` is applied.
- Learner-model architecture research and implementation contract are in `docs/research/learner-model/`. User-accepted Phase 4A decisions govern reasoning in event evidence, immutable committed events, and the MVP PRD Attempt route names where that contract differs.
- Phase 4B v1 binary single-skill BKT/reporting and Phase 6 tutor flows are complete as described below.
- Phase 7 is complete: deterministic recommendation policy, persistence, revision scheduling, weak-skill targeting, API and Attempt integration; migration `20261003_0006`. Full verification: 263 passed, 1 opt-in Judge0 test skipped; no schema drift.
- Phase 8 is complete: typed Streamlit UI, safe learner/dashboard/submission reads, isolated sample Run, explicit demo provisioning, recovery and the full learner loop. Full verification: 353 passed, 1 opt-in Judge0 test skipped; Alembic unchanged with no drift.

## Next Objective

Next boundary: Phase 9 readiness/evaluation architecture only. Identify datasets, baselines and quality/safety questions before accepting evaluation implementation or paid provider runs. Preserve Phase 7 deterministic rules, Phase 4B mastery and immutable evidence. Manual browser visual/accessibility verification of Phase 8 remains recommended; no Phase 9 implementation is authorized.

Phase 4A supplies persistent evidence, Phase 4B v1 supplies binary single-skill BKT and assisted-activity reporting, Phase 6 supplies bounded tutor flows, and Phase 7 supplies deterministic adaptive decisions. Retry opt-in Gemini verification later; the external provider blocker did not block Phase 7 completion. Tutor quality/safety validation remains necessary before production use. Preserve the full product flow: Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity.

## Phase 4A — Learning Evidence / Session Vault

Implemented in migration `20260929_0004`. The active code stores canonical reasoning text in `REASONING_RECORDED.evidence`, keeps committed events append-only, and uses the MVP PRD Attempt route names. Public hint and understanding-check APIs were added later in Phase 6.

- `Attempt` groups one learner engagement with a problem. **Attempt ≠ Submission**: one Attempt can contain multiple existing Submissions and interventions.
- `LearningEvent` persists meaningful actions and execution/evaluation results with ordering, references, and source provenance. Do not rewrite raw evidence to fit a later interpretation.
- MVP event types: `ATTEMPT_STARTED`, `REASONING_RECORDED`, `SUBMISSION_EVALUATED`, `HINT_REQUESTED`, `HINT_DELIVERED`, `ATTEMPT_COMPLETED`, `UNDERSTANDING_CHECK`. Add a type only when a concrete workflow requires it.
- Keep raw `evidence` and `derived_labels` separate. Link deterministic execution and test evaluation evidence into events without exposing hidden-test inputs, expected outputs, or private provider details through learner-facing APIs. Capture requested and delivered hint levels separately when hints exist; do not require the tutor to be implemented in this phase.
- Learner-safe schemas, validation, ordering/idempotency, and the single-learner ownership boundary are implemented and covered by isolated provider tests.

## Phase 4B — Learner Model / Knowledge Tracing

Implemented checkpoints: `KnowledgeTracingProvider` and pure BKT calculations use versioned experimental parameters in `config/learner_model.json`; migration `20260929_0005` adds `ProblemSkill` and `SkillState`. Attempt closure snapshots a skill only when exactly one mapping has unit weight. A service replays eligible completion events by event ID, validates prior deterministic evaluation events, and updates SkillState in the same transaction as the completion event. Reprocessing the same history cannot double-apply mastery. `GET /learner/skills` and `GET /learner/skills/{skill_id}` expose allowlisted projection fields. Current BKT accepts only binary, unassisted Attempt observations.

Implemented Phase 4B v1 reporting replays terminal single-skill Attempts independently of BKT eligibility. Hint-request counts, delivered-level averages, hint-associated and independent solves, and assisted-only histories now project from immutable events. Only binary, independent, single unit-weight skill observations may update mastery. Historical Phase 4A completions without a captured `skill_id` are not retroactively attributed. Problems with no mapping, multiple mappings, or non-unit weights still close but do not update mastery; their event provenance records the reason. `ProblemSkill.weight` is not a probability or BKT credit. No public mapping-write endpoint exists.

After v1 reporting, define mistake and retention signals from validated evidence and review whether an authenticated administrative replay endpoint is needed. Assisted mastery rules and multi-skill mastery attribution require future evidence and separate acceptance. Fractional hint-weight BKT and normalized `ProblemSkill.weight` mastery credit in `docs/research/learner-model/Phase4B_Policy_Research.md` remain proposals, not implementation instructions.

- Keep `SkillState` derived from immutable events and `KnowledgeTracingProvider` replaceable. BKT is the initial method, with model parameters and versions recorded rather than embedded as permanent architectural truths. An LLM must not calculate or directly change mastery.
- Update state from meaningful evidence: mastery probability and uncertainty, attempt and successful-attempt counts, independent solves, hint dependency, timing, recent errors, last attempt, and retention evidence where available. Preserve provenance for each derived observation and state transition.
- Keep v1 mastery eligibility binary and versioned. Define hint reporting separately: `hint_count_total` counts requests; `average_hint_level` uses delivered levels; `hint_dependent_count` describes successful Attempts with any hint request or delivery, without implying a pedagogical threshold. Future hint weighting and error/understanding labels require separate validated rules. Do not treat Level 3+ hints as incorrect BKT observations.
- Support deterministic replay: given the same event history, model version, model parameters, and skill-attribution rules, the resulting learner state should be reproducible. A future correction must append new history and rebuild the projection without replacing historical raw evidence.
- A problem may supply evidence for multiple skills. `ProblemSkill` stores the relation, but multi-skill attribution and evidence weighting remain unimplemented. Do not duplicate raw LearningEvents merely to cause multiple mastery updates. Define attribution before implementing multi-skill updates.
- Keep focused tests for implemented BKT updates, provenance, replay, eligibility, transaction failure, and hidden-evidence protection. Add hint and multi-skill policy tests only when those policies are implemented.

## Phase 6 — AI Tutor (complete; live verification externally blocked)

- Typed `TutorProvider`, deterministic mock, hint-only fallback, and `GeminiTutorProvider` using `google-genai` are implemented. `gemini-3.8-flash` is a configurable default. The application controls hint levels and the configurable Level 6 gate.
- The six routes in the frozen contract are implemented, including PRD `POST /hints/request`, separate request/delivery events, and an understanding answer committed before optional AI evaluation. Provider failures preserve learner evidence and do not block core execution/evaluation.
- Delivered/received content is evidence; AI classification/confidence is derived labels; provider/model/prompt identity is provenance. Committed events are not amended. Tutor flows do not update `SkillState` or mastery; `recent_error_types` projection remains deferred until a deterministic replay rule is accepted.
- Bounded learner-owned context excludes hidden tests, expected outputs, protected diagnostics, secrets, and full chat history. Phase 6 verification used mocks/fake SDK clients: 67 passed, 1 opt-in Judge0 test skipped. No Phase 6 migration was created; its verified Alembic head was `20260929_0005` with no schema drift.
- Live smoke requests reached the authenticated Gemini HTTP service: `gemini-3.8-flash` returned `503 UNAVAILABLE`; `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No implementation defect was established; failure handling preserved learner evidence and safe fallback behavior. Live structured-output validation and model quality remain externally blocked. Retry later without reopening Phase 6 or blocking Phase 7 development.

## Phase 7 — Adaptive Engine (complete)

- `RecommendationPolicy` consumes typed historical facts, supported projections and catalogue candidates without providers, persistence or side effects. The versioned `adaptive-rules-v1` defaults implement the five PRD actions with deterministic reasons/ties. Thresholds are uncalibrated; low priors without observations are not weakness and scheduled review is not retention loss.
- The service snapshots replay inputs and persists immutable decisions with a controlled consumed/superseded lifecycle. Freshness combines learner-scoped maximum event ID and committed event count, configuration/catalogue/projection fingerprints and review deadlines. There is at most one active recommendation per learner.
- `GET /recommendations/next` is allowlisted and returns `409` while an Attempt is active. `POST /attempts/start` consumes only a fresh exact match in the same transaction as its new Attempt/opening event; stale or different-problem decisions are superseded. Idempotent old-start retrieval cannot consume a newer decision.
- Single-skill/unit-weight mappings permit targeting. Unsupported mappings may supply unattributed catalogue choices, without mastery inference. No LLM, execution-provider, learner-state or historical-event write occurs during recommendation selection.
- Migration `20261003_0006` follows `20260929_0005`; upgrade, empty-table downgrade, re-upgrade and schema consistency checks passed. Tests cover policy, persistence, service, API and rollback; disposable PostgreSQL concurrency checks passed.
- No demo seed expansion was required for Phase 7 correctness. Phase 8 subsequently added explicit demo catalogue provisioning without learner history. Retention/error targeting and recommendation-quality validation remain deferred.

## Phase 8 — Streamlit UI (complete)

- Implemented `PHASE8_UI_CONTRACT.md`: Home/Progress and Workspace call public HTTP through a typed API client; no direct database/service/provider access. Viewing a Problem creates no Attempt. Start/resume, reasoning, Run/Submit, completion/abandonment and all six targeted tutor flows respect backend gates.
- `POST /runs` uses only public sample cases through ExecutionProvider, creates no learning evidence and cannot authorize SOLVED. Submission read, learner facade and dashboard return allowlisted ownership-scoped data and public skill labels; reporting denominators remain explicit.
- `python -m scripts.provision_demo` provisions a small local catalogue idempotently and refuses conflicts. It creates no Attempts, Submissions, events, learner state or recommendations. Legacy local ID sequences are advanced only when needed; rollback may leave harmless gaps.
- Safe URL IDs plus backend reads restore committed Attempts, reasoning, tutor content and latest Submission/results. Session drafts/operation keys are transient; no automatic POST replay or resubmission of saved understanding answers. Gemini failure leaves the coding/progress/recommendation loop usable.
- Verification: 26 backend tests, 32 provisioning tests, 21 foundation tests and 11 AppTest scenarios; full suite 353 passed, 1 skipped. Disposable localhost HTTP and server health checks passed; browser automation was unavailable, so visual/keyboard review remains recommended. No live Gemini/Judge0 calls or new migration.
- Estimated mastery is not certainty. Unsupported retention/error/readiness metrics, multi-skill mastery, policy-quality claims, authentication, custom-input execution and production UI remain deferred.

## Deferred Work

Defer LeetCode ingestion, retention modelling/background scheduler, neural knowledge tracing, embeddings/RAG expansion, production UI, fine-tuning, local-model infrastructure, MCP, Kafka, Redis, and Kubernetes. Phase 7 includes dynamic scheduled review only. A separate unrestricted final-solution generator and advanced multi-turn agent are also deferred.
