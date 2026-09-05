# Repository Guidelines

## Project Structure & Module Organization

This repository contains the Python MVP for DEV Placement OS. Application code is in `app/`: HTTP routes live in `app/api/`, configuration in `app/config.py`, SQLAlchemy setup in `app/db/`, ORM entities in `app/models/`, and Pydantic contracts in `app/schemas/`. Alembic configuration and revision scripts are in `migrations/`. Keep tests in `tests/`, mirroring the component under test (for example, `tests/test_health.py`). The product and implementation PRDs are retained as `.docx` files in the repository root.

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

Tests use `pytest` and FastAPI's `TestClient`. Name files `test_<feature>.py` and tests `test_<expected_behavior>()`. Add a focused unit test for every new endpoint, migration-sensitive model, and validation rule. Do not make standard unit tests depend on a live database, network service, LLM, or Judge0 instance; isolate those behind interfaces and mock them.

## Database, Security & Configuration

Never commit `.env`, database passwords, API keys, or student code execution shortcuts. Copy `.env.example` to `.env` for local setup. Student code must only run through a future isolated execution provider—never `exec()` or `eval()` in the application process. Create a new Alembic revision for every schema change; do not edit an already-applied migration.

## Commit & Pull Request Guidelines

There is no commit history yet. Use concise imperative Conventional Commit-style messages, such as `feat: add problem retrieval endpoint` or `test: cover health response`. Keep each commit scoped. Pull requests should describe the behavioral change, list tests run, note migration/configuration changes, and include API response examples when routes change.

## Multi-Agent Development Workflow

The development process is organized into specialized subagent roles defined in `.agents/subagents/`:
- **Lead / Orchestrator**: Coordinates workflow stages and communicates with the user.
- **Researcher** (`.agents/subagents/researcher.md`): Read-only research into authoritative PRD documents (`DEV_Placement_OS_Updated_PRD_v0.2.docx`, `DEV_Placement_OS_Python_MVP_Implementation_PRD_v0.1.docx`) and technical docs.
- **Developer** (`.agents/subagents/developer.md`): Implements features, API routes, models, schemas, and migrations in `app/` and `migrations/`.
- **Tester** (`.agents/subagents/tester.md`): Authors tests in `tests/` and executes `pytest`. Never modifies application source code.
- **Reviewer** (`.agents/subagents/reviewer.md`): Strictly read-only code quality, security, and guideline compliance auditing.

The workflow protocol is detailed in `.agents/workflows/multi_agent_workflow.md`.

