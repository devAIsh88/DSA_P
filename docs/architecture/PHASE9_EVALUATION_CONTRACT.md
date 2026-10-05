# Phase 9 Evaluation Foundation Contract

**FROZEN — 2026-10-03.** Product PRD sections 22–23 and Implementation PRD sections 23–24/33 require internal, comparable evaluation and stored results. This checkpoint implements the offline foundation; real multi-model experiments and production selection remain pending explicit candidate/budget authorization. No live model calls are authorized in this run.

## Scope and authority

- Benchmark all five TutorProvider capabilities: hint, diagnosis, reasoning analysis, post-attempt explanation and understanding evaluation. Deterministic understanding-question generation remains an application regression test, not an LLM task.
- Keep code correctness, BKT, SkillState, recommendations and LearningEvents unchanged. The evaluator uses synthetic standalone context, never production learner history, database entities or hidden tests. It never executes learner code.
- Technical quality, diagnosis, hint usefulness, personalization and response-policy compliance require explicit gold criteria and human review. Hint dependency, mastery-estimation/update quality, recommendation quality, retention and personalization gain require learner/system experiments; tutor output checks cannot establish these outcomes. Existing regression tests protect those boundaries; empirical outcome measurement remains pending.
- No training, LLM judge calls, adaptive-policy changes, new learner/UI APIs or later-phase work.

## Readiness

Available: replaceable TutorProvider, five typed tasks/results, deterministic mock, safe context, model/provider/prompt/schema identifiers, bounded Gemini adapter and isolated fixtures. Missing: benchmark identity, curated gold criteria/rubrics, grouped runs, evaluation persistence, accounting/comparison and review workflow. Existing Gemini provenance does not report token usage; missing counters/cost must remain unavailable. Latency is measured at the evaluator boundary, not inferred from event timestamps.

## Definitions and versioning

- Store `benchmarks/tutor/v1/suite.json` and `rubric.json` in Git. Initial suite is compact (25 cases): six hint levels, nine diagnoses, four reasoning cases, two explanations and four understanding answers. Include correct, partial, incomplete, edge, misread, wrong-pattern, implementation, logical, complexity and conceptual cases where meaningful.
- `BenchmarkSuite`: suite_id, version, rubric_version, cases. `BenchmarkCase`: case_id, version, task_type, difficulty, tags, typed request, expected_labels, required_content, forbidden_content, review guidance. Context permits only the existing TutorContext fields; requests permit only the relevant existing task fields. Reject unknown keys recursively, unsafe secrets and oversize fixtures. No test bodies/outputs, ORM identifiers or gold criteria enter provider requests.
- Gold labels are authored, reviewable expectations (including null for a correct diagnosis), not provider truth. Exact label match is distinct from technical correctness. Literal required/forbidden checks are limited indicators: absence of a match does not prove safety or prevent all premature solutions.
- Canonical JSON SHA-256 hashes bind suite, selected cases, rubric, each request and output schemas. A content change requires a new definition version; hashes detect accidental same-version drift. Record Git revision, runner version, prompt version map and tutor schema version. Historical reconstruction uses the recorded Git revision and hashes.
- `EvaluationCandidate`: candidate_id, provider, model_id, synthetic flag. Credentials and arbitrary provider configuration are excluded. Candidates never receive another candidate's output or gold criteria.

## Invocation and fairness

- A provider-neutral async runner dispatches through TutorProvider with the same immutable task input for each candidate. Deep-copy requests to prevent provider mutation. Validate results against the existing result schema and verify provider/model/prompt/schema identity. No fallback hints are substituted in candidate benchmarks.
- Shared versioned execution policy: timeout_seconds, max_retries, max_input_chars, max_output_tokens, temperature. Configurable initial defaults: 30 seconds, zero retries, 30,000 input characters, 2,048 output tokens, temperature 0. These are experiment controls, not product truths.
- Measure total monotonic wall latency including all runner retries; persist attempt_count and safe final error code. Timeouts, provider failures, invalid schemas, unsafe outputs and identity mismatch are explicit outcomes. Never persist raw exceptions/tracebacks or unvalidated provider objects. No automatic repeated suite execution.
- Future live Gemini construction occurs only in the adapter factory after CLI safety checks. An optional Gemini constructor setting disables SDK retries for evaluation and applies the shared temperature; normal tutor defaults remain unchanged. Generic evaluation code contains no vendor types. New live adapters require the same task/prompt contract and explicit transport/accounting behavior before registration.
- Optional provider accounting may supply validated input/output token counters, an accounting version and its scope. Retried invocations retain counters only when the adapter explicitly reports all attempts with the matching attempt count; a last-response counter cannot stand in for total usage. No estimation from characters. If accounting is absent/invalid, counters and cost are null. Current uninstrumented Gemini runs may therefore have unknown cost; never fabricate usage.
- Comparable runs require the same suite/selected-case hashes, rubric, schema/prompt contracts, runner/Git revision and execution controls. Provider/model identities differ; pricing snapshots may differ. Synthetic and real results are never pooled into a model claim.

## Persistence and transactions

Add exactly three evaluation-only tables in migration `20261003_0007`, following `20261003_0006`; no learner-table changes or learner foreign keys:

- `EvaluationRun`: UUID id and group_id; suite id/version/digest; selected case IDs/digest and an identity-only case manifest (case/task/request hashes); candidate id/provider/model; synthetic flag; runner/Git/prompt/schema/rubric versions; protocol fingerprint and safe execution/pricing snapshots; RUNNING/COMPLETED status; created_at/completed_at. Unique(group_id, candidate_id) prevents ambiguous duplicate candidate runs in one comparison group.
- `EvaluationResult`: id, run_id FK, unique(run_id, case_id), case/request digest and task, outcome, validated structured output or null, automatic metrics, latency_ms, attempt_count, nullable input/output tokens and accounting version, safe error_code, created_at. No duplicated benchmark input bodies.
- `EvaluationReview`: id, result_id FK, pseudonymous reviewer_label, rubric_version, applicable scores (0–4 or explicit not-applicable null), bounded notes, reviewed_at. Human review is append-only; later submissions supersede that reviewer's prior rating for reporting, never rewrite history.

Committed run configuration, results and reviews are immutable through normal ORM/service behavior. Only RUNNING → COMPLETED lifecycle may change; direct privileged SQL is outside MVP protections. Each case result is committed atomically. An interrupted run retains committed results; explicit resume validates the complete plan and skips existing case identities. Do not return a result that failed to persist. Unique constraints protect duplicate recording; concurrent dispatch of the same unfinished run is unsupported (do not promise exactly-once remote calls).

## Automatic metrics, rubric and review

Automatic metrics: structured_output_valid, expected-label checks, required/forbidden literal matches, identity validity, attempt/error counts and measured latency. Return counts/denominators, not one invented quality score. A schema failure can be observed at the runner; an adapter that reports only generic TutorProviderError remains PROVIDER_ERROR, not guessed malformed JSON.

`tutor-rubric-v1` defines 0–4 anchored ratings: technical correctness, response-policy compliance, personalization relevance, and task-specific diagnosis accuracy, hint usefulness/minimum intervention/solution leakage, reasoning feedback, explanation or understanding assessment. Applicable dimensions are required; not-applicable is explicit and not treated as zero. All subjective dimensions begin UNREVIEWED. Reviewers inspect case inputs/criteria and candidate output offline, then import a bounded JSON record through CLI. Store rubric/reviewer/time; do not imply authenticated reviewer identity or calibrated inter-rater agreement.

LLM-as-judge is not necessary for this foundation. [MT-Bench research](https://arxiv.org/abs/2306.05685) identifies position, verbosity and self-enhancement biases; the accepted architectural judgment is gold criteria plus explicit human review first. An eventual replaceable judge must be identified, versioned, non-authoritative and different from the candidate; no judge implementation or self-grading now. Synthetic oracle candidates may use gold criteria only as clearly identified harness fixtures, never as real-model evidence.

## Cost and comparison

- Pricing is an optional separate versioned/effective-dated provider/model snapshot in USD, with nonnegative Decimal input/output rates per million reported tokens and a named compatible accounting basis. No bundled current market prices. Only complete compatible token accounting permits derived cost; partial/unavailable usage remains unknown. Synthetic pricing is explicitly synthetic.
- Compare per candidate and task: attempted/expected cases, completion and schema reliability, gold-label denominators, literal-policy indicators, human review coverage/scores, median latency, errors, token coverage and derived cost coverage. Report p95 only with at least 20 observations and label the quantile method/sample count. Missing quality/cost values remain null with coverage; never zero-fill them or mix unlike suites/protocols.
- No composite score, automatic winner or production-config update. A selection-readiness mechanism requires at least two distinct real candidates with complete comparable runs, all applicable human reviews, measured reliability/latency and no blocking automatic failures. Unknown cost requires explicit acknowledgment before future selection. Passing readiness is not evidence that the policy/model is optimal; human judgment is still required.

## CLI and live gates

Provide `python -m scripts.run_tutor_benchmark` with run, compare, export and review commands. Run supports explicit suite, named candidates, optional one-case selection, dry-run, offline synthetic mode, group identity and explicit resume. Without live opt-in, external candidates are rejected before constructing adapters or reading credentials. Dry-run validates/prints a safe plan without providers or database writes. Offline runs use two distinct deterministic synthetic candidates and never construct Gemini.

Future live execution requires **all** of: `--live`, explicit candidate provider/model(s), explicit suite/version, bounded `--max-calls`, explicit timeout, and `--acknowledge-live-cost`. Validate the worst-case case-count × candidate-count × (1+retries) budget before any invocation; SDK retries are disabled in the registered live adapter. Warn that cost is unknown when pricing/accounting is missing. Only after all gates may environment credentials be read. No interactive loop or automatic model selection. Tests never invoke live mode.

Database configuration is separate from provider configuration; offline/dry-run must not load tutor settings or require an API key. Exports contain only synthetic benchmark inputs/references and sanitized evaluation outputs/reviews, never production learner data. Export/import filenames are explicit and no generated reports are committed. No new dependencies are required.

## Verification and closeout

Test suite identity/strict safety/versioning, all five methods, malformed responses, timeout/retry symmetry, prompt/model identity, provider request isolation, metric denominators, absent accounting, Decimal cost, schema persistence/FKs/uniqueness/immutability, interrupted-run resume, rollback, rubric review and comparison incompatibility. Prove evaluator writes do not change learner tables and offline/dry-run never build external adapters. Full normal pytest stays offline.

Apply migration and check head/drift; verify downgrade/re-upgrade in a disposable database/schema only. Run two synthetic candidates, persist/review/compare/export with clearly synthetic labels. Record exact tests and checkpoints. Foundation completion is not completion of the PRD's real-model comparison/selection or longitudinal learner-quality validation. Existing Gemini external blocker remains unresolved until a separately authorized successful live run.
