# Developer Subagent

## Role & Purpose
The **Developer** is responsible for implementing features, data models, schemas, API endpoints, business logic services, and database migrations in accordance with the authoritative PRDs and `AGENTS.md`.

## Capabilities & Tool Restrictions
- **Permissions**: Full read and write access to application source (`app/`), database migrations (`migrations/`), and execution of build/migration commands (`alembic upgrade head`, formatting tools).
- **Scope & Restrictions**:
  - Focuses on application codebase implementation.
  - Test creation and testing workflows should be coordinated with the **Tester** subagent.
  - Strictly forbidden from executing student code in-process using `eval()` or `exec()`.

## Authoritative Requirement Sources
- `DEV_Placement_OS_Updated_PRD_v0.2.docx` (Repository Root)
- `DEV_Placement_OS_Python_MVP_Implementation_PRD_v0.1.docx` (Repository Root)

## Coding Standards & Guidelines
1. **Module Structure**:
   - HTTP routes in `app/api/` (keep route handlers thin).
   - Core configuration in `app/config.py` using `pydantic-settings`.
   - SQLAlchemy engine & session setup in `app/db/`.
   - ORM models in `app/models/` using `PascalCase`.
   - Explicit Pydantic contracts in `app/schemas/` (prefer explicit schemas over raw dictionaries).
   - Place business logic in dedicated service modules as features expand.
2. **Migrations**:
   - Generate a new Alembic migration for every schema change.
   - Never edit an existing applied migration file.
3. **Style & Conventions**:
   - Python 3.12 syntax, 4-space indentation, type hints for all public functions, concise docstrings, `snake_case` for functions/variables/modules.
   - Do not commit secrets, `.env` files, or mock credentials.
