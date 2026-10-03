"""Session-local drafts/operation identities; committed state always comes from HTTP."""

import hashlib
import json
from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4

from app.schemas.learning_event import LearningEventResponse, LearningEventType


def positive_id(value: object) -> int | None:
    try:
        result = int(str(value))
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def operation_key(state: MutableMapping[str, Any], action: str, payload: dict[str, Any]) -> str:
    """A retry keeps its identity; editing the payload starts a new explicit operation."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    operations = state.setdefault("operations", {})
    existing = operations.get(action)
    if existing is None or existing["digest"] != digest:
        operations[action] = {"digest": digest, "key": uuid4().hex}
    return operations[action]["key"]


def finish_operation(state: MutableMapping[str, Any], action: str) -> None:
    state.get("operations", {}).pop(action, None)


def latest_submission_id(events: list[LearningEventResponse]) -> int | None:
    evaluated = [event for event in events if event.event_type == LearningEventType.SUBMISSION_EVALUATED]
    return max(evaluated, key=lambda event: event.attempt_sequence).submission_id if evaluated else None


def latest_reasoning(events: list[LearningEventResponse]) -> LearningEventResponse | None:
    recorded = [event for event in events if event.event_type == LearningEventType.REASONING_RECORDED]
    return max(recorded, key=lambda event: event.attempt_sequence) if recorded else None
