# Zero-cost tutor provider contract

Accepted scope: extend the replaceable Phase 6 `TutorProvider`; keep its task
schemas, public routes, immutable events, hint gates and authority boundaries.
No schema migration, SDK dependency or learner-state policy change is required.

## Provider and cost boundary

- `ZERO_COST_MODE=true` is the default. Configuration rejects every tutor
  provider except `zero_cost`, `groq`, `ollama` and `mock`. Unknown providers
  fail closed. Direct Gemini adapter construction and live Gemini benchmark
  construction are also rejected in this mode.
- `zero_cost` and the `groq` factory alias always select
  `ZeroCostFallbackTutorProvider`: one confirmed-free Groq request, then local
  Ollama. No paid adapter can be configured or injected as its fallback.
- Groq is skipped unless the operator has explicitly set
  `GROQ_FREE_TIER_CONFIRMED=true` and supplied `GROQ_MODEL` and a local key.
  Confirmation means the account and chosen text model currently permit free
  use without billing, credits or a card. Do not enable billing to continue.
- An API key cannot prove account pricing. Confirmation is an operator
  assertion, not automatic billing verification. If free eligibility is
  unknown, expired or changes, keep confirmation false and use local inference.
  External account/pricing policies remain outside application control.
- No account management, purchases, quota bypass, cloud Ollama, hosted paid
  fallback or model download occurs in application code. The existing Gemini
  implementation is retained for historical compatibility, not selected by
  this chain. Disabling zero-cost mode removes its configuration safeguard;
  it is not permitted for this zero-spend deployment.

## Requests, fallback and limits

Groq uses the fixed HTTPS Groq chat-completions endpoint through existing
`httpx`, JSON output mode and local Pydantic validation. Its OpenAI-compatible
wire format does not call OpenAI. Model identity remains configuration.
No compound/tool-enabled generation is supported.

Rate limits, quota/payment/auth errors, timeouts, connection failures, 5xx and
invalid structured responses trigger local fallback. There is no automatic
retry of Groq within an operation, including a 429. Local failure returns a
non-retryable `TutorProviderError`, preventing the service retry loop from
repeating the chain. Existing hint-only static fallback remains available;
other tasks return safe unavailable responses without synthetic evidence.

Groq defaults to an 8-second total deadline (maximum 10); Ollama defaults to
60 seconds (maximum 70), including its model check and generation. The total
chain stays within the default 90-second UI request deadline. Input and output
token limits reuse tutor settings; HTTP response bodies and metadata are also
bounded. CPU inference may time out; this does not affect core coding flows.

## Local-only Ollama

Use `http://127.0.0.1:11434` and a manually installed model; the initial
configurable choice is `qwen2.5-coder:3b`, not a quality-validated selection.
Only HTTP literal loopback IPs with explicit ports are accepted. Credentials,
remote hosts, query strings, cloud model identifiers, proxies and redirects
are refused. Before sending learner context, `/api/show` must identify local
GGUF weights with architecture metadata and no remote host/model. Unknown or
cloud aliases fail closed. No pull endpoint is called.

Disable cloud features in the actual Ollama daemon with `OLLAMA_NO_CLOUD=1`
and restart it. An entry in FastAPI's `.env` does not configure an already
running Ollama daemon. The local daemon and manually installed model are
trusted software; the application cannot attest a modified local server.

## Contracts, evidence and privacy

All five task methods reuse the exact Phase 6 task instructions, versioned
prompts, bounded safe context and structured response schemas. Learner text
is JSON user data, never system instructions. Neither adapter executes code,
determines deterministic correctness, accesses persistence or mutates mastery.

Actual serving provider/model and prompt/schema identifiers remain internal
generation provenance. Delivered content and classifications retain the
existing evidence/derived-label separation. Public DTOs remain unchanged and
allowlisted; hidden execution data never enters context. Logs contain only
fixed provider identity, elapsed milliseconds, safe category and fallback
occurrence. Credentials, headers, exception bodies and learner text are not
logged. Secret-echo output is rejected before it can reach events or responses.

## Verification and deferred work

Fake HTTP tests cover every task, success/fallback, non-repeated 429, bounds,
local-only configuration/model checks, schema failure, secret redaction,
factory/startup rejection and endpoint authority/evidence preservation.
Normal tests perform zero external inference calls. No live smoke test or
Phase 9 multi-model run is authorized here. Real output quality remains
unverified; Groq live testing requires fresh confirmed free eligibility and
explicit authorization. Local Ollama evaluation can be separately scoped.

Provider reference: [Groq rate limits](https://console.groq.com/docs/rate-limits),
[billing](https://console.groq.com/docs/billing-faqs),
[structured outputs](https://console.groq.com/docs/structured-outputs),
[Ollama local-only configuration](https://docs.ollama.com/faq),
[chat API](https://docs.ollama.com/api/chat).
