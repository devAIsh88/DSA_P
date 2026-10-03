"""Typed HTTP-only client. POSTs are never retried automatically."""

from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.schemas.attempt import (
    AttemptAbandon, AttemptComplete, AttemptResponse, AttemptStart, ReasoningCreate,
)
from app.schemas.dashboard import DashboardSummaryResponse, LearnerStateResponse
from app.schemas.learning_event import LearningEventResponse
from app.schemas.problem import ProblemDetailResponse, ProblemListItemResponse
from app.schemas.recommendation import NextRecommendationResponse
from app.schemas.run import RunCreate, RunResponse
from app.schemas.submission import SubmissionCreate, SubmissionReadResponse, SubmissionResultResponse
from app.schemas.tutor import (
    DiagnoseRequest, DiagnoseResponse, HintRequest, HintResponse, PostExplanationRequest,
    PostExplanationResponse, ReasoningAnalysisRequest, ReasoningAnalysisResponse,
    UnderstandingAnswerRequest, UnderstandingAnswerResponse, UnderstandingCheckRequest,
    UnderstandingCheckResponse,
)


class APIError(Exception):
    """Public failure information; raw bodies/provider diagnostics are never retained."""

    def __init__(self, message: str, status: int | None = None, code: str | None = None,
                 attempt_ids: tuple[int, ...] = ()):
        super().__init__(message)
        self.status = status
        self.code = code
        self.attempt_ids = attempt_ids


_PUBLIC_CODES = {
    "ACTIVE_ATTEMPT_EXISTS": "Resume an active Attempt before requesting another activity.",
    "LEARNER_STATE_NOT_READY": "Learner state is not ready for a recommendation yet.",
    "RECOMMENDATION_UNAVAILABLE": "Recommendations are temporarily unavailable.",
    "NO_PUBLIC_SAMPLE_TESTS": "This problem has no public sample tests to Run.",
}


class APIClient:
    def __init__(self, base_url: str, timeout: float = 90, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url
        self.timeout = timeout
        self.transport = transport

    def _request(self, method: str, path: str, response_type: Any, payload: BaseModel | None = None) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                response = client.request(method, path, json=payload.model_dump(mode="json") if payload else None)
        except (httpx.RequestError, httpx.InvalidURL) as error:
            raise APIError("The server response was not received. Check saved state before retrying.",
                           code="NETWORK_UNAVAILABLE") from error
        if response.is_error:
            code = None
            attempt_ids: tuple[int, ...] = ()
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict) and isinstance(detail.get("code"), str) and detail["code"] in _PUBLIC_CODES:
                    code = detail["code"]
                    ids = detail.get("attempt_ids", [])
                    if isinstance(ids, list):
                        attempt_ids = tuple(i for i in ids if type(i) is int and i > 0)
            except (ValueError, AttributeError):
                pass
            message = _PUBLIC_CODES.get(code) if code else None
            if message is None:
                message = {404: "The learner or requested resource was not found.",
                           409: "The operation conflicts with saved state or the current Attempt rules.",
                           422: "Check the request fields and try again.",
                           503: "This service is temporarily unavailable. Saved learner evidence is preserved."}.get(
                               response.status_code, "The server could not complete this request.")
            raise APIError(message, response.status_code, code, attempt_ids)
        try:
            return TypeAdapter(response_type).validate_python(response.json())
        except (ValueError, ValidationError) as error:
            raise APIError("The server returned an invalid response.", code="INVALID_RESPONSE") from error

    def problems(self) -> list[ProblemListItemResponse]:
        return self._request("GET", "/problems", list[ProblemListItemResponse])

    def problem(self, problem_id: int) -> ProblemDetailResponse:
        return self._request("GET", f"/problems/{problem_id}", ProblemDetailResponse)

    def learner(self) -> LearnerStateResponse:
        return self._request("GET", "/learner/state", LearnerStateResponse)

    def dashboard(self) -> DashboardSummaryResponse:
        return self._request("GET", "/dashboard/summary", DashboardSummaryResponse)

    def recommendation(self) -> NextRecommendationResponse:
        return self._request("GET", "/recommendations/next", NextRecommendationResponse)

    def attempt(self, attempt_id: int) -> AttemptResponse:
        return self._request("GET", f"/attempts/{attempt_id}", AttemptResponse)

    def events(self, attempt_id: int) -> list[LearningEventResponse]:
        return self._request("GET", f"/attempts/{attempt_id}/events", list[LearningEventResponse])

    def start(self, payload: AttemptStart) -> AttemptResponse:
        return self._request("POST", "/attempts/start", AttemptResponse, payload)

    def reasoning(self, attempt_id: int, payload: ReasoningCreate) -> LearningEventResponse:
        return self._request("POST", f"/attempts/{attempt_id}/reasoning", LearningEventResponse, payload)

    def complete(self, attempt_id: int, payload: AttemptComplete) -> AttemptResponse:
        return self._request("POST", f"/attempts/{attempt_id}/complete", AttemptResponse, payload)

    def abandon(self, attempt_id: int, payload: AttemptAbandon) -> AttemptResponse:
        return self._request("POST", f"/attempts/{attempt_id}/abandon", AttemptResponse, payload)

    def run(self, payload: RunCreate) -> RunResponse:
        return self._request("POST", "/runs", RunResponse, payload)

    def submit(self, payload: SubmissionCreate) -> SubmissionResultResponse:
        return self._request("POST", "/submissions", SubmissionResultResponse, payload)

    def submission(self, submission_id: int) -> SubmissionReadResponse:
        return self._request("GET", f"/submissions/{submission_id}", SubmissionReadResponse)

    def hint(self, payload: HintRequest) -> HintResponse:
        return self._request("POST", "/hints/request", HintResponse, payload)

    def diagnose(self, attempt_id: int, payload: DiagnoseRequest) -> DiagnoseResponse:
        return self._request("POST", f"/attempts/{attempt_id}/diagnose", DiagnoseResponse, payload)

    def analyze(self, attempt_id: int, payload: ReasoningAnalysisRequest) -> ReasoningAnalysisResponse:
        return self._request("POST", f"/attempts/{attempt_id}/reasoning-analysis", ReasoningAnalysisResponse, payload)

    def explain(self, attempt_id: int, payload: PostExplanationRequest) -> PostExplanationResponse:
        return self._request("POST", f"/attempts/{attempt_id}/post-explanation", PostExplanationResponse, payload)

    def understanding_check(self, attempt_id: int, payload: UnderstandingCheckRequest) -> UnderstandingCheckResponse:
        return self._request("POST", f"/attempts/{attempt_id}/understanding-checks", UnderstandingCheckResponse, payload)

    def answer(self, attempt_id: int, check_event_id: int,
               payload: UnderstandingAnswerRequest) -> UnderstandingAnswerResponse:
        return self._request("POST", f"/attempts/{attempt_id}/understanding-checks/{check_event_id}/answer",
                             UnderstandingAnswerResponse, payload)
