# Optional provider adapter

The provider is an opt-in OpenAI-compatible HTTP adapter. `FITNESS_LIVE_ENABLED=false` is the default and is checked before constructing any network request. Set it to `true` only in a local environment with a deliberate provider endpoint and API key. HTTPS is required for remote endpoints; HTTP is accepted only for localhost test transports. A DeepSeek key is used only when `FITNESS_BASE_URL` is a DeepSeek endpoint, so changing the endpoint cannot accidentally send that key elsewhere.

The Python contract is:

```python
ProviderReply(content: str | None, tool_calls: list[dict], usage: dict)
OpenAICompatibleProvider(settings, *, transport=None, client=None)
OpenAICompatibleProvider.complete(messages, tools=None, *, timeout_seconds=None, max_output_tokens=None) -> ProviderReply
```

`tool_calls` is normalized to `{"id": str, "name": str, "arguments": dict}`. The adapter accepts at most one call in a reply, sends `parallel_tool_calls=false`, and only validates tool arguments against the declared JSON schema. It never executes a tool. Responses, requests, message fields, tool names, and token counters are bounded; malformed JSON, unknown tools, extra response fields, redirects, and non-finite values produce stable `ProviderError.reason_code` values.

Stable reason codes include `live_disabled`, `missing_api_key`, `invalid_request`, `request_too_large`, `response_too_large`, `timeout`, `network_error`, `http_error`, `invalid_response`, and `invalid_tool_call`. Error messages and logs never include prompts, response bodies, authorization headers, cookies, or API keys. The request log contains only model, latency, HTTP status, and provider-reported token counters. Cost is omitted when the provider does not supply it.

Non-streaming responses are bounded by `Settings.max_response_bytes` (128,000 bytes by default). For streaming text, that same limit applies to the accumulated UTF-8 content, checked before each fragment is emitted. Repeated SSE metadata has a separate transport budget of `max_response_bytes + max_output_tokens * 1024` bytes; raw SSE data is parsed incrementally rather than retained in a second response buffer. This allows ordinary token-by-token plans without removing the bounds on oversized text, metadata-only streams, or incomplete responses.

Model wording is independently checked by `fitness.safety` before it can be applied:

```python
validate_model_advice(candidate, baseline) -> AdviceData
validate_model_plan(candidate, baseline) -> PlanData
validate_model_feedback(candidate, text, day, baseline) -> FeedbackData
health_guardrails(profile, feedback=None, raw_text="") -> list[str]
has_urgent_symptoms(text) -> bool
```

Advice can change only its natural-language summary and suggestions. A plan can change only its summary. Sources, citations, exercises, sets, reps, nutrition fields, guidance, explanations, and every other structured field remain immutable. The feedback validator permits a newly extracted sleep, weight, intake, or completion value only when a bounded deterministic pattern finds the same explicit fact in the original text; ambiguous or ungrounded values are rejected. New narrative fact fields must be exact excerpts from the input. `health_guardrails` always handles known conditions, medications, pregnancy/postpartum context, and abnormal symptoms even when no provider is available.

New plan/advice wording cannot add quantified facts absent from the rule wording or claim personal outcomes and causality. Such content produces `SafetyError("ungrounded_claim")` so orchestration retains the validated baseline. This is a conservative wording filter, not a general proof that arbitrary prose is true.

DeepSeek `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` are accepted only as bounded nonnegative integer counters and included in usage accounting. No pricing or cost is inferred from cache counters. New feedback uncertainty entries must be original-text excerpts or narrow generic extraction ambiguity messages; they cannot introduce new medications or health facts.

Tests inject `httpx.MockTransport` and do not call a real API. Keep live mode off in CI and demos.

## Model-led training (phase 1)

The long-term/daily live training role returns complete candidates, independently of the legacy weekly-plan summary validator above. AgentRuntime supports read-only tools and bounded candidate repair. Defaults are 12 provider calls, 20 tool executions, 2 repairs, 180 seconds per run and 4096 output tokens per call. Configure FITNESS_AGENT_MAX_CALLS, FITNESS_AGENT_MAX_TOOLS, FITNESS_AGENT_MAX_REVISIONS, FITNESS_AGENT_TIMEOUT_SECONDS and FITNESS_AGENT_MAX_OUTPUT_TOKENS. Legacy advice continues using FITNESS_MAX_STEPS.

Provider timeout overrides use the remaining run time capped by the per-call configuration. The transport checks elapsed time during response streaming; the runtime also checks after provider/validation work. Synchronous interruption remains limited by underlying blocking transport timeouts; arbitrary custom providers are not forcibly interrupted.

Training candidates pass structure, equipment, estimated-time, restriction, execution-fact and source-ID checks. Failed runs never call the demo planner as a substitute. Urgent symptoms cause a local safety stop with zero provider calls and skipped_safety provenance. Unresolved activity restrictions conservatively prevent new training. Ordinary fatigue remains model input. Time validation assumes four seconds per repetition, prescribed between-set rest and three minutes warm-up; unilateral/timed movements, transitions and actual pace still need review. Nutrition remains deterministic_local and main-model delegation is a later phase. Earlier wording/fallback descriptions apply to legacy weekly/advice/feedback paths.
