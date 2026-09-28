# Current Implementation Plan

This is the active engineering plan for Phase 4B. Product PRD v0.3 (`DEV Placement OS.docx`) governs long-term direction; the Python MVP Implementation PRD v0.1 governs MVP scope and order. The 4A/4B labels below split its Phase 4 (learning events) and Phase 5 (learner model) without changing that sequence. See `docs/architecture/LEARNER_EVIDENCE_AND_STATE.md` for the stable data boundary.

## Current State

- Phase 1 foundation is complete: FastAPI, PostgreSQL/SQLAlchemy, Alembic, health endpoint, and tests.
- Phase 2 problem system is complete: Skill, Problem, TestCase, and problem retrieval.
- Phase 3 execution/evaluation is complete: existing Submission and TestResult persistence, replaceable `ExecutionProvider` with Judge0 adapter, deterministic evaluation, and hidden-test redaction. The Phase 3 migration is applied and its tests passed, per the verified project state. Execution architecture and implementation contract are in `docs/research/phase3/`.
- Phase 4A Learning Evidence / Session Vault is complete: Attempt lifecycle, append-only LearningEvents, Attempt-linked Submission evidence, ordering, idempotency, and learner-safe event responses. Migration `20260929_0004` is applied.
- Learner-model architecture research and implementation contract are in `docs/research/learner-model/`. User-accepted Phase 4A decisions govern reasoning in event evidence, immutable committed events, and the MVP PRD Attempt route names where that contract differs.

## Next Objective

Phase 4A supplies independently verified persistent evidence. Phase 4B has a working single-skill slice: eligible unassisted Attempt completions replay into persisted SkillState. Next, define hint observation and metric rules, then extend evidence processing without changing raw history. Preserve the full product flow: Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity. This plan does not authorize later tutor or adaptive features.

## Phase 4A — Learning Evidence / Session Vault

Implemented in migration `20260929_0004`. The active code stores canonical reasoning text in `REASONING_RECORDED.evidence`, keeps committed events append-only, and uses the MVP PRD Attempt route names. Public hint and understanding-check APIs remain deferred.

- `Attempt` groups one learner engagement with a problem. **Attempt ≠ Submission**: one Attempt can contain multiple existing Submissions and interventions.
- `LearningEvent` persists meaningful actions and execution/evaluation results with ordering, references, and source provenance. Do not rewrite raw evidence to fit a later interpretation.
- MVP event types: `ATTEMPT_STARTED`, `REASONING_RECORDED`, `SUBMISSION_EVALUATED`, `HINT_REQUESTED`, `HINT_DELIVERED`, `ATTEMPT_COMPLETED`, `UNDERSTANDING_CHECK`. Add a type only when a concrete workflow requires it.
- Keep raw `evidence` and `derived_labels` separate. Link deterministic execution and test evaluation evidence into events without exposing hidden-test inputs, expected outputs, or private provider details through learner-facing APIs. Capture requested and delivered hint levels separately when hints exist; do not require the tutor to be implemented in this phase.
- Learner-safe schemas, validation, ordering/idempotency, and the single-learner ownership boundary are implemented and covered by isolated provider tests.

## Phase 4B — Learner Model / Knowledge Tracing

Implemented checkpoints: `KnowledgeTracingProvider` and pure BKT calculations use versioned experimental parameters in `config/learner_model.json`; migration `20260929_0005` adds `ProblemSkill` and `SkillState`. Attempt closure snapshots a skill only when exactly one mapping has unit weight. A service replays eligible completion events by event ID, validates prior deterministic evaluation events, and updates SkillState in the same transaction as the completion event. Reprocessing the same history cannot double-apply mastery. `GET /learner/skills` and `GET /learner/skills/{skill_id}` expose allowlisted projection fields. Current BKT accepts only binary, unassisted Attempt observations.

Remaining Phase 4B work: define versioned hint weighting and the reporting threshold for hint dependency before assisted Attempts update mastery; establish mistake labels and retention signals from real evidence; decide whether an authenticated administrative replay endpoint is needed. Historical Phase 4A completions without a captured `skill_id` are not retroactively attributed. Problems with no mapping, multiple mappings, or non-unit weights still close but do not update mastery; their event provenance records the reason. The `ProblemSkill.weight` column has no effect on BKT in this slice. No public mapping-write endpoint exists. Multi-skill attribution needs an explicit future policy.

- Keep `SkillState` derived from immutable events and `KnowledgeTracingProvider` replaceable. BKT is the initial method, with model parameters and versions recorded rather than embedded as permanent architectural truths. An LLM must not calculate or directly change mastery.
- Update state from meaningful evidence: mastery probability and uncertainty, attempt and successful-attempt counts, independent solves, hint dependency, timing, recent errors, last attempt, and retention evidence where available. Preserve provenance for each derived observation and state transition.
- Define observation eligibility, independent-versus-assisted success, hint weighting, and error/understanding labels as explicit versioned rules. Do not hard-code every Level 3+ hint as an incorrect BKT observation unless the accepted implementation contract explicitly requires that policy; keep weights configurable enough for later evaluation.
- Support deterministic replay: given the same event history, model version, model parameters, and skill-attribution rules, the resulting learner state should be reproducible. A future correction must append new history and rebuild the projection without replacing historical raw evidence.
- A problem may supply evidence for multiple skills. `ProblemSkill` stores the relation, but multi-skill attribution and evidence weighting remain unimplemented. Do not duplicate raw LearningEvents merely to cause multiple mastery updates. Define attribution before implementing multi-skill updates.
- Keep focused tests for implemented BKT updates, provenance, replay, eligibility, transaction failure, and hidden-evidence protection. Add hint and multi-skill policy tests only when those policies are implemented.

## Deferred Work

Defer AI tutor and LLM provider implementation, adaptive recommendation, LeetCode ingestion, retention scheduler, neural knowledge tracing, embeddings/RAG expansion, dashboard/UI, fine-tuning, local-model deployment, Kafka, Redis, and Kubernetes. These remain later product/MVP work where the PRDs require them; their visibility in an interface does not move them into Phase 4A or 4B.
