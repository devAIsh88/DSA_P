# DEV Placement OS - Backend MVP

**High-Performance DSA Practice, Evaluation & Placement Operating System**

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688.svg)](https://fastapi.tiangolo.com)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-red.svg)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

**DEV Placement OS** is a specialized backend engine designed for developer placement preparation, algorithmic problem solving, automated submission evaluation, and skill analytics. Built with **FastAPI**, **SQLAlchemy 2.0**, and **PostgreSQL with pgvector**, the system provides a clean, modular foundation for managing coding challenges, running sandboxed evaluations (via Judge0 integration), and securely storing test results.

---

## Architecture & Features

```
                                  +-------------------+
                                  |   Client Request  |
                                  +---------+---------+
                                            |
                                            v
                                  +-------------------+
                                  |   FastAPI Router  |
                                  |    (app/api/*)    |
                                  +---------+---------+
                                            |
                         +------------------+------------------+
                         |                                     |
                         v                                     v
             +-----------------------+             +-----------------------+
             |    Problem Service    |             |  Submission Service   |
             | (app/services/problem)|             |  (app/services/sub.)  |
             +-----------+-----------+             +-----------+-----------+
                         |                                     |
                         v                                     v
             +-----------------------+             +-----------------------+
             |   SQLAlchemy 2 ORM    |             |  Execution Provider   |
             |     (PostgreSQL)      |             |  (Judge0 Isolated)    |
             +-----------+-----------+             +-----------+-----------+
                         |                                     |
                         +------------------+------------------+
                                            |
                                            v
                                  +-------------------+
                                  | Evaluation Engine |
                                  |  (Status & Score) |
                                  +-------------------+
```

- **Problem Catalog & Hidden Cases:** Exposes public problem metadata and sample test cases to users while securely isolating hidden evaluation test cases.
- **Isolated Code Execution:** Integrates an abstract execution provider interface with a concrete Judge0 implementation, strictly separating user-submitted code from backend host resources.
- **Automated Evaluation Pipeline:** Evaluates status codes (Accepted, Wrong Answer, Time Limit Exceeded, Memory Limit Exceeded, Runtime Error) and aggregates memory/runtime statistics.
- **Learning Evidence:** Groups reasoning and multiple submissions in an Attempt, then records ordered, append-only LearningEvents with learner-safe views.
- **Initial Learner Model:** Replays eligible single-skill Attempt completions through a replaceable BKT provider into persisted SkillState. Experimental parameters are versioned in `config/learner_model.json`.
- **Relational & Vector Data Storage:** Built on PostgreSQL 16 with `pgvector` for upcoming semantic question retrieval and embeddings-based skill recommendations.
- **Alembic Database Migrations:** Version-controlled database revisions for seamless schema evolution.

Phase 4B is in progress. Skill mappings must be curated; only one unit-weight skill mapping currently produces mastery evidence. Assisted Attempts and multi-skill attribution await explicit policies. No public mapping-write or administrative replay endpoint is available.

---

## Project Structure

```
DSA_P/
├── app/
│   ├── api/                 # API route controllers
│   │   ├── attempts.py      # Attempt lifecycle and evidence retrieval
│   │   ├── health.py        # Service health checks
│   │   ├── learner.py       # Read-only skill state
│   │   ├── problems.py      # Problem catalog endpoints
│   │   └── submissions.py   # Code submission & evaluation endpoints
│   ├── db/                  # Database connectivity and session lifecycle
│   │   ├── base.py          # Declarative Base
│   │   └── session.py       # Engine and sessionmaker
│   ├── models/              # SQLAlchemy 2.0 ORM entities
│   │   ├── attempt.py       # Learner engagement
│   │   ├── learning_event.py # Historical evidence
│   │   ├── problem.py       # Problems & difficulty definitions
│   │   ├── problem_skill.py # Curated problem-to-skill mapping
│   │   ├── skill.py         # Skill taxonomy
│   │   ├── skill_state.py   # Derived learner state
│   │   ├── submission.py    # User code submissions
│   │   ├── test_case.py     # Public & private test cases
│   │   ├── test_result.py   # Per-case evaluation outputs
│   │   └── user.py          # Single-learner record
│   ├── schemas/             # Pydantic v2 validation contracts
│   │   ├── attempt.py       # Attempt requests and responses
│   │   ├── execution.py     # Judge0 execution schemas
│   │   ├── health.py        # Health response schema
│   │   ├── learning_event.py # Learner-safe evidence responses
│   │   ├── problem.py       # Problem request/response models
│   │   ├── skill_state.py   # Learner-safe state responses
│   │   └── submission.py    # Submission payloads & results
│   ├── services/            # Core business & evaluation logic
│   │   ├── attempt_service.py # Attempt lifecycle
│   │   ├── bkt_provider.py  # Pure BKT implementation
│   │   ├── evaluation_service.py # Verdict resolution & scoring
│   │   ├── execution_service.py  # Sandboxed execution interface
│   │   ├── knowledge_tracing.py # Replaceable tracing contract
│   │   ├── learner_state_service.py # Evidence replay and projection
│   │   ├── learning_event_service.py # Event append and safe serialization
│   │   ├── problem_service.py    # Problem queries & retrieval
│   │   └── submission_service.py # Submission lifecycle management
│   ├── config.py            # Pydantic Settings configuration
│   └── main.py              # Application entrypoint & middleware
├── compose.yaml             # Docker Compose for PostgreSQL + pgvector
├── config/                  # Versioned experimental learner-model parameters
├── docs/                    # Status, plan, architecture, and development log
├── migrations/              # Alembic migration scripts
├── tests/                   # Pytest test suite with TestClient
├── pyproject.toml           # Project metadata
├── requirements.txt         # Pinned production & test dependencies
├── LICENSE                  # MIT License
└── README.md
```

---

## Getting Started

### Prerequisites
- **Python 3.12+**
- **Docker Desktop** (or a running PostgreSQL 16+ instance with `pgvector`)

### Installation & Local Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/devAIsh88/DSA_P.git
   cd DSA_P
   ```

2. **Set up a virtual environment:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   ```powershell
   Copy-Item .env.example .env
   ```

4. **Start Database Services:**
   ```powershell
   docker compose up -d db
   ```

5. **Run Migrations:**
   ```powershell
   alembic upgrade head
   ```

6. **Start the API Server:**
   ```powershell
   uvicorn app.main:app --reload
   ```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health status check |
| `GET` | `/problems` | List available coding problems |
| `GET` | `/problems/{problem_id}` | Retrieve problem details & public sample cases |
| `POST` | `/submissions` | Submit solution for execution & evaluation |
| `POST` | `/attempts/start` | Start a learner engagement |
| `POST` | `/attempts/{attempt_id}/reasoning` | Record reasoning as event evidence |
| `GET` | `/attempts/{attempt_id}` | Read Attempt metadata |
| `POST` | `/attempts/{attempt_id}/complete` | Close with an outcome |
| `POST` | `/attempts/{attempt_id}/abandon` | Abandon an Attempt |
| `GET` | `/attempts/{attempt_id}/events` | Read allowlisted historical evidence |
| `GET` | `/learner/skills` | List derived skill states |
| `GET` | `/learner/skills/{skill_id}` | Read one derived skill state |

Interactive documentation is available at `http://127.0.0.1:8000/docs` (Swagger UI) and `http://127.0.0.1:8000/redoc`.

---

## Running Tests

Execute the automated test suite with `pytest`:

```powershell
pytest
```

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
