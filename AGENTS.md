# Repository Guidelines

## Project Structure & Module Organization

This repository contains the Python MVP for DEV Placement OS. Application code is in `app/`: HTTP routes live in `app/api/`, configuration in `app/config.py`, SQLAlchemy setup in `app/db/`, ORM entities in `app/models/`, and Pydantic contracts in `app/schemas/`. Alembic configuration and revision scripts are in `migrations/`. Keep tests in `tests/`, mirroring the component under test (for example, `tests/test_health.py`). The product and implementation PRDs are retained as `.docx` files in the repository root.

## Authority and Current Phase

Use, in order: (1) Product PRD v0.3 (`DEV Placement OS.docx`) for long-term direction; (2) Python MVP Implementation PRD v0.1 for MVP scope and implementation order; (3) accepted architecture/research contracts in `docs/`; (4) implemented architecture; (5) agent-specific instructions. A research artifact can refine implementation details but cannot override an explicit PRD requirement without review. Report genuine PRD contradictions before implementation. Read `docs/PROJECT_STATUS.md` and `docs/plans/CURRENT_IMPLEMENTATION_PLAN.md` for the active scope.

Implementation Phases 1 (foundation), 2 (problem system), 3 (execution/evaluation), and 4A (Learning Evidence / Session Vault; implementation PRD Phase 4) are complete. Phase 4B (Learner Model / Knowledge Tracing; implementation PRD Phase 5) is in progress: single-skill BKT and SkillState persistence exist. Assisted observations and multi-skill attribution need separate accepted policies. Do not start tutor, adaptive recommendation, or UI work just because their interfaces appear in a PRD.

## Product and Evidence Boundaries

The product is **Learner Model + Evidence + Execution + Evaluation + Adaptive Decision Making + AI**, not a generic LLM chat UI. Preserve this flow: Problem → Attempt → Reasoning / learner actions → Submission → Execution → Deterministic Evaluation → Learning Event / Session Vault → Learner-State Update → Adaptive Decision → Next Activity.

Learner evidence is a core product asset. Keep **raw evidence → structured LearningEvent → derived labels → learner state → adaptive decision** as distinct layers; later interpretations must not overwrite earlier evidence. Session Vault / LearningEvent history persists. SkillState is a derived projection, not historical truth. Every derived observation and state update needs provenance sufficient for correction and replay. Deterministic evidence takes precedence over unsupported LLM claims. LLMs may diagnose, explain, or classify but must not directly calculate or mutate mastery. Keep knowledge tracing behind a replaceable interface (BKT is the initial MVP method), execution behind `ExecutionProvider`, and external integrations behind adapters. Keep providers, models, and technologies replaceable where practical.

## Build, Test, and Development Commands

Use Python 3.12 and the local virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
alembic upgrade head
```

`uvicorn` starts the FastAPI service; verify it at `GET /health`. `pytest` runs the automated checks. `alembic upgrade head` applies schema revisions using `DATABASE_URL` from `.env`. Use `alembic upgrade head --sql` for an offline migration preview.

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, type hints for public functions, concise docstrings for modules/classes/services, and `snake_case` for functions, variables, modules, and routes. Use `PascalCase` for ORM and Pydantic models. Keep route handlers thin; place business logic in a dedicated service module as the project expands. Prefer explicit Pydantic request/response schemas over raw dictionaries.

## Testing Guidelines

Tests use `pytest` and FastAPI's `TestClient`. Name files `test_<feature>.py` and tests `test_<expected_behavior>()`. Add a focused unit test for every new endpoint, migration-sensitive model, and validation rule. Standard unit tests must be deterministic and independent of a live database, network service, LLM, or Judge0 instance; use isolated provider mocks and dependency overrides.

## Database, Security & Configuration

Never commit `.env`, database passwords, API keys, or student code execution shortcuts. Copy `.env.example` to `.env` for local setup. Never use `exec()` or `eval()` for student submissions, execute learner code in the FastAPI process, or expose secrets, database credentials, or environment variables to learner code. Use the isolated `ExecutionProvider`; hidden tests and their inputs/expected outputs must never leak to learners. Create a new Alembic revision for every schema change; do not edit an already-applied migration.

## Commit & Pull Request Guidelines

Use concise imperative Conventional Commit-style messages, such as `feat: add problem retrieval endpoint` or `test: cover health response`. Keep each commit scoped. Pull requests should describe the behavioral change, list tests run, note migration/configuration changes, and include API response examples when routes change.

## Multi-Agent Development Workflow

The development process is organized into specialized subagent roles defined in `.agents/subagents/`:
- **Lead / Orchestrator**: Coordinates research → architecture/decision acceptance → implementation → testing → review, preserves phase boundaries, and communicates with the user.
- **Researcher** (`.agents/subagents/researcher.md`): Researches uncertain architecture/design questions; read-only unless explicitly asked to create research documents. Separates source evidence from architectural judgment.
- **Developer** (`.agents/subagents/developer.md`): Implements approved scope in `app/` and `migrations/`; does not silently redesign architecture and reports contradictions first.
- **Tester** (`.agents/subagents/tester.md`): Authors independent deterministic tests in `tests/` and executes `pytest`; never modifies application source code or requires a live provider for standard unit tests.
- **Reviewer** (`.agents/subagents/reviewer.md`): Strictly read-only architecture, security, scope, and test-quality auditing.

The workflow protocol is detailed in `.agents/workflows/multi_agent_workflow.md`.

Developer completion reports must list files changed, migration changes, architecture implemented, tests added, full `pytest` result, Alembic result, known limitations, unresolved decisions, and confirmation that work stayed within the approved phase/scope.
