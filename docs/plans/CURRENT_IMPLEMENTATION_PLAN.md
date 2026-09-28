# Current Implementation Plan

This is the active engineering plan for Phase 4B. Product PRD v0.3 (`DEV Placement OS.docx`) governs long-term direction; the Python MVP Implementation PRD v0.1 governs MVP scope and order. The 4A/4B labels below split its Phase 4 (learning events) and Phase 5 (learner model) without changing that sequence. See `docs/architecture/LEARNER_EVIDENCE_AND_STATE.md` for the stable data boundary.

## Current State

- Phase 1 foundation is complete: FastAPI, PostgreSQL/SQLAlchemy, Alembic, health endpoint, and tests.
- Phase 2 problem system is complete: Skill, Problem, TestCase, and problem retrieval.
- Phase 3 execution/evaluation is complete: existing Submission and TestResult persistence, replaceable `ExecutionProvider` with Judge0 adapter, deterministic evaluation, and hidden-test redaction. The Phase 3 migration is applied and its tests passed, per the verified project state. Execution architecture and implementation contract are in `docs/research/phase3/`.
- Phase 4A Learning Evidence / Session Vault is complete: Attempt lifecycle, append-only LearningEvents, Attempt-linked Submission evidence, ordering, idempotency, and learner-safe event responses. Migration `20260929_0004` is applied.
- Learner-model architecture research and implementation contract are in `docs/research/learner-model/`. User-accepted Phase 4A decisions govern reasoning in event evidence, immutable committed events, and the MVP PRD Attempt route names where that contract differs.

## Next Objective

Phase 4A now supplies persistent learning evidence and has been independently verified. Phase 4B is authorized and starts with single-skill BKT; the pure provider and versioned experimental parameters are complete. Next, persist SkillState and project only eligible Attempt completions with exactly one attributed skill. Preserve the full product flow: Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity. This plan does not authorize later tutor or adaptive features.

## Phase 4A — Learning Evidence / Session Vault

Implemented in migration `20260929_0004`. The active code stores canonical reasoning text in `REASONING_RECORDED.evidence`, keeps committed events append-only, and uses the MVP PRD Attempt route names. Public hint and understanding-check APIs remain deferred.

- Introduce `Attempt` as one learner engagement with a problem, with an explicit lifecycle (start, activity, completion) and optional reasoning capture. **Attempt ≠ Submission**: one Attempt can contain multiple existing Submissions and interventions. Associate new submissions with their Attempt; do not recreate the Phase 3 Submission entity or its evaluation pipeline.
- Introduce persistent `LearningEvent` history. Use append-oriented events for meaningful learner actions and execution/evaluation results. Preserve timestamps, references to Attempt/Problem/Submission as applicable, and source provenance. Corrections should be traceable; do not rewrite raw evidence to fit a later interpretation.
- MVP event types: `ATTEMPT_STARTED`, `REASONING_RECORDED`, `SUBMISSION_EVALUATED`, `HINT_REQUESTED`, `HINT_DELIVERED`, `ATTEMPT_COMPLETED`, `UNDERSTANDING_CHECK`. Add a type only when a concrete workflow requires it.
- Keep raw `evidence` and `derived_labels` separate. Link deterministic execution and test evaluation evidence into events without exposing hidden-test inputs, expected outputs, or private provider details through learner-facing APIs. Capture requested and delivered hint levels separately when hints exist; do not require the tutor to be implemented in this phase.
- Define learner-safe request/response schemas, validation, ordering/idempotency behavior, and ownership boundaries for Attempt and event APIs during implementation review. Add focused model, lifecycle, event, integration, validation, and redaction tests using isolated provider mocks.

## Phase 4B — Learner Model / Knowledge Tracing

Initial checkpoint: `KnowledgeTracingProvider` and pure BKT calculations are implemented with versioned parameters in `config/learner_model.json`. Current BKT accepts only binary, unassisted Attempt observations. Hint weighting and multi-skill attribution remain separate policy work; neither is inferred from a submission alone.

- Add `SkillState` as a derived projection and `KnowledgeTracingProvider` as a replaceable boundary. Implement BKT first, with model parameters and versions recorded rather than embedded as permanent architectural truths. An LLM must not calculate or directly change mastery.
- Update state from meaningful evidence: mastery probability and uncertainty, attempt and successful-attempt counts, independent solves, hint dependency, timing, recent errors, last attempt, and retention evidence where available. Preserve provenance for each derived observation and state transition.
- Define observation eligibility, independent-versus-assisted success, hint weighting, and error/understanding labels as explicit versioned rules. Do not hard-code every Level 3+ hint as an incorrect BKT observation unless the accepted implementation contract explicitly requires that policy; keep weights configurable enough for later evaluation.
- Support deterministic replay: given the same event history, model version, model parameters, and skill-attribution rules, the resulting learner state should be reproducible. Correct a derived label by retaining/correcting its provenance and rebuilding the projection, without replacing historical raw evidence.
- A problem may supply evidence for multiple skills. Keep attribution and evidence weighting behind a replaceable boundary (a `ProblemSkill`/weight mapping may be proposed during implementation review). Do not duplicate raw LearningEvents merely to cause multiple mastery updates. Define attribution before implementing multi-skill updates.
- Add focused tests for BKT updates, metrics, provenance, replay, corrections, hint distinctions, multi-skill attribution, and evidence that must not update mastery.

## Deferred Work

Defer AI tutor and LLM provider implementation, adaptive recommendation, LeetCode ingestion, retention scheduler, neural knowledge tracing, embeddings/RAG expansion, dashboard/UI, fine-tuning, local-model deployment, Kafka, Redis, and Kubernetes. These remain later product/MVP work where the PRDs require them; their visibility in an interface does not move them into Phase 4A or 4B.
