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

### Git

- `1f79d55 docs: freeze conservative Phase 4B learner-model policy` on `main`. Git remains the source for remote synchronization status.

## 2026-09-29 — Phase 4B v1 assistance reporting

### Completed

- Rebuilt single-skill `SkillState` reporting from terminal historical events independently of BKT observation eligibility. Assisted-only and abandoned Attempts now retain descriptive state at the configured mastery prior.
- Counted hint requests separately from delivered hint levels; reported hint-associated successful Attempts and replayed repeated Attempts without editing source events. Existing binary BKT and multi-skill deferral gates remain intact.

### Decisions

- Kept `hint_count_total` as request count and `average_hint_level` as the mean of valid delivered levels. `hint_dependent_count` describes successful Attempts with any recorded request or delivery, without implying a mastery penalty.
- Versioned the combined observation/reporting projection rule as `attempt-completion-binary-reporting-v1`. Fractional BKT and weighted multi-skill credit remain research only.

### Verification

- Focused learner-state/BKT suite: 18 passed. Complete suite: 45 passed, 1 opt-in Judge0 test skipped, 8 warnings. New coverage checks assisted SOLVED and GAVE_UP, multiple hints, request versus delivery counts, assisted-only reporting, repeated replay, and unchanged historical evidence.
- PostgreSQL Alembic current revision: `20260929_0005 (head)`. `alembic check` reported no new upgrade operations. No migration was created or applied for this reporting change.

### Git

- The implementation checkpoint commit and push result are recorded in Git; this entry describes the verified engineering milestone without duplicating source history.

### Next

- Evaluate reporting and mastery estimates using preserved evidence before accepting further observation policies. Multi-skill attribution, mistake and retention rules, tutor, adaptive engine, and UI remain outside this checkpoint.

## 2026-09-30 — Phase 6 AI Tutor architecture freeze

### Completed

- Readiness scan compared the PRDs, existing evidence/evaluation services, and tutor research. The tracked Phase 6 contract now specifies six public routes, event causality, retry behavior, safe provider context, and failure responses. No tutor implementation or schema change was made.

### Issues Encountered

- Research left the API contract incomplete, used `/attempts/{id}/hints` instead of the implementation PRD's `/hints/request`, and deferred an understanding check expressly listed as an AI Tutor responsibility. It also proposed atomic hint events, synthetic degraded diagnosis, legacy SDK/model choices, and direct recent-error state updates.

### Decisions

- Retained `POST /hints/request`, added the minimal deterministic-question/learner-answer/AI-evaluation understanding flow, and retained PRD Level 6 full explanation/solution only behind a versioned deterministic gate. Separate unrestricted solution generation remains deferred.
- `HINT_REQUESTED` commits independently; `HINT_DELIVERED` records only content actually delivered. Learner answers likewise persist before optional AI evaluation. Diagnosis, reasoning analysis, post-attempt explanation, and understanding evaluation fail with `503` rather than fabricated successful output.
- Delivered/received content is evidence; AI interpretations and confidence are derived labels; provider/model/prompt/policy identity is provenance. Any `recent_error_types` update must replay committed diagnosis events; mastery is untouched.
- Kept `TutorProvider` replaceable, chose `GeminiTutorProvider` with `google-genai` initially, and made `gemini-3.8-flash` a configurable default. Corrected the legacy SDK and retired Gemini 2.0 Flash proposals. Deferred MCP, RAG, fine-tuning, and later adaptive/UI work.

### Verification

- Documentation-only endpoint audit covered method, path, request, response, Attempt state, idempotency, events, and provider failure for every route. No application tests or migrations were run for this architecture checkpoint; the prior verified schema head remains `20260929_0005`.

### Next

- Begin Phase 6 implementation only under the tracked architecture contract and a separate implementation task; keep normal tests provider-independent.

## 2026-10-02 — Phase 6 AI Tutor implementation

### Completed

- Implemented provider-neutral contracts, deterministic mock and hint fallback, the six frozen tutor routes, bounded safe context, versioned prompts/gating, and a Gemini SDK adapter. Added immutable tutor events for delivered feedback, separate hint request/delivery, and separate understanding prompt/answer/evaluation.
- Preserved deterministic evaluation and binary BKT authority. Tutor flows read learner state for context but do not update SkillState or mastery; recent-error projection remains deferred.

### Issues Encountered

- GitHub HTTPS briefly refused connections after the diagnosis checkpoint; a later push synchronized both diagnosis and post-attempt commits. The local sandbox blocked `pip` inspection of a Windows Python installation; an approved external run installed the SDK and `pip check` passed.
- Final contract review caught the public fallback source label, client idempotency-key bound, and positive path-ID validation. All were corrected before final verification.

### Decisions

- Kept the configured Gemini model and SDK isolated behind `TutorProvider`. Level 6 has no static fallback because a generic template cannot safely supply a problem-specific solution. Provider failure returns `503` where no safe result exists and preserves separately committed learner actions.

### Verification

- Complete offline suite: 67 passed, 1 opt-in Judge0 test skipped (2026-10-02). Mock API and fake SDK tests cover all six routes, retries, idempotency, partial failure recovery, ownership, hidden-test redaction, malformed output, and unchanged mastery. `pip check` found no broken requirements.
- PostgreSQL Alembic current/head: `20260929_0005`; `alembic check` found no upgrade operations. No Phase 6 migration. Live Gemini output quality, latency, and account behavior remain unverified.

### Git

- Milestone commits: `3dfaf33` provider foundation; `62db895` hints; `fc6d14b` diagnosis/reasoning; `b8ef535` post-attempt flows; `0546981` Gemini adapter. Each was pushed to `main`; final hardening/documentation checkpoint follows.

### Next

- Run opt-in tutor quality/safety benchmarks and review model outputs before production use. Do not begin Phase 7 without separate scope acceptance.

## 2026-10-02 — Phase 6 closeout and blocked live verification

### Completed

- Closed Phase 6 for development: all six tutor endpoints and offline provider integration are complete. Updated status and plan to distinguish completion from externally blocked live verification.

### Issues Encountered

- Controlled live Gemini smoke requests reached the HTTP service with configured authentication, but `gemini-3.8-flash` returned `503 UNAVAILABLE` and `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. No successful live structured output was available to validate; no implementation defect was established.

### Decisions

- Accepted verdict: **Phase 6 complete — live provider verification externally blocked**. Retry Gemini verification later without blocking Phase 7 development. Production quality/safety validation remains outstanding; Phase 7 implementation requires separate authorization.

### Verification

- Offline suite: 67 passed, 1 opt-in Judge0 test skipped. Alembic head remains `20260929_0005`; `alembic check` found no new upgrade operations. No migration or application change was needed for closeout.
- Failure handling behaved correctly: safe hint fallback remained available; unsuccessful AI operations created no false delivered tutor evidence; hint requests and learner understanding answers remained preserved.

### Git

- Implementation/hardening checkpoint `1d3aaa1` was already synchronized with `origin/main`. This documentation-only closeout is recorded by `docs: close Phase 6 AI tutor implementation` in Git history.

### Next

- Retry minimal opt-in live verification when the provider is available; separately authorize Phase 7 scope before implementation.

## 2026-10-03 — Phase 7 architecture freeze

### Decisions

- Accepted the deterministic policy/service boundary, five PRD actions, immutable persisted decisions and one active recommendation per learner. Kept skill targeting single-skill/unit-weight and mastery/history unchanged.
- Corrected evidence-only invalidation: review deadlines, policy and catalogue changes also invalidate. MAX(event ID) is paired with committed event count because allocation order is not commit order. Abandonment is excluded from struggle; review is scheduling, not retention loss. Thresholds remain versioned, uncalibrated MVP defaults.

### Verification

- Baseline: 67 passed, 1 opt-in Judge0 test skipped; Alembic `20260929_0005`. Contract specifies API, lifecycle, transactions, recommendation-only migration and independent tests.

### Next

- Implement Phase 7 under the frozen contract; keep Phase 8 deferred. Architecture checkpoint is recorded in Git.

## 2026-10-03 — Phase 7 Adaptive Engine completion

### Completed

- Implemented the frozen `PHASE7_ADAPTIVE_ENGINE_CONTRACT.md`: typed pure policy and `config/recommendation_policy.json`, recommendation persistence/lifecycle services, allowlisted `GET /recommendations/next`, and transactional consumption through the existing Attempt-start service.
- Added deterministic cold start, difficulty adjustment, remediation, scheduled review, evidenced weak-skill targeting, catalogue coverage and conditional revisit. Every persisted decision selects a Problem and uses one of the five PRD actions with machine-readable reasons.
- Stored exact replay inputs, policy/projection versions, catalogue/mapping snapshots and learner-scoped event references. Maximum event ID plus committed count detects late lower-ID commits; fingerprints and review deadlines also invalidate cached decisions.
- Added isolated policy, persistence, service, API and Attempt fixtures/tests. Kept the existing execution abstraction, binary BKT and immutable event history unchanged.

### Issues Encountered

- Independent tests found a historical-attribution gap in revisit selection, expired ORM attributes allowing terminal recommendation reopening, and inconsistent UTC serialization on reuse. Each was fixed with regression coverage.
- The self-audit found malformed historical JSON and broken evaluation references could escape the safe failure boundary. Structured evidence, authority, references and integer pass counts now fail closed; supported invalid history returns `503` without rewriting evidence or learner state.

### Decisions

- Retained five PRD actions and versioned, uncalibrated thresholds. Abandonment breaks performance streaks without becoming incorrectness; review is a scheduling heuristic, not evidence of forgetting. Promotion requires independent performance on distinct Problems and weak-skill targeting requires actual observations.
- Shared User-row locking and a partial unique index protect one active recommendation. Fresh matching starts consume atomically; stale/different choices supersede; failed starts roll back and idempotent retrieval of an old Attempt cannot consume newer recommendations.
- Normal ORM/service behavior protects recommendation decisions; direct SQL remains outside that protection. Evidence committed after the final consistency check may stale a decision until the next request detects it.
- No catalogue seed was needed for correctness. The local database remains one Easy unmapped problem with no learner/activity rows; deterministic fixtures supply multiple skills/difficulties without manufacturing persistent learner activity. Multi-skill mastery, retention modelling, recent-error targeting and policy-quality evaluation remain deferred.

### Verification

- Baseline: 67 passed, 1 skipped. Final full suite: **263 passed, 1 opt-in Judge0 test skipped, 8 existing warnings**. New focused suites: policy 59, persistence 46, service 58, API 16 and Attempt integration 17.
- A guarded offline run (261 passed before the final two abandonment regressions) recorded zero live service/DNS attempts; only Windows standard-library event-loop socketpairs were allowed. No Gemini or Judge0 request was made by the normal suite.
- PostgreSQL migration `20261003_0006` follows `20260929_0005`. Upgrade, downgrade after confirming the new table empty, and re-upgrade passed; current/head is `20261003_0006` and `alembic check` reports no schema drift.
- Disposable localhost PostgreSQL concurrency checks confirmed two concurrent GETs reuse one decision and two concurrent matching starts create one Attempt/consume once. The isolated schema was removed; persistent learner data was unchanged. Read-only reviewer verdict: **APPROVED**.

### Git

- `b93a752` — architecture freeze; `77e8a57` — pure policy; `4144d1b` — persistence/migration.
- `3a3c236` — lifecycle orchestration; `57b50f1` — API; `f3623c5` — Attempt integration; `f8f7cec` — historical-evidence hardening.
- Each verified milestone was pushed to `origin/main`. This closeout is recorded by `docs: close Phase 7 adaptive engine implementation`; Git records its exact revision.

### Next

- Phase 8 readiness/architecture review only; UI implementation needs separate authorization. Retry externally blocked live Gemini verification independently. Recommendation-quality evaluation remains Phase 9 work; do not claim calibrated thresholds or optimal recommendations.

## 2026-10-03 — Phase 8 UI architecture freeze

### Decisions

- Accepted Streamlit per the MVP PRD, two primary screens, explicit local learner/demo provisioning and server-authoritative recovery. Resolved missing submission/learner/dashboard reads with allowlisted ownership-scoped DTOs and truthful reporting denominators.
- Separated sample-only isolated Run from persisted Submit; Run writes no learner evidence, mastery or recommendations. Refresh restores committed state, not unsaved drafts; understanding answers survive AI failure without automatic resubmission.
- Preserved frozen BKT, tutor and adaptive semantics. No new schema, authentication or browser-storage infrastructure is required. Phase 9 remains deferred.

### Verification

- Starting HEAD `4a2abb4`, clean and synchronized after fetch. Baseline: 263 passed, 1 opt-in Judge0 test skipped; Alembic `20261003_0006 (head)`. The local catalogue has no learner and no useful mappings, so explicit provisioning is necessary for the demo.

### Git

- Architecture checkpoint: `docs: freeze Phase 8 UI architecture`; Git records the exact revision and push.

### Next

- Implement safe backend support, demo provisioning and the Streamlit learning loop under the frozen contract.

## 2026-10-03 — Phase 8 Streamlit learning loop completion

### Completed

- Added public-sample `POST /runs`, ownership-scoped Submission recovery, learner/dashboard facades and safe skill labels. Run uses ExecutionProvider and writes no Submission, LearningEvent, mastery or recommendation state.
- Added explicit `python -m scripts.provision_demo`: six curated Problems, two Skills and unit-weight mappings, with idempotency/conflict checks and local database guards. No learner history, projections or recommendations are fabricated.
- Built Streamlit Home/Progress and Workspace with a typed HTTP client, explicit Attempt lifecycle, reasoning, distinct Run/Submit results, all six targeted tutor flows, truthful skill reporting and server-selected next activity. Kept frozen BKT, adaptive rules and historical events unchanged.
- Implemented safe URL recovery, stable session operation keys, persisted Submission/source restoration and lost-response reconstruction. Saved understanding answers are not automatically resent when AI evaluation fails.

### Issues Encountered

- Real local provisioning found legacy manually assigned IDs ahead of PostgreSQL sequences. Added upward-only sequence synchronization under local catalogue locks and regression tests; existing rows are preserved. Sequence advances are nontransactional and can leave harmless rollback gaps.
- Hardened malformed HTTP error translation so private server content remains excluded. No browser surface was available for visual verification; this remains a separate manual check, not a claimed pass.

### Decisions

- Frontend presentation remains outside database/services/providers; public schemas and HTTP are the only application boundary. Viewing a Problem does not start an Attempt and sample Run cannot authorize SOLVED.
- Global Attempt totals are distinct from supported skill reporting; independent/hint shares have explicit supported-success denominators. Mastery is an estimate, review is scheduling, and AI feedback is interpretation.
- Refresh recovers committed state, not unsaved drafts. Gemini failure preserves the core learning loop; successful live provider/model quality remains unverified. Phase 9 evaluation and production authentication remain deferred.

### Verification

- Baseline: 263 passed, 1 skipped. Final full offline suite: **353 passed, 1 opt-in Judge0 test skipped, 8 existing warnings**. Phase 8 suites: backend 26, provisioning 32, foundation 21, Streamlit AppTest 11. No live Gemini/Judge0 calls.
- AppTest exercised the full independent learning loop, all six tutor flows, assisted reporting without mastery, provider failure/fallback, unknown POST results, full-session recovery, recommendation consumption and hidden-data exclusion.
- Local PostgreSQL provisioning succeeded; rerun created zero rows. Original catalogue data was retained; persistent Attempt/Submission/LearningEvent/SkillState/Recommendation counts remained zero after provisioning.
- Disposable localhost FastAPI and Streamlit returned successful health/read responses. An HTTP learning-loop smoke test using isolated SQLite and fake execution/tutor providers passed. No learner code was executed or persistent learner activity manufactured. Browser visual/keyboard verification remains recommended.
- Alembic current/head remains `20261003_0006`; `alembic check` detected no new upgrade operations. No Phase 8 migration. Read-only reviewer verdict: **APPROVED** for the supplied contract, critical source and test scenarios; root/tester ran the tests independently.

### Git

- `e9063b6` — architecture freeze; `3c9a3a1` — safe backend reads/sample Run; `17b7dc9` — demo provisioning.
- `b55659b` — Streamlit/API foundation; `5269387` — legacy sequence fix; `884a306` — integrated workspace/progress/tutor/recovery flows.
- Verified milestones were pushed to `origin/main`. This closeout is recorded by `docs: close Phase 8 Streamlit implementation`; Git supplies its exact revision.

### Next

- Phase 9 readiness/evaluation architecture only. Manually inspect browser layout/keyboard use; retry externally blocked Gemini verification separately. Do not infer calibrated mastery, retention loss or validated recommendation quality from prototype completion.

## 2026-10-03 — Phase 9 evaluation architecture freeze

### Decisions

- Accepted a Git-versioned compact tutor suite and human rubric, provider-neutral invocation, three evaluation-only persistence tables, explicit resume and per-dimension comparison. Existing learner/evidence/tutor/adaptive semantics remain unchanged.
- Automatic contract checks are distinct from subjective human quality and longitudinal learner outcomes. Missing accounting stays unknown; synthetic oracle fixtures cannot establish model quality or justify production selection.
- Future live CLI calls require explicit candidates/suite, opt-in, timeout, maximum calls and cost acknowledgment. This autonomous run permits only offline/dry-run execution. No judge calls, production model selection or later-phase work.

### Verification

- Starting HEAD `358453c`, clean and synchronized after fetch; independent baseline **353 passed, 1 skipped**. Alembic `20261003_0006`. PRDs require same-case comparisons and stored results; current adapter lacks token counters and successful live verification remains blocked.

### Git

- Architecture checkpoint: `docs: freeze Phase 9 evaluation architecture`; Git records the exact revision.

### Next

- Implement and verify offline benchmark definitions, harness, persistence, review and comparison; keep real candidates and selection pending.

## 2026-10-05 - Phase 9 offline evaluation foundation completion

### Completed

- Added `benchmarks/tutor/v1/`: 25 standalone cases across hints, diagnosis, reasoning, explanation and understanding, with explicit gold/literal criteria and a ten-dimension anchored human rubric.
- Added strict provider-neutral contracts/loading/invocation, fresh input copies, bounded failure/retry handling, safe output validation and two clearly synthetic oracle/contrast candidates. No learner code execution or live model calls.
- Added evaluation-only plans/results/reviews, exact-plan resume, human-review import/export, explicit pricing snapshots and per-dimension comparison through `python -m scripts.run_tutor_benchmark`.

### Issues Encountered

- Continuation after the date changed exposed two existing Phase 8 acceptance failures: Attempt fixture clocks were frozen, recommendation creation was not. Aligned test clocks without changing application semantics or weakening assertions.
- Review corrected an explicit-zero timeout defaulting bug, excluded incomplete retry usage and mixed token bases from totals, and added a pre-invocation cost warning for the future live path.

### Decisions

- Automatic schema/gold/literal indicators remain distinct from human quality ratings and learner outcomes. Missing accounting is unavailable, not estimated; no composite winner or production selection occurs.
- Three evaluation-only tables have no learner foreign keys. Plans/results/reviews are immutable in normal ORM/services; direct privileged SQL and concurrent dispatch of one unfinished run remain outside MVP guarantees.
- Future live candidates require a clean recorded Git checkpoint, explicit suite/version/controls/call budget and cost acknowledgment. Gemini's evaluation-only SDK retry/temperature overrides preserve normal tutor defaults. Only Gemini is registered for future live execution; additional adapters require equivalent contracts.
- Tutor benchmark results cannot establish retention, mastery-estimation quality, hint-dependency behavior, recommendation quality or personalization gain. These empirical studies and actual model selection remain pending.

### Verification

- Focused evaluation suites: **109 passed** (62 definitions/invocation, 25 persistence, 22 CLI/comparison/review). Full offline suite: **462 passed, 1 opt-in Judge0 test skipped, 8 existing warnings**. Zero live Gemini/OpenAI/Anthropic/Judge0 calls; no new dependencies.
- Migration `20261003_0007` follows `20261003_0006`; local upgrade succeeded and Alembic detected no drift. Upgrade/downgrade/re-upgrade passed in a disposable PostgreSQL schema; its DDL was rolled back without changing learner data.
- Clean-checkpoint PostgreSQL CLI smoke group `e8de9213-4274-45bb-a5b7-07b4d1b5a5bd` persisted two synthetic runs and 50 results. Comparison/export passed; learner row counts were unchanged. Both had valid schemas; the oracle matched authored labels/literals while the contrast failed label checks and triggered literal flags. These are harness checks, not real-model quality claims. Cost remained unavailable and human ratings UNREVIEWED in those smoke runs.
- Isolated tests exercised appended sample human reviews, coverage/missing values, exact-plan resume, rollback, FK/uniqueness/immutability, malformed/unsafe output, provider isolation and preservation of every learner table. Generated exports stayed temporary and were not committed.

### Git

- `c96073d` - `docs: freeze Phase 9 evaluation architecture`.
- `55b39fb` - `feat(eval): add versioned tutor benchmark foundation`.
- `6a75b37` - `feat(eval): persist isolated benchmark results`.
- `d9167f3` - `feat(eval): add offline benchmark CLI and comparison`.
- Verified checkpoints were pushed to `origin/main`; final cost-safety/documentation closeout is recorded by `fix(eval): finish cost safety and evaluation closeout`. Git supplies that commit's exact revision.

### Next

- Accept candidate providers/models and an API/cost budget before real comparable runs; complete human rubric review before considering production selection. Existing live Gemini availability remains unresolved. No later-phase implementation.

## Document Roles

- `docs/PROJECT_STATUS.md` records current truth.
- `docs/plans/CURRENT_IMPLEMENTATION_PLAN.md` records the next approved work and phase boundaries.
- This log records historical engineering context.
- `docs/architecture/` records durable architecture decisions.
- Git history records exact source changes.

## Maintenance Rule

Update this log when a phase or sub-phase is completed; a meaningful architecture or research decision is accepted; an important blocker is found or resolved; migration or schema behavior changes materially; a significant test or security issue is resolved; or a milestone is committed and pushed. Do not add entries for trivial formatting, tiny fixes, routine commands, normal debugging noise, or every individual commit.
