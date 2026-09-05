# DEV Placement OS - Python MVP

Phase 1 foundation for the DEV Placement OS Python MVP.

## Prerequisites

- Python 3.12
- Docker Desktop (for PostgreSQL)

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/health` to confirm the service is running.

## Tests

```powershell
pytest
```

The application never executes student code. Sandboxed execution is introduced in Phase 3.

