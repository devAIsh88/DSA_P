# Current Implementation Plan

This plan records completed implementation and the next development boundaries. Phase 6 is complete for development; live provider verification is externally blocked. Product PRD v0.3 (`DEV Placement OS.docx`) governs long-term direction; Python MVP Implementation PRD v0.1 governs MVP scope and order. Phase 4A/4B split its learning-event and learner-model work without changing the sequence. `docs/architecture/PHASE6_AI_TUTOR_CONTRACT.md` is the frozen Phase 6 contract; `docs/architecture/LEARNER_EVIDENCE_AND_STATE.md` remains the evidence/state boundary. Architecture acceptance does not itself begin implementation.

## Current State

- Phase 1 foundation is complete: FastAPI, PostgreSQL/SQLAlchemy, Alembic, health endpoint, and tests.
- Phase 2 problem system is complete: Skill, Problem, TestCase, and problem retrieval.
- Phase 3 execution/evaluation is complete: existing Submission and TestResult persistence, replaceable `ExecutionProvider` with Judge0 adapter, deterministic evaluation, and hidden-test redaction. The Phase 3 migration is applied and its tests passed, per the verified project state. Execution architecture and implementation contract are in `docs/research/phase3/`.
- Phase 4A Learning Evidence / Session Vault is complete: Attempt lifecycle, append-only LearningEvents, Attempt-linked Submission evidence, ordering, idempotency, and learner-safe event responses. Migration `20260929_0004` is applied.
- Learner-model architecture research and implementation contract are in `docs/research/learner-model/`. User-accepted Phase 4A decisions govern reasoning in event evidence, immutable committed events, and the MVP PRD Attempt route names where that contract differs.

## Next Objective

Phase 4A supplies persistent evidence, Phase 4B v1 supplies binary single-skill BKT and assisted-activity reporting, and completed Phase 6 supplies bounded tutor flows. Phase 7 adaptive work is next in the implementation sequence and requires separate authorization. Retry opt-in Gemini verification later; the external provider blocker does not block Phase 7 development. Tutor quality/safety validation remains necessary before production use. Preserve the full product flow: Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity.

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
- Bounded learner-owned context excludes hidden tests, expected outputs, protected diagnostics, secrets, and full chat history. Normal tests use mocks/fake SDK clients: 67 passed, 1 opt-in Judge0 test skipped. No migration was created; Alembic head stays `20260929_0005` with no schema drift.
- Live smoke requests reached the authenticated Gemini HTTP service: `gemini-3.8-flash` returned `503 UNAVAILABLE`; `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No implementation defect was established; failure handling preserved learner evidence and safe fallback behavior. Live structured-output validation and model quality remain externally blocked. Retry later without reopening Phase 6 or blocking Phase 7 development.

## Deferred Work

Defer Phase 7 adaptive recommendation, LeetCode ingestion, retention scheduler, neural knowledge tracing, embeddings/RAG expansion, dashboard/UI, fine-tuning, local-model infrastructure, MCP, Kafka, Redis, and Kubernetes. A separate unrestricted final-solution generator and advanced multi-turn agent are also deferred. Their visibility in research or a PRD does not move them into Phase 6.
