# DEV Placement OS — Development Log

This is a milestone-based engineering history. Append new entries in chronological order. Git remains the exact source-code history; this log records the context, decisions, and verification behind meaningful checkpoints.

## 2026-09-05 — Foundation through execution checkpoint

### Completed

- Phase 1: FastAPI and PostgreSQL/SQLAlchemy foundation, Alembic, health endpoint, and tests.
- Phase 2: Skill, Problem, and TestCase catalogue with problem retrieval.
- Phase 3: Submission and TestResult persistence, Judge0 behind a replaceable `ExecutionProvider`, deterministic evaluation, and hidden-test redaction. Execution architecture research and its implementation contract are in `docs/research/phase3/`.
- The first tracked commit contains all three phases; separate completion dates for Phases 1 and 2 are not recorded in Git.

### Decisions

- Keep learner code outside the FastAPI process and execution behind `ExecutionProvider`; determine correctness through deterministic evaluation.

### Verification

- Alembic revisions `20260817_0001`, `20260828_0002`, and `20260904_0003` cover these phases. Project status records that the Phase 3 migration was applied and its tests passed; the historical test count is not recorded.

### Git

- `961c68fdfb94cea95fb7f208fcb89fb445a5c190` — `feat: complete phase 3 execution pipeline` (`main`). Historical push status is not recorded.

### Next

- Build persistent learning evidence before learner-state or higher-level AI features.

## 2026-09-29 — Phase 4A Learning Evidence / Session Vault

### Completed

- Added Attempt engagements with `ACTIVE`, `COMPLETED`, and `ABANDONED` states. Closed Attempts stay closed; a later revisit starts a new Attempt. One Attempt can contain multiple existing Submissions.
- Added append-only LearningEvents with separate raw `evidence`, `derived_labels`, and `provenance`. Learner reasoning is recorded in `REASONING_RECORDED.evidence`, the canonical history, rather than duplicated on Attempt.
- Linked evaluated Submissions to `SUBMISSION_EVALUATED` events. Each event has `occurred_at` and a per-Attempt `attempt_sequence`; appends lock the Attempt row and the database enforces unique sequence numbers.
- Added scoped idempotency keys and a unique evaluated-Submission rule to prevent duplicate evidence on retries. Learner-facing event responses allowlist safe fields and exclude hidden-test and protected execution details.
- Updated governance and planning documents and made `AGENTS.md` and `.agents/` trackable while retaining secret and environment ignore rules.

### Issues Encountered

- The learner-model contract conflicted with the PRD on canonical reasoning storage and Attempt endpoint names, and left committed-event immutability ambiguous. These were resolved before implementation.
- Review identified an ambiguous learner-ownership boundary. Attempt-linked APIs now require exactly one User row for this single-learner MVP and fail closed otherwise.

### Decisions

- Reasoning history belongs in `REASONING_RECORDED` LearningEvents. Committed LearningEvents have no normal update or delete path; a future correction mechanism must append new history.
- Retained the MVP PRD routes: `POST /attempts/start`, `POST /attempts/{attempt_id}/reasoning`, and `GET /attempts/{attempt_id}`, plus complete, abandon, and learner-safe event retrieval routes.
- Phase 4B learner state, BKT, mastery updates, hint weighting, and adaptive behavior remain deferred.

### Verification

- Full pytest suite: **27 passed, 1 skipped, 8 warnings in 1.82s**. The skipped test is the opt-in live Judge0 test.
- Alembic upgraded the local PostgreSQL database from `20260904_0003` to `20260929_0004`; `alembic current` reported `20260929_0004 (head)` and `alembic check` found no new upgrade operations.
- Read-only review approved the Phase 4A scope after the learner-ownership fix.

### Git

- `f782a0a6fc35fa0875292d184d7850b1e0553aad` — `feat: add Phase 4A learning evidence and session vault` (`main`); pushed to `origin/main` and synchronized at the checkpoint.

### Next

- Phase 4B Learner Model / Knowledge Tracing is the next planned increment, pending separate authorization.

## 2026-09-29 — Independent Phase 4A verification and closure

### Completed

- Rechecked Attempt lifecycle, event persistence/order, idempotency, submission association, learner-safe serialization, hidden-test redaction, and the retained `ExecutionProvider` boundary against the implementation and tests.
- Confirmed the Phase 4A migration follows `20260904_0003`; reviewed its downgrade operations without applying them to the existing local database.

### Decisions

- Normal services and APIs only append LearningEvents. Direct database mutation can bypass this contract; the current MVP does not require database triggers, so that limitation remains explicit.

### Verification

- Full suite: 27 passed, 1 opt-in live Judge0 test skipped, 8 warnings. Focused Phase 4A tests: 8 passed.
- `alembic history` confirmed the revision chain; `alembic current` reported `20260929_0004 (head)`; `alembic upgrade head` succeeded; `alembic check` found no new upgrade operations.

### Git

- Phase 4A implementation: `f782a0a6fc35fa0875292d184d7850b1e0553aad` on `main`. Git history records this closure document's own commit.

### Next

- Begin the authorized Phase 4B work with a single-skill BKT boundary and evidence-derived learner state. Multi-skill attribution remains an unresolved policy decision.

## 2026-09-29 — Phase 4B pure BKT checkpoint

### Completed

- Added a database-independent `KnowledgeTracingProvider` contract and initial BKT provider for binary, unassisted Attempt observations.
- Stored the experimental BKT parameters in a versioned configuration file. The provider calculates posterior mastery, applies the learning transition, clamps probabilities, and supports deterministic replay.

### Decisions

- Keep fractional hint weighting outside this first checkpoint. The current BKT provider rejects assisted or fractional observations instead of treating them as incorrect evidence. Multi-skill attribution remains unresolved.
- BKT parameters are starting values for data collection, not calibrated measurements; tests pass fixed values explicitly.

### Verification

- Focused BKT tests: 9 passed, covering correct/incorrect observations, transition, bounds, invalid parameters, replay, and policy boundaries. Full regression suite: 36 passed, 1 opt-in live Judge0 test skipped, 8 warnings.
- No schema change in this checkpoint.

### Git

- This milestone accompanies the pure BKT implementation commit on `main`; Git records the exact revision.

### Next

- Persist SkillState and project eligible, single-skill Attempt-completion evidence with replay and duplicate protection.

## 2026-09-29 — Phase 4B single-skill evidence-to-state checkpoint

### Completed

- Added `ProblemSkill` mapping and persisted `SkillState` with mastery, uncertainty, attempt metrics, timing, model versions, and latest evidence-event reference. Added a read-only, allowlisted learner skill API.
- On Attempt closure, captured a single skill in the immutable completion event when exactly one unit-weight mapping exists. The projection service replays eligible completion and prior evaluation events in event-ID order, then writes SkillState in the same transaction. Replaying or retrying cannot double-apply an observation.
- Kept unmapped, multiply mapped, non-unit-weight, assisted, abandoned, and incomplete/system-error evidence out of the initial BKT projection. Event provenance records why mapping did not qualify. Actual hint actions are summarized in submission and completion evidence without inventing hint behavior.

### Issues Encountered

- An initial replay draft depended on mutable Attempt and Submission rows. It was changed to derive observations from historical LearningEvents and captured attribution.
- A test exposed mixed naive and timezone-aware timestamps under SQLite. Replay now normalizes timestamps before comparison.

### Decisions

- `ProblemSkill.weight` is stored for future attribution work but is not applied to mastery; only a sole unit-weight mapping qualifies now. Multi-skill and fractional weighting remain unresolved.
- Do not amend committed LearningEvent provenance with model output. Store projection provenance on SkillState and retain immutable source events for replay; this follows the higher-priority event-immutability decision over the conflicting research-contract clause.
- No public replay or mapping-write route is exposed without an administrative authorization boundary. Recent-error and retention fields remain null until supported by evidence; hint metrics remain zero/null while assisted observations are deferred.

### Verification

- New Phase 4B integration tests: 7 passed. Full suite: 43 passed, 1 opt-in live Judge0 test skipped, 8 warnings. Coverage includes closure timing, multiple submissions, revisit, skill isolation, replay, duplicate protection, invalid evidence, rollback, ambiguous mappings, and learner-safe responses.
- Alembic `20260929_0005` follows `20260929_0004`. On the confirmed localhost database, upgrade, downgrade with empty new tables, and re-upgrade succeeded. Final revision: `20260929_0005 (head)`; `alembic check` found no schema drift.

### Git

- This milestone accompanies the single-skill evidence-to-state implementation commit on `main`; Git records the exact revision.

### Next

- Define the versioned hint observation policy and reporting threshold, then process assisted evidence; establish mistake/retention labels from validated sources. Resolve multi-skill attribution separately before any multi-skill mastery update.

## 2026-09-29 — Phase 4B v1 policy acceptance

### Issues Encountered

- A research proposal recommended fractional hint-weight observations and normalized multi-skill weights. Review found that standard BKT has binary observations: merely allowing a float in the current provider would treat every fractional value as incorrect. The proposal did not establish a calibrated soft-observation model or historical mapping snapshots for replay.

### Decisions

- Retain standard binary BKT for eligible independent, single-skill, unit-weight Attempts. Assisted, multiply mapped, and non-unit-weight Attempts do not update mastery in v1.
- Report assistance separately from mastery. Preserve hint requests and delivered levels as historical events; count request totals separately from delivered-level averages. Classify successful Attempts with any recorded hint request or delivery as hint-associated for descriptive v1 reporting, without a pedagogical threshold.
- Keep fractional hint-weight BKT and normalized `ProblemSkill.weight` mastery credit as research proposals. Future policies can be evaluated against preserved immutable events; projection metadata stays on derived state.

### Next

- Implement and verify replayable assistance reporting, including assisted-only histories, without a migration or new public hint API.

## Document Roles

- `docs/PROJECT_STATUS.md` records current truth.
- `docs/plans/CURRENT_IMPLEMENTATION_PLAN.md` records the next approved work and phase boundaries.
- This log records historical engineering context.
- `docs/architecture/` records durable architecture decisions.
- Git history records exact source changes.

## Maintenance Rule

Update this log when a phase or sub-phase is completed; a meaningful architecture or research decision is accepted; an important blocker is found or resolved; migration or schema behavior changes materially; a significant test or security issue is resolved; or a milestone is committed and pushed. Do not add entries for trivial formatting, tiny fixes, routine commands, normal debugging noise, or every individual commit.
