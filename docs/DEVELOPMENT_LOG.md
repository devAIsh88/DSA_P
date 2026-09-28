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

## Document Roles

- `docs/PROJECT_STATUS.md` records current truth.
- `docs/plans/CURRENT_IMPLEMENTATION_PLAN.md` records the next approved work and phase boundaries.
- This log records historical engineering context.
- `docs/architecture/` records durable architecture decisions.
- Git history records exact source changes.

## Maintenance Rule

Update this log when a phase or sub-phase is completed; a meaningful architecture or research decision is accepted; an important blocker is found or resolved; migration or schema behavior changes materially; a significant test or security issue is resolved; or a milestone is committed and pushed. Do not add entries for trivial formatting, tiny fixes, routine commands, normal debugging noise, or every individual commit.
