# Multi-Agent Workflow Protocol

This document outlines the operational collaboration protocol between the **Lead Orchestrator** and the four specialized subagents.

## Agent Role Matrix

| Agent | Scope | Write Tooling | Command Execution | Target Output |
| :--- | :--- | :--- | :--- | :--- |
| **Lead / Orchestrator** | Coordination & User Communication | Allowed | Allowed | Orchestrated workflow & user status |
| **Researcher** | Technical exploration & PRD analysis | Research documents only on explicit request | **Disabled** | Analysis report, API specs & trade-offs |
| **Developer** | App source (`app/`, `migrations/`) | **Enabled** | **Enabled** (Alembic/tools) | Source code changes & new migrations |
| **Tester** | Tests (`tests/`) & test execution | **Tests Only** | **Enabled** (`pytest`) | Automated test cases & test run results |
| **Reviewer** | Quality & security auditing | **Disabled** | **Disabled** | Structured review report with verdict |

## End-to-End Execution Flow

After research, the Lead checks recommendations against both PRDs and accepted contracts, resolves or reports contradictions, and accepts the architecture/decision boundary before implementation. Agents must not make incompatible architecture decisions independently. Preserve the current Phase 4A evidence → Phase 4B learner-state sequence before tutor/adaptive/UI work.

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
- Authority order: Product PRD v0.3 (`DEV Placement OS.docx`) for long-term direction; Python MVP Implementation PRD v0.1 for MVP scope/order; accepted architecture/research contracts; implemented architecture; agent-specific instructions. Research may refine details but cannot override explicit PRD requirements without review.
- Subagents must never modify these PRD documents.
- The `Tester` must never edit files outside of `tests/`.
- The `Reviewer` must never perform write operations. The `Researcher` is read-only unless explicitly asked to create research documents.
- Student code execution shortcuts (`exec()`, `eval()`) are strictly prohibited across all subagents.
