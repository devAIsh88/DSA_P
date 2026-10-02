# Phase 7 Adaptive Engine Contract

**FROZEN — accepted reconciliation, 2026-10-03.** Product PRD v0.3 governs direction; Implementation PRD v0.1 sections 20, 27 and 33 require deterministic recommendation, revision, weak-skill targeting, persistence and `GET /recommendations/next`. This contract preserves Phase 4B v1 and the immutable evidence boundary.

## Scope and responsibilities

- `RecommendationPolicy` is a pure function over typed, bounded inputs: no SQLAlchemy, FastAPI, providers, network or side effects.
- `RecommendationService` loads learner/evidence/catalogue, validates projections, builds candidates/context, invokes policy, persists decisions and controls lifecycle/transactions.
- `RecommendationContext`: UTC evaluation time; learner-scoped immutable terminal facts; supported SkillState snapshots and their versions; candidates; full visible event boundary; active Attempt IDs.
- `RecommendationCandidate`: Problem ID, recognized difficulty, supported single skill or null, mapping status and public target metadata. Skill-targeted eligibility requires exactly one mapping with weight exactly 1.0.
- `RecommendationDecision`: action, actual Problem ID, nullable supported Skill ID, ordered reason codes. Empty policy output has an explicit unavailable reason.
- `RecommendationPolicyConfig`: versioned defaults and target filter. Changing any rule/default requires a new policy version; capture exact config in every persisted input snapshot.
- Policy never changes LearningEvents, SkillState, mastery, BKT eligibility or ProblemSkill weights. No AI or execution-provider dependency.

## Actions and reasons

All persisted decisions select a real Problem. Five actions are required by the implementation PRD:

| Action | Semantics | Reasons |
|---|---|---|
| NEXT_PROBLEM | Baseline or catalogue coverage | COLD_START, UNPRACTICED_SKILL, NEW_PROBLEM, UNATTRIBUTED_CATALOGUE |
| REVISE_CONCEPT | Practice a review problem for an identified skill | SCHEDULED_REVIEW_DUE |
| RETRY_SIMILAR_PROBLEM | Same-skill/current-level practice, or explicit original-problem retry | EVALUATED_FAILURE_RETRY, ASSISTED_SUCCESS_PRACTICE, ABANDONED_PROBLEM_RETRY, DECLARED_GIVE_UP_RETRY, INDEPENDENT_PRACTICE_PENDING |
| INCREASE_DIFFICULTY | Next configured difficulty | INDEPENDENT_SUCCESS_PROGRESSION |
| DECREASE_DIFFICULTY | Previous configured difficulty | CONSECUTIVE_EVALUATED_FAILURES |

The four skill-targeted actions require a supported Skill ID. An explicit abandoned-problem retry may have null Skill ID. No sixth resume action; retry always starts a new Attempt.

## Evidence and defaults

Terminal facts come from immutable `ATTEMPT_COMPLETED` and preceding same-Attempt `SUBMISSION_EVALUATED`/hint events, with matching learner/problem/references and accepted source/rule provenance. Use existing Phase 4B binary eligibility, including independent GAVE_UP without submission; such a declaration is not evaluated struggle evidence. Deduplicate terminal facts by Attempt and order by completion event ID, as existing replay does.

State reporting counts include assisted and abandoned activity; they are not BKT observation counts. Derive eligible observation count from history. `mastery_uncertainty` currently equals 1-P and is not an independent confidence measure. Missing state with reportable supported history, mismatched source watermark or incompatible model/parameter/projection versions is `503 LEARNER_STATE_NOT_READY`; do not rebuild state inside recommendation reads.

Excluded: hidden tests/outputs, stderr/compile details, code/reasoning text, model confidence as truth, unsupported historical attribution and stale/incomplete execution. AI recent-error and retention projection remain deferred. Recent deterministic failed outcomes may guide retry. Never reinterpret unmapped historical completions using today's mapping.

**CONFIGURABLE MVP DEFAULTS — uncalibrated heuristics**, stored in `config/recommendation_policy.json`, initial version `adaptive-rules-v1`:

| Setting | Default |
|---|---|
| Difficulty order | Easy, Medium, Hard (trim/case-insensitive recognition) |
| Weak minimum binary observations / threshold | 2 / mastery <= 0.50 |
| Review minimum independent successes / mastery / interval | 1 / >= 0.60 / 7 days |
| Promotion mastery / consecutive independent solves | >= 0.70 / 2, distinct Problems at the same difficulty |
| Consecutive demotion struggles | 2 |
| Demotion statuses | WRONG_ANSWER, TIME_LIMIT_EXCEEDED, MEMORY_LIMIT_EXCEEDED |
| Assisted-success remediation | actual maximum delivered hint level >= 4 |
| Avoid immediate repetition / unattributed catalogue fallback | true / true |
| Target-track filter | null (no inferred learner goal); non-null exact trimmed match |

Independent binary success rate = correct eligible observations / eligible observations; zero denominator is unavailable. Hint-associated success ratio = hint-dependent successful Attempts / successful Attempts; zero denominator is unavailable. Requests keep existing reporting semantics; actual delivery is required for the assistance-remediation threshold. None changes mastery.

## Cascade and deterministic selection

The first stage with an eligible candidate wins. Active Attempt is an API gate, not an action. For current-level stages, latest means the learner's latest valid terminal fact; historical difficulty is the current catalogue value captured in the input snapshot, not a claimed historical snapshot.

1. **Cold start:** no valid terminal history. Lowest recognized difficulty, supported mappings before unattributed fallback, then Skill ID/Problem ID. Establish evidence before interpreting weakness.
2. **Demotion:** latest fact and the preceding fact for that skill are independent completed GAVE_UP at the same difficulty, each with referenced deterministic evaluation in the allowed demotion statuses. Select previous difficulty. Abandonment, assistance, success, missing/system/incomplete evaluation or a different difficulty breaks the streak. Reduce the unsuccessful challenge before ordinary retry.
3. **Remediation:** latest supported terminal fact has GAVE_UP with evaluated failure (including compilation/runtime errors), or SOLVED with actual delivered hint meeting threshold. Select same skill/current difficulty, alternative Problem preferred. Address immediate outcome before review/advancement.
4. **Revision:** prior eligible independent success, mastery threshold reached and interval elapsed from latest eligible independent success. Select most overdue skill, then Skill ID; use the latest independently solved Problem if still supported. Reason is scheduled review, never forgetting. Review precedes advancement.
5. **Promotion:** latest fact belongs to the qualifying run of independent SOLVED facts at the same difficulty on distinct Problems; mastery threshold reached. Select next difficulty. Corroborated advancement precedes general coverage.
6. **Weak skill:** enough eligible observations and low mastery. Rank mastery ascending, available hint-associated success ratio descending, available independent binary success rate ascending, last practice oldest, Skill ID. Missing ratios follow available values; they are not zero. Select current level (lowest available level if no recognizable anchor), unattempted Problems preferred.
7. **Catalogue coverage:** choose unattempted supported Problems by least-practiced skill, then Skill ID, current level when available (otherwise lowest level), Problem ID. No inferred prerequisite/curriculum sequence. If no supported unattempted candidate exists, permitted unattributed candidates may supply NEXT_PROBLEM with null Skill ID.
8. **Conditional revisit:** latest abandonment may retry its original eligible catalogue Problem; otherwise oldest declared GAVE_UP or assisted-only solved Problem, then Problem ID. Independently solved stable Problems are not recycled unless review is due.

Within a stage, prefer unattempted candidates, then an alternative to the latest Problem when enabled, then Problem ID. If no required adjacent/current difficulty exists, fall through rather than changing an action's meaning. Unknown difficulty and target-filter mismatch are excluded. No mapping, multiple mappings and non-unit weight are permitted only for catalogue baseline/coverage and explicit abandonment fallback, with null Skill ID and recorded exclusion status. Do not normalize weights or infer mastery.

## Evidence cursor, replay and invalidation

Persist `(evidence_through_event_id, evidence_event_count)` over all visible learner LearningEvents. No history means `(null, 0)`. IDs are stable but allocated before commit; MAX(id) alone misses later lower-ID commits. Read the pair from one snapshot and materialize complete relevant history, not just IDs above the previous maximum. Preserve exact event references in decision inputs.

Also fingerprint current policy/config, catalogue/mappings and used SkillState values/versions. Capture public candidate metadata so replay survives later edits. `created_at` is the explicit policy evaluation clock. `reevaluate_at` is the earliest future review deadline among skills otherwise eligible for review; its arrival invalidates without new evidence. No continuous time score, inferred retention loss or background scheduler.

Issuance acquires the User row lock shared with new Attempt starts. Under existing READ COMMITTED conventions, assemble immutable inputs, check evidence boundary/catalogue/projection consistency before persistence, and retry boundedly on changed inputs/conflicts. Newly committed evidence after validation may make a decision stale; the next GET detects it. No Attempt-row lock inside recommendation issuance, avoiding the existing closure Attempt->User lock cycle.

## Persistence and lifecycle

New `Recommendation` table:

- `id`, `user_id` FK, `action_type`, required `problem_id` FK, nullable `skill_id` FK.
- `policy_version`, JSONB `reason_codes`, nullable FK `evidence_through_event_id`, nonnegative `evidence_event_count`.
- JSONB `input_snapshot`, 64-character `input_fingerprint`, UTC `created_at`, nullable `reevaluate_at`.
- Nullable `consumed_at`, paired nullable FK `consumed_attempt_id`, nullable `superseded_at`.

Decision columns are immutable through normal ORM/service behavior. Lifecycle only transitions ACTIVE->CONSUMED or ACTIVE->SUPERSEDED, never both/reopened; no public update/delete. No database triggers. Active means both lifecycle timestamps null. PostgreSQL partial unique index on `user_id` for active rows plus User locking provides one active recommendation. Check action values, evidence count, paired consumption reference, exclusive terminal timestamps, timestamps >= creation and supported skill requirement (null allowed for explicit abandonment retry).

GET reuses a fresh active decision. Evidence/config/catalogue/projection change or reached deadline supersedes and replaces in one transaction. Empty result supersedes stale decision but creates no fake recommendation. Failure rolls back and never returns an unpersisted decision.

New `POST /attempts/start` processing takes the User lock, validates recommendation freshness before the opening event, and consumes only an exact user/problem match, atomically with successful new Attempt and event. Stale matching or different-problem recommendations are superseded. Failed creation rolls back lifecycle changes. Existing idempotent Attempt-start retrieval does not consume a newer decision. Existing per-user/problem ACTIVE Attempt constraint is unchanged; no global ACTIVE Attempt DDL.

## Exact API

Only `GET /recommendations/next`; no body or query parameters. Resolve exactly one existing learner; do not create one implicitly.

- `200`: `{recommendation: {id, action_type, problem_id, skill_id, policy_version, reason_codes, created_at}, unavailable_reason: null}`.
- Empty `200`: `{recommendation: null, unavailable_reason: EMPTY_CATALOGUE | NO_ELIGIBLE_PROBLEM | CATALOGUE_EXHAUSTED}`. Empty table, all candidates excluded, or no remaining fresh/remedial/due activity respectively.
- `404`: learner missing.
- `409`: ambiguous learner, or `{detail: {code: ACTIVE_ATTEMPT_EXISTS, attempt_ids: [sorted IDs]}}`. With active Attempt(s), no recommendation is created/recomputed and no sixth action returned.
- `503`: persistence unavailable or required projection not ready. No LLM fallback.

Responses are allowlisted; never expose snapshots, private evidence/provenance or hidden execution data. GET may persist on first access but never consumes. Routes contain no ranking logic.

## Migration, verification and deferred work

One revision `20261003_0006` (`20261003_0006_add_recommendations.py`) follows `20260929_0005`. Create only the recommendation table, constraints/FKs/indexes; downgrade removes only these. JSONB/partial-index SQLite variants support deterministic tests. No seed/history in migration or edits to previous revisions.

Test every stage/default boundary, fall-through, insufficient evidence, abandonment streak break, request/delivery distinction, independently corroborated promotion, deadline invalidation, late lower-ID commit/count, catalogue/config changes, immutable decisions/events/state, rollback, ownership, active gate, API empty/failure responses, atomic fresh consumption and idempotent start retry. Test partial uniqueness/FKs and PostgreSQL concurrency where practical; ordinary tests use isolated SQLite and zero live model/execution calls. Verify upgrade/downgrade/re-upgrade on disposable/local data and schema drift.

Dev catalogue seeding is explicit and separate from tests/migration. Minimum demo: learner plus two skills and four supported Problems (two Easy and one Medium for A, one Easy for B); no manufactured learner history. More difficulty coverage may be curated only if useful.

**DEFERRED:** retention modelling, AI recent-error targeting/projection, learner-goal modelling, multi-skill mastery, calibrated thresholds, contextual bandits/ML ranking, recommendation-quality claims/evaluation (Phase 9), UI (Phase 8), external practice, RAG/MCP and infrastructure expansion.
