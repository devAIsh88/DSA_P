# Phase 8 Streamlit UI Contract

**FROZEN — 2026-10-03.** Product PRD v0.3 governs direction; Python MVP Implementation PRD v0.1 sections 25–27, 33 and 34 require the prototype UI and complete learning loop. Phase 8 implementation is authorized. Preserve the frozen learner-state, tutor and adaptive contracts.

## Architecture and screens

Streamlit is the PRD-selected prototype. It calls public FastAPI HTTP contracts through one typed API client; it never imports database models/sessions, application services, execution/tutor providers or vendor SDKs. Home/Progress and Problem Workspace are the two primary screens; results and tutor feedback are workspace sections. Backend state is authoritative. No authentication system, new database schema, browser draft store or UI session table is introduced.

Run and Submit are distinct. Neither UI presentation nor tutor interpretation changes correctness, mastery, historical events or recommendation rules. Estimated mastery is not certainty; scheduled review is not forgetting. No Phase 9 evaluation, unsupported readiness/retention metrics, generic chat or new adaptive policy is in scope.

## Local learner and explicit demo provisioning

Use `python -m scripts.provision_demo` explicitly in development/test/demo only. Create a User if none exists, reuse the sole existing User, and fail on ambiguous ownership. Create two concept Skills and six curated Python stdin/stdout Problems across Easy/Medium/Hard with public samples, hidden grading cases and sole unit-weight mappings. Identify demo catalogue by stable source/title; verify existing demo rows rather than overwrite conflicting data. A rerun is idempotent and a conflict rolls back. Never create Attempts, Submissions, LearningEvents, SkillState or Recommendations; no automatic startup seeding.

The command prints the learner ID. Streamlit reads `UI_LEARNER_ID` from local environment; `GET /learner/state` supplies the existing single learner identity, and a mismatch fails clearly before writes. A missing configured ID or absent/ambiguous backend learner is a setup error, not account creation. `UI_API_BASE_URL` defaults to localhost and `UI_REQUEST_TIMEOUT_SECONDS` controls bounded HTTP waits. Only safe example variables belong in `.env.example`.

## Required backend contracts

All read facades resolve the sole learner and enforce ownership. Missing learner/reference is 404; ambiguous or invalid ownership is 409; malformed requests are 422. Routes remain thin and DTOs explicit. These reads never project state or issue/consume recommendations.

### Sample Run

`POST /runs` accepts `{problem_id: positive int, code: nonempty str, language: python3}` (`python` normalizes to `python3`). It does not require an Attempt. Load only TestCases with `is_sample=true AND is_hidden=false`, ordered by ID. Use the existing isolated ExecutionProvider and deterministic evaluation/resource limits. Do not execute Python in Streamlit/FastAPI.

Return 200 `RunResponse`: `problem_id`, `overall_status`, `tests_passed`, `tests_total`, `edge_cases_failed`, `execution_time_ms`, `memory_used_kb`, `test_results` using the existing learner-safe result schema. Missing Problem is 404; no public samples is 409 `NO_PUBLIC_SAMPLE_TESTS`; provider failure returns a safe `SYSTEM_ERROR` result. Run creates no Submission, event, learner-state or recommendation write and invokes no AI. A passing Run never authorizes SOLVED completion.

### Submission recovery

`GET /submissions/{submission_id}` returns the existing redacted `SubmissionResultResponse` plus `problem_id`, nullable `attempt_id`, `language`, learner-owned `code`, and `created_at`. Require a linked Attempt owned by the sole learner. Missing Submission is 404; unlinked historical records or ownership ambiguity/mismatch are 409 because ownership cannot safely be established. Never return hidden inputs/expected outputs, protected stderr/compile details, tokens or provider internals. Reads do not write.

`POST /submissions` retains its existing authoritative, persisted grading semantics; UI always supplies active Attempt ID and an operation key. HTTP success is not code acceptance. SOLVED requires the latest persisted Submission accepted, as the existing service enforces.

### Learner facade and skill labels

`GET /learner/state` returns `LearnerStateResponse`: `user_id`, `active_attempts: list[AttemptResponse]`, `skills: list[SkillProgressResponse]`. SkillProgress extends the existing skill response with `skill_name` and nullable `skill_description`; expose only actual projections, not fabricated prior rows. Existing `/learner/skills` contracts remain compatible. Sort active Attempts and skills by ID.

### Dashboard

`GET /dashboard/summary` returns `DashboardSummaryResponse`:

- `user_id`, `catalogue_problem_count`;
- `attempt_count`, `completed_attempt_count`, `solved_attempt_count`, `abandoned_attempt_count`, `unique_solved_problem_count` over this learner's actual Attempts;
- `active_attempts`, `recent_attempts` (latest ten by Attempt ID), `skills` with public labels;
- `hint_request_count`, `hint_delivery_count` over this learner's actual respective events, counted separately;
- `independent_solve_count`, `hint_dependent_solve_count`, `successful_supported_attempt_count` summed from existing supported SkillState reporting;
- `independent_solve_share` and `hint_dependency_share`: corresponding supported solve count divided by `successful_supported_attempt_count`, null for zero denominator;
- `existing_recommendation: RecommendationResponse | null`, the persisted active snapshot, explicitly possibly stale. `/recommendations/next` remains the freshness/issuance authority.

Global Attempt totals are distinct from supported skill reporting. Skill hint_count_total remains request count, average_hint_level is mean valid delivered levels, and average_duration_ms is terminal Attempt duration, not successful-solve time. Do not expose private projection/recommendation snapshots, fabricate global accuracy/readiness, or label 1−P as calibrated statistical confidence. Recent-error/retention projections remain deferred.

## Workspace and tutor

Viewing a Problem does not start an Attempt. Explicit Start uses configured learner ID and a session-retained key. Resume first when active activity exists; handle multiple active IDs without pretending global exclusivity is enforced. ACTIVE enables reasoning, Run, Submit and active tutor actions. Closed solving history is read-only; retry creates a new Attempt. COMPLETED enables post-explanation and understanding checks. Browser closure does not abandon.

Reasoning is optional; explicit saves append history. Display Python source as text, public samples and safe result details only. Run is labeled sample practice; Submit is grading and evidence. Disable conflicting actions while requests are pending. Separate deterministic verdict, AI interpretation and learner evidence visually and semantically.

Use all six frozen tutor routes without changing their semantics. Diagnosis targets an evaluated Submission; reasoning analysis targets saved reasoning. Hint requests/deliveries are separate and the backend controls Level 6 gating. Show fallback source when returned. Post-attempt questions are deterministic. If understanding evaluation fails after the answer commits, reconstruct evidence and show “Answer saved; AI evaluation unavailable.” Never automatically resend a recorded answer. All core operations remain usable without Gemini. No live provider calls in normal tests.

## State, retry and recovery

URL contains only positive `problem_id`, `attempt_id` and view identifier. No code, reasoning, answers, keys or secrets. Streamlit session memory holds drafts, response DTOs, loading state and operation keys; it is not historical truth and full reload may lose unsaved drafts. No browser localStorage dependency.

Create a stable key per explicit operation and retain it until resolved; a changed payload/new intentional action receives a new key. Never automatically retry POSTs in the HTTP client. On an unknown result, inspect authoritative Attempt/events/Submission first; same-session explicit retries reuse the original key/payload. Full-session recovery reconstructs committed state rather than blindly resubmitting.

On workspace load fetch Attempt, Problem and ordered events. Recover latest persisted Submission from SUBMISSION_EVALUATED references and GET its safe DTO/source. Restore persisted reasoning, delivered hints, explanation/question/answer/feedback text. Generic events omit internal AI labels and keys; do not invent lost classifications. Pending understanding answers remain saved without automatic evaluation retry after key loss. A new question is a new explicit interaction.

Home reads summaries and calls `/recommendations/next` only explicitly/when safe, not on every widget rerun. Handle active Attempt 409 as Resume; scheduled review, cold start, retry, progression and demotion use backend reason codes. Empty catalogue/no candidate/exhaustion and projection/service 503 are explicit states; catalogue/workspace remain accessible. Start consumption/supersession belongs solely to the existing Attempt service.

## Security, tests and acceptance

Render learner/code/stdout/AI content as text or safe default Markdown, never unsafe HTML. No secret logging or environment dump. Streamlit talks to FastAPI server-to-server; no browser CORS addition or public deployment/authentication is needed for this local MVP. No hidden test material or protected diagnostics enter Run or UI responses. Do not cache private learner responses globally across sessions.

Use pytest, isolated SQLite and fake execution/MockTutorProvider. Test read ownership/redaction/denominators; Run zero persistence; explicit provisioning idempotency/conflict rollback/no history; API client errors/serialization; Streamlit AppTest navigation/state/results/tutor/empty states; recovery and terminal guards. No learner code execution in tests. A controlled fake provider returns specified statuses.

Acceptance: provision isolated catalogue → Home/recommendation → view Problem → explicit Start → save reasoning → sample Run with no new evidence → failed Submit → advisory diagnosis/reasoning → corrected Run/accepted Submit → explicit SOLVED → state refresh → post-understanding → next recommendation → fresh matching Start/consumption. Separate assisted and provider-failure branches verify reporting without mastery and continued core operation. Full offline regression and Alembic current/check are required. Real-browser visual checks are reported separately from AppTest; successful live Gemini remains externally blocked and is not a Phase 8 gate.

## Checkpoints and deferral

Architecture → required read/Run support → explicit demo → Streamlit foundation → workspace/lifecycle → execution → tutor → progress/recommendation → recovery/E2E/audit → closeout. Commit coherent verified milestones, with no forced micro-commits. Alembic remains `20261003_0006`; no migration is required. Phase 9 benchmarks/evaluation, model choice, multi-skill mastery, retention/error projections, placement-readiness scores, custom-input execution, authentication and production UI remain deferred.
