# Learner Evidence and State Boundary

This note defines the conceptual boundary for the Python MVP evidence pipeline. Product PRD v0.3 requires a persistent Session Vault and separation of raw evidence from interpretation. The Python MVP Implementation PRD v0.1 specifies `LearningEvent`, initial BKT, and learner-state fields. Schema/API details require implementation review.

**Attempt → Submission / intervention evidence → LearningEvent → KnowledgeTracingProvider → SkillState**

The surrounding learning flow is Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity. Evidence and state must be in place before later tutor and adaptive behavior is built.

## Attempt

An Attempt is one learner engagement with a problem. It may contain reasoning, multiple submissions, requested/delivered hints, corrections, and a final outcome. Its lifecycle groups these actions without treating a single code run as the whole learning episode. Completion and later retry semantics need an explicit implementation decision.

## Submission

A Submission is one code submission/execution and its deterministic evaluation. Phase 3 already persists Submission and TestResult; multiple Submissions may belong to one Attempt. The Attempt association must extend this structure, not replace it. Execution stays behind `ExecutionProvider`; test correctness stays with deterministic evaluation. Hidden test data remains private in every learner-facing representation.

## LearningEvent and Session Vault

LearningEvent is persistent historical evidence for meaningful actions and results. It references the learner, Attempt, Problem, Submission, skills when attributable, and the relevant time/source. Keep `evidence` (observed learner actions, code/execution/test outcomes, hints, timing) separate from `derived_labels` (for example, a possible mistake classification) and `provenance` (source references, derivation/rule/model identity). Prefer structured JSON/JSONB for flexible event payloads where appropriate; do not redesign existing relational entities without implementation review.

The history is append-oriented. Preserve original evidence when labels are corrected or algorithms change. Avoid duplicating a raw event for every skill projection. Provide learner-safe API views that cannot reveal hidden tests, secrets, or internal execution details.

## SkillState

SkillState is a derived learner-state projection, not the authoritative historical record. The MVP projection needs mastery probability; confidence/uncertainty; attempts and successful attempts; independent solves; hint count, level, and dependency metrics; timing; recent mistakes; last attempt; and retention evidence where available. A successful submission alone does not establish mastery. Independent and assisted success are distinct evidence.

## Provenance and Knowledge Tracing

Every derived observation and state transition must be traceable to source events, any derived-label version, skill attribution, model/rule version, and parameters. Deterministic execution and evaluation take precedence over unsupported LLM claims. An LLM may help diagnose or classify with recorded provenance, but it cannot directly calculate or mutate mastery.

Use a replaceable `KnowledgeTracingProvider` boundary. BKT is the initial MVP implementation, with versioned/configurable parameters and observation rules, including hint weighting. Future algorithms must be able to replace BKT without rewriting the Event Store, Execution Engine, Problem system, or API architecture. Multi-skill attribution remains a separate replaceable rule; one event can inform more than one skill without duplicating raw evidence.

## Replay Principle

Retain event history so learner state can be recomputed when model parameters, the tracing algorithm, skill attribution, or a derived label changes. Given the same event history, model version, parameters, and attribution rules, replay should reproduce the same SkillState. Corrections must preserve the original raw evidence and the provenance of the revised interpretation.
