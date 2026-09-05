# Multi-Agent Workflow Protocol

This document outlines the operational collaboration protocol between the **Lead Orchestrator** and the four specialized subagents.

## Agent Role Matrix

| Agent | Scope | Write Tooling | Command Execution | Target Output |
| :--- | :--- | :--- | :--- | :--- |
| **Lead / Orchestrator** | Coordination & User Communication | Allowed | Allowed | Orchestrated workflow & user status |
| **Researcher** | Technical exploration & PRD analysis | **Disabled** | **Disabled** | Analysis report, API specs & trade-offs |
| **Developer** | App source (`app/`, `migrations/`) | **Enabled** | **Enabled** (Alembic/tools) | Source code changes & new migrations |
| **Tester** | Tests (`tests/`) & test execution | **Tests Only** | **Enabled** (`pytest`) | Automated test cases & test run results |
| **Reviewer** | Quality & security auditing | **Disabled** | **Disabled** | Structured review report with verdict |

## End-to-End Execution Flow

```
[User Prompt]
      │
      ▼
[Lead Orchestrator]
      │
      ├───────────────────────┐
      │ (If research needed)  │
      ▼                       │
 [Researcher]                 │
      │                       │
      ▼                       ▼
 [Lead Orchestrator] ──► [Developer]
                              │
                              ▼
                         [Lead Orchestrator] ──► [Tester]
                                                      │
                                                      ▼
                         [Lead Orchestrator] ◄────────┘
                              │
                              ▼
                         [Reviewer]
                              │
                              ├─► [Changes Requested] ──► [Developer]
                              │
                              └─► [Approved]
                                       │
                                       ▼
                              [Lead Orchestrator]
                                       │
                                       ▼
                                 [User Report]
```

## Guardrails
- The authoritative requirements live strictly in `DEV_Placement_OS_Updated_PRD_v0.2.docx` and `DEV_Placement_OS_Python_MVP_Implementation_PRD_v0.1.docx`.
- Subagents must never modify these PRD documents.
- The `Tester` must never edit files outside of `tests/`.
- The `Reviewer` and `Researcher` must never perform write operations.
- Student code execution shortcuts (`exec()`, `eval()`) are strictly prohibited across all subagents.
