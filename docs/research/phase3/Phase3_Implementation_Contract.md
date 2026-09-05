# Phase 3 MVP Implementation Contract: Execution Architecture

*Note: This specification distinguishes between evidence-backed requirements (e.g., how Judge0's API functions and standard security models) and architectural judgment (e.g., how to organize the Python FastAPI services).*

## 1. ExecutionProvider Interface

**Architectural Judgment:** The core application must interact exclusively with an abstract interface. The application must not know Judge0 exists.

**Conceptual Request Contract (`ExecutionRequest`):**
*   `code` (str): The raw Python source code.
*   `language_id` (int/str): A generalized ID for Python 3.
*   `test_cases` (List[TestCaseExecution]): Contains `id`, `input_data`, `time_limit_secs`, `memory_limit_kb`.

**Conceptual Output Contract (`ExecutionResult`):**
*   `test_case_id` (int)
*   `status` (ExecutionStatus Enum)
*   `stdout` (str)
*   `stderr` (str)
*   `compile_output` (str)
*   `time_ms` (float)
*   `memory_kb` (float)

**Execution Status Model (Strict Enum):**
`QUEUED`, `RUNNING`, `ACCEPTED` (meaning execution finished without crashing, *not* necessarily mathematically correct), `WRONG_ANSWER` (calculated by Evaluation Service, not ExecutionProvider), `COMPILATION_ERROR`, `RUNTIME_ERROR`, `TIME_LIMIT_EXCEEDED`, `MEMORY_LIMIT_EXCEEDED`, `SYSTEM_ERROR`.

**Timeout & Error Handling:**
*   If the `ExecutionProvider` internal HTTP request times out or receives a `502 Bad Gateway`, it must catch the exception and yield `SYSTEM_ERROR`.
*   If the code exceeds the time limit, it yields `TIME_LIMIT_EXCEEDED`.

---

## 2. Judge0 Adapter

**Evidence-Backed Requirement:** Judge0 exposes a batch API that allows multiple test cases to be executed in a single HTTP call, reducing network overhead.

**Payload Structure (to Judge0 `/submissions/batch`):**
```json
{
  "submissions": [
    {
      "source_code": "...",
      "language_id": 71, // Python 3.x
      "stdin": "5\n1 2 3 4 5",
      "cpu_time_limit": 2.0,
      "memory_limit": 256000,
      "enable_network": false
    }
  ]
}
```

*   **Requesting Execution:** Send an async HTTP POST to `/submissions/batch?base64_encoded=false&wait=true`.
*   **Wait=True Handling:** Because `wait=true` holds the connection open, the `httpx.AsyncClient` must use a strict timeout that is *slightly larger* than the Judge0 `cpu_time_limit` (e.g., if code limit is 2.0s, httpx timeout should be 5.0s to account for networking and container startup).
*   **Status Mapping (Judge0 `status.id` $\rightarrow$ Internal Enum):**
    *   `3` (Accepted) $\rightarrow$ `ACCEPTED`
    *   `5` (Time Limit Exceeded) $\rightarrow$ `TIME_LIMIT_EXCEEDED`
    *   `6` (Compilation Error) $\rightarrow$ `COMPILATION_ERROR` (rare for Python, but possible for syntax errors)
    *   `7-12` (Runtime Errors) $\rightarrow$ `RUNTIME_ERROR`
    *   `13-14` (Internal Errors) $\rightarrow$ `SYSTEM_ERROR`
    *   *Note: Do not pass `expected_output` to Judge0. Let Judge0 return `3` (Accepted), and do the correctness comparison in the FastAPI EvaluationService.*

---

## 3. Test-Case Execution Flow

**Architectural Judgment:** The ExecutionProvider executes code. The EvaluationService determines if the output is correct.

*   **Visible vs Hidden:** Both are passed to the ExecutionProvider blindly. The ExecutionProvider does not care if a test is hidden.
*   **Batching:** All test cases for a submission must be executed in a single `execute_batch()` call to minimize latency.
*   **Stdin Construction:** Problem test cases must define exact string representations for `stdin`.
*   **Stdout Normalization:** The EvaluationService must:
    1.  Strip leading/trailing whitespace.
    2.  Normalize line endings (convert `\r\n` to `\n`).
*   **Numeric Output:** If a problem is flagged as requiring floating-point comparison, use `math.isclose()` with a defined tolerance (e.g., `1e-5`). Otherwise, use exact string matching after normalization.
*   **Aggregation:** The overall Submission status is determined by the "worst" test case. 
    *   If 1 test TLEs and 9 are correct $\rightarrow$ Overall Status: `TIME_LIMIT_EXCEEDED`.
    *   If 1 test WA and 9 are correct $\rightarrow$ Overall Status: `WRONG_ANSWER`.

---

## 4. Evaluation Result Contract

The `EvaluationService` consumes the `ExecutionProvider` results and produces a provider-independent `SubmissionResult` object for the API and Database:

```json
{
  "submission_id": 1042,
  "overall_status": "WRONG_ANSWER",
  "tests_passed": 7,
  "tests_total": 10,
  "edge_cases_failed": 2,
  "execution_time_ms": 42.1,
  "memory_used_kb": 12054,
  "test_results": [
    {
      "test_case_id": 1,
      "is_hidden": false,
      "status": "ACCEPTED",
      "stdout": "42"
    },
    {
      "test_case_id": 2,
      "is_hidden": true,
      "status": "WRONG_ANSWER",
      "stdout": null // REDACTED
    }
  ]
}
```

---

## 5. Hidden-Test Security

**Evidence-Backed Requirement:** If hidden tests are leaked, the learning model is compromised, as students will hard-code if-statements for the hidden inputs.

*   **Rule 1:** When the API returns a failed hidden test, the `stdout`, `stderr`, `input`, and `expected_output` fields must be explicitly stripped or set to `null` in the Pydantic response schema.
*   **Rule 2:** The UI should only display: *"Failed hidden test case."*
*   **Rule 3:** The LLM (Tutor) *is* allowed to see the hidden test failure context in its private prompt so it can generate a conceptual hint (e.g., "Think about negative numbers"), but the LLM system prompt must strictly instruct it not to reveal the exact hidden test input.

---

## 6. Student-Code Security

To protect the host and application, the following must be enforced in the Judge0 Adapter payload:

*   **Filesystem:** Judge0's `isolate` provides an ephemeral `tmpfs`. The FastAPI app does not need to configure this, but must not rely on files being preserved between test cases.
*   **Environment Variables:** Do not pass *any* environment variables in the Judge0 payload.
*   **Network:** Explicitly set `"enable_network": false` in the Judge0 payload to prevent HTTP requests from the student's code.
*   **Resource Exhaustion:** Set `cpu_time_limit` to 2.0s, `wall_time_limit` to 5.0s, and `memory_limit` to 256MB.
*   **Excessive Output:** Judge0 naturally truncates output. Ensure FastAPI limits string parsing size to prevent memory exhaustion when decoding the JSON response.

---

## 7. API Contract for DEV Placement OS

**Internal Flow:**
1.  **POST `/submissions`**: Controller receives `code` and `problem_id`.
2.  **`ProblemService`**: Fetches problem and all associated test cases from DB.
3.  **`ExecutionService` (Adapter)**: Calls Judge0, returns raw execution metrics and `stdout`.
4.  **`EvaluationService`**: Compares `stdout` vs `expected_output`. Generates `SubmissionResult`.
5.  **`SubmissionService`**: Saves `Submission` and `TestResult` records to the database.
6.  **API Response**: Serializes the `SubmissionResult` (redacting hidden test data) and returns to the client.

---

## 8. Phase 3 MVP Boundary

**MUST Implement Now:**
*   `ExecutionProvider` abstract base class.
*   `Judge0ExecutionService` adapter utilizing HTTP batching and `wait=true`.
*   String and whitespace normalization for test comparison.
*   Strict redaction of hidden test case outputs in the Pydantic response.

**SHOULD Defer:**
*   AST-based cyclomatic complexity checks.
*   Floating-point tolerance (unless specifically required by the first MVP DSA problem).
*   LLM-based code correctness analysis.

**FUTURE Self-Owned Infrastructure:**
*   Kafka/Redis queues.
*   Firecracker MicroVM worker fleets.
*   Webhooks for async execution polling.

---

## 9. Testing Strategy

**Architectural Judgment:** Unit tests must not depend on a live Judge0 container. 

*   **MockExecutionProvider:** Create a mock class implementing `ExecutionProvider`. It should return hard-coded `ExecutionResult` objects.
*   **Test 1 (Evaluation Logic):** Assert that a mocked output with extra spaces correctly evaluates to `ACCEPTED`.
*   **Test 2 (Overall Status):** Assert that 9 `ACCEPTED` and 1 `TIME_LIMIT_EXCEEDED` results in an overall `TIME_LIMIT_EXCEEDED`.
*   **Test 3 (Security Redaction):** Assert that the Pydantic API response schema strips `stdout` for `is_hidden=True` test cases.
*   **Integration Test:** Provide a marked `@pytest.mark.integration` test that actually hits a local Judge0 container, which developers can skip in CI if Judge0 is unavailable.

---

## 10. Codex Implementation Checklist

1.  [ ] Define `ExecutionStatus` enum matching the PRD exactly.
2.  [ ] Create `ExecutionRequest` and `ExecutionResult` Pydantic schemas.
3.  [ ] Create `ExecutionProvider` Abstract Base Class.
4.  [ ] Create `MockExecutionProvider` for unit testing.
5.  [ ] Implement `Judge0ExecutionService` utilizing `httpx` and `/submissions/batch?wait=true`.
6.  [ ] Implement HTTP timeout catching to return `SYSTEM_ERROR`.
7.  [ ] Implement Judge0 status ID mapping to internal `ExecutionStatus`.
8.  [ ] Create `EvaluationService.evaluate()` to handle string normalization and equality checking.
9.  [ ] Create the `SubmissionResult` schema with strict hidden-test redaction rules (`@computed_field` or custom `model_dump` logic).
10. [ ] Write unit tests for `EvaluationService` using `MockExecutionProvider`.
11. [ ] Integrate execution flow into the `POST /submissions` endpoint.
