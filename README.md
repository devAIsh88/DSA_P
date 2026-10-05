# DEV Placement OS — Python MVP

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

DEV Placement OS is an evidence-first DSA learning prototype for one learner. Phase 8 provides a Streamlit Home/Progress view and Problem Workspace over FastAPI. The learning loop connects reasoning, isolated Python execution, deterministic evaluation, persistent history, derived learner state and deterministic next activities.

## Architecture

```text
Streamlit → public FastAPI HTTP contracts → application services
                                            ├─ PostgreSQL
                                            ├─ isolated ExecutionProvider (Judge0)
                                            └─ replaceable TutorProvider (free Groq → local Ollama)

Problem → Attempt → reasoning/actions → Submission → execution/evaluation
        → LearningEvent → SkillState → Recommendation → next activity
```

- Backend services own lifecycle, correctness, events, mastery and recommendations. The frontend has no direct database or provider access.
- Attempts group multiple submissions and interventions. Historical LearningEvents are append-only through normal application behavior; SkillState is a replayable derived projection.
- Phase 4B v1 uses standard binary BKT for eligible independent, single-skill, unit-weight outcomes. Assistance contributes reporting, not mastery. Multi-skill mastery remains deferred.
- Five versioned deterministic recommendation actions select actual problems. Thresholds are uncalibrated MVP defaults; scheduled review does not prove forgetting, and abandonment is not failure evidence. Recommendation quality is not validated.
- Public schemas exclude hidden inputs/expected outputs, protected execution diagnostics, internal provenance and private recommendation snapshots.

The supplied PostgreSQL image includes pgvector. RAG, vector retrieval and embeddings-based recommendations are not implemented.

## Local setup

Use **Python 3.12**, Docker Desktop or local PostgreSQL 16 with the required extension support, and two terminals. This is a local, trusted, single-learner prototype without authentication; public production deployment is outside its current scope.

```powershell
git clone https://github.com/devAIsh88/DSA_P.git
cd DSA_P
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d db
python -m alembic upgrade head
```

Configure the local, untracked `.env` for the database and providers. Never commit it or print credentials. Preserve an existing `.env` when repeating setup.

### Explicit demo provisioning

```powershell
python -m scripts.provision_demo
```

The idempotent command creates or verifies **one learner, two skills and six curated problems across Easy/Medium/Hard**, with public samples, hidden grading cases and sole unit-weight skill mappings. It reuses the sole existing learner, refuses ambiguous ownership/conflicting rows, and permits loopback PostgreSQL only (SQLite is test-only).

Set `UI_LEARNER_ID` in `.env` to the ID printed by the command. Provisioning creates **no Attempts, Submissions, LearningEvents, SkillState or Recommendations** and never runs automatically at startup. Learner history arises from real usage.

### Start FastAPI

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health: `http://127.0.0.1:8000/health`. Interactive API documentation: `http://127.0.0.1:8000/docs`.

### Start Streamlit in a second activated terminal

```powershell
python -m streamlit run frontend/app.py --server.address 127.0.0.1
```

Open `http://127.0.0.1:8501`. The configured learner ID must match the backend before writes are enabled.

The existing repository environment uses `.\.venv\python312\python.exe`; substitute this executable for `python` when using it. A standard Windows virtual environment uses `.\.venv\Scripts\python.exe`.

### Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Backend connection; private local configuration |
| `APP_ENV` | Provisioning permits `development`, `test` or `demo` |
| `JUDGE0_BASE_URL` | Isolated execution service for real Run/Submit execution |
| `TUTOR_PROVIDER`, `TUTOR_MODEL` | Replaceable tutor adapter and configured model |
| `GOOGLE_API_KEY` | Backend Gemini credential; untracked environment only |
| `UI_API_BASE_URL` | FastAPI URL; default `http://127.0.0.1:8000` |
| `UI_LEARNER_ID` | Required provisioned learner ID |
| `UI_REQUEST_TIMEOUT_SECONDS` | Bounded UI HTTP wait; default 90 seconds |

See `.env.example` for timeout, retry and resource settings. Tutor credentials are not frontend configuration. An unavailable execution provider returns an infrastructure failure; learner Python is never executed in FastAPI or Streamlit.

## Learning workflow

Home/Progress presents catalogue browsing, active-Attempt recovery, activity/skill reporting and backend recommendations. Opening a problem only displays it; start an Attempt explicitly.

1. Draft Python and optional reasoning. Explicit reasoning saves append evidence.
2. **Run** checks public sample tests through isolated execution. It creates no Submission, LearningEvent, mastery update or recommendation invalidation.
3. **Submit** performs authoritative grading, including hidden tests, and persists results/evidence. HTTP success does not mean code acceptance.
4. Review the deterministic verdict separately from optional AI interpretation; correct and resubmit within the Attempt.
5. Complete as `SOLVED` only when the latest persisted Submission is accepted. `GAVE_UP` and `ABANDONED` are distinct. Closed Attempts cannot reopen; retries create new Attempts.
6. Reload progress and request the next backend-selected activity. A fresh matching Attempt start consumes its recommendation transactionally.

The UI labels **estimated mastery**, not certainty. Hint requests, delivered levels and supported-skill solve shares retain their exact reporting denominators; global activity counts remain separate. Unsupported placement-readiness, retention-loss and calibrated-confidence metrics are not shown.

### Tutor flows and degradation

#### Zero-cost provider setup

Install [Ollama](https://ollama.com/download) explicitly. Quit any existing
Ollama daemon, then in a separate PowerShell terminal:

```powershell
$env:OLLAMA_NO_CLOUD='1'
ollama serve
```

With that local daemon running, use another terminal to install the model:

```powershell
ollama pull qwen2.5-coder:3b
```

The pull is a manual local-model download; the application never downloads
models. If the desktop app manages the daemon, set `OLLAMA_NO_CLOUD=1` in its
environment and restart it instead of starting a second daemon.

Update your existing untracked `.env` locally (preserve database settings):

```dotenv
ZERO_COST_MODE=true
TUTOR_PROVIDER=zero_cost
GROQ_API_KEY=
GROQ_MODEL=
GROQ_FREE_TIER_CONFIRMED=false
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:3b
GROQ_TIMEOUT_SECONDS=8
OLLAMA_TIMEOUT_SECONDS=60
```

For optional Groq use, add the key **only locally**, select a currently free
text model, and set confirmation true only after verifying that the account
and model need no billing, card, credits or paid tier. Never enable billing to
resolve a limit. No key/model/confirmation means local-only operation.
Free-tier limits are account-specific; a key alone is not proof of free use.
See [Groq billing](https://console.groq.com/docs/billing-faqs) and
[limits](https://console.groq.com/docs/rate-limits).

Start FastAPI and Streamlit using the commands above. Groq success returns its
validated response; rate limits, timeout, connection/provider errors or invalid
output switch to local Ollama. There is one Groq call per operation, not a
rate-limit retry loop. Both failures retain existing safe unavailable/static
hint behavior; Run, Submit, lifecycle, progress and recommendations continue.

Zero-cost mode defaults on and refuses known paid/unknown provider selection,
including the legacy Gemini adapter and live Gemini benchmark path. An older
`.env` selecting Gemini must be changed before startup. Do not disable this
guard for the zero-spend deployment. The software prevents configured paid
fallbacks; external account/pricing policies cannot be guaranteed by software.
Ollama must use trusted local GGUF weights and a cloud-disabled daemon:
[official local-only setup](https://docs.ollama.com/faq).
No live provider quality or model selection is claimed. Details:
[zero-cost contract](docs/architecture/ZERO_COST_TUTOR_CONTRACT.md).

Six targeted interactions cover hint requests, diagnosis, reasoning analysis, post-attempt explanation, understanding questions and answer evaluation. There is no generic chatbot. Tutor feedback never determines code correctness or mutates mastery.

Hint gating remains backend-controlled, including Level 6 full explanation/solution when allowed. Requests and deliveries are separate historical events. Model failure may produce a safe static hint fallback; unavailable diagnosis/analysis/explanation is displayed without fake feedback.

Understanding questions are deterministic. Learner answers are saved before optional AI evaluation. On evaluation failure the UI shows **“Answer saved; AI evaluation unavailable.”** and does not automatically resend the answer.

Live Gemini verification remains externally blocked: `gemini-3.8-flash` returned `503 UNAVAILABLE` and `gemini-3.7-flash` returned `504 DEADLINE_EXCEEDED`. Connectivity reached the Gemini HTTP service, but successful live structured output and model quality have not been verified. Core execution, lifecycle, evidence, learner-state and recommendation flows remain usable without Gemini.

### Refresh and recovery

The URL holds safe problem/Attempt IDs only. Reload reads the Attempt, ordered events and latest owned Submission to restore persisted reasoning, source, results and delivered feedback. Unsaved drafts and operation keys are session-local and may be lost on full refresh.

POSTs are never retried automatically. After an unknown response, inspect saved server state; explicit same-session retries retain their operation identity. Recovered events do not invent unavailable AI labels. A saved understanding answer is not resent after session loss.

## Public API surface

| Area | Endpoints |
|---|---|
| Health/problems | `GET /health`, `GET /problems`, `GET /problems/{problem_id}` |
| Attempts | `POST /attempts/start`, `GET /attempts/{attempt_id}`, `GET /attempts/{attempt_id}/events` |
| Learner actions | `POST /attempts/{attempt_id}/reasoning`, `POST /attempts/{attempt_id}/complete`, `POST /attempts/{attempt_id}/abandon` |
| Execution | `POST /runs`, `POST /submissions`, `GET /submissions/{submission_id}` |
| Hints | `POST /hints/request` |
| Tutor interpretation | `POST /attempts/{attempt_id}/diagnose`, `POST /attempts/{attempt_id}/reasoning-analysis`, `POST /attempts/{attempt_id}/post-explanation` |
| Understanding | `POST /attempts/{attempt_id}/understanding-checks`, `POST /attempts/{attempt_id}/understanding-checks/{check_event_id}/answer` |
| Learner reporting | `GET /learner/state`, `GET /learner/skills`, `GET /learner/skills/{skill_id}`, `GET /dashboard/summary` |
| Next activity | `GET /recommendations/next` |

Submission recovery requires ownership through a linked Attempt; unlinked historical submissions are refused because ownership is unavailable. Dashboard reads expose an existing recommendation snapshot only; `/recommendations/next` owns freshness and issuance.

## Verification

```powershell
python -m pytest
python -m alembic current
python -m alembic check
```

Current offline result: **462 passed, 1 opt-in test skipped** (2026-10-05). Normal pytest uses isolated databases, fake execution, MockTutorProvider and Streamlit AppTest, with no live Gemini/Judge0 calls. Acceptance coverage includes the primary loop, assistance reporting without mastery changes, provider failures, recovery and privacy.

Alembic is **`20261003_0007`** with no schema drift; Phase 9 adds only evaluation history. Phase 8 added no migration. Local provisioning passed twice, with zero new rows on the second run. Disposable localhost HTTP smoke verification using fake providers passed. Manual browser visual verification remains recommended; no visual pass is claimed.

## Phase 9 offline tutor evaluation

The offline foundation is complete; **no production tutor model has been selected**. The same Git-versioned 25-case suite covers hints (all six levels), diagnosis, reasoning, explanation and understanding evaluation. Benchmark inputs are authored standalone fixtures, not production learner history or hidden tests. Understanding-question generation remains deterministic application behavior.

### Offline run and planning

```powershell
python -m scripts.run_tutor_benchmark run --dry-run
python -m scripts.run_tutor_benchmark run --suite benchmarks/tutor/v1/suite.json --suite-version v1 --candidate synthetic-good --candidate synthetic-bad
```

Dry-run validates and prints a plan without constructing providers or opening a database. The normal run defaults to the two deterministic **synthetic harness candidates** and persists only evaluation tables in a guarded local/dev database. It does not need a model API key, execute learner code or modify learner events/state/recommendations. Synthetic oracle/contrast outputs are not real-model claims or human quality evidence.

Optional `--case CASE_ID` selects one case. `--resume-run RUN_UUID` requires one named candidate and the exact original suite/selection/controls/pricing/Git checkpoint, then skips committed results. Changed code or definitions require a new run; concurrent dispatch of the same unfinished run is unsupported. Never rewrite a published commit to resume it.

### Comparison and human review

```powershell
python -m scripts.run_tutor_benchmark compare --group-id GROUP_UUID
python -m scripts.run_tutor_benchmark export --group-id GROUP_UUID --output C:\Temp\tutor-review.json
python -m scripts.run_tutor_benchmark review --input C:\Temp\one-review.json
```

Use an existing writable directory and a new export filename. Export includes the versioned rubric, authored case inputs/criteria, validated outputs and per-result review templates. Copy one template into a review JSON file: use a pseudonymous `reviewer_label`, score every applicable dimension **0-4**, and keep non-applicable dimensions `null`. Append through `review`; later ratings from the same reviewer affect reporting without rewriting prior reviews. This is local human review, not authenticated reviewer identity or LLM grading.

Comparison reports task/dimension counts and coverage, schema reliability, gold-label/literal indicators, human ratings, failures, median latency and p95 only for at least 20 observations. Subjective scores start `UNREVIEWED`; missing values are not zero-filled. Literal checks do not prove safety or technical correctness. There is no composite score or automatic winner. Hint dependency, learner-state quality, recommendation quality, retention and personalization gain need separate learner/system experiments.

### Accounting and future live execution

Optional `--pricing FILE.json` accepts a bounded JSON list of PricingSnapshot records: version, effective_at, provider, model_id, accounting_basis, input/output USD rates per million tokens and synthetic flag. Rates are explicit snapshots, not bundled market prices. Cost requires compatible reported input/output usage; missing or incomplete retry accounting leaves cost unavailable. Mixed token bases are not summed. The current Gemini adapter has no usage hook, so its benchmark cost may remain unknown.

Future live execution requires separate candidate/budget authorization and all CLI gates. Only the Gemini adapter is registered today; other providers need equivalent prompt/schema/transport controls before registration. Example **for a later authorized run only**, substituting explicit candidate IDs:

```powershell
python -m scripts.run_tutor_benchmark run --live --candidate gemini:MODEL_A --candidate gemini:MODEL_B --suite benchmarks/tutor/v1/suite.json --suite-version v1 --max-calls 50 --timeout-seconds 30 --acknowledge-live-cost
```

The runner requires a clean identifiable Git checkpoint. The maximum-call budget includes configured retries; SDK retries are disabled for evaluation. A warning precedes live invocation; cost acknowledgment does not select a model. Adding `--dry-run` to a fully gated live command plans without opening the database or reading provider credentials. No external candidates are constructed without `--live`. No live commands were executed during offline implementation.

A production choice remains a human decision after at least two real comparable complete runs, applicable human reviews, reliability/latency evidence and consideration of safety failures and available/explicitly unknown cost. Existing Gemini availability remains externally blocked. No production model/configuration is changed by the evaluator.

## Repository layout and next work

```text
app/          FastAPI routes, schemas, services, providers and ORM entities
frontend/     Streamlit views/sections, typed HTTP client and session state
scripts/      Explicit demo provisioning and evaluation CLI
benchmarks/   Versioned tutor cases and human rubric
config/       Versioned learner-model and recommendation configuration
migrations/   Alembic revisions
tests/        Offline backend, UI and acceptance tests
docs/         Architecture, active plan, status and development log
```

Read `AGENTS.md`, `docs/PROJECT_STATUS.md`, `docs/plans/CURRENT_IMPLEMENTATION_PLAN.md` and `docs/architecture/PHASE8_UI_CONTRACT.md` before further work. Phase 9 offline evaluation is complete under `docs/architecture/PHASE9_EVALUATION_CONTRACT.md`; real multi-model runs, human review and production selection remain pending candidate/budget acceptance. No later-phase implementation is authorized.

Deferred: multi-skill mastery, retention/error projections, recommendation-quality evaluation, custom-input execution, RAG, fine-tuning, production authentication and deployment. Adaptive-policy optimality and successful live-model validation are not claimed.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
