# Readable plan streaming implementation plan

**Goal:** Display live readable plan content before structured validation finishes.

**Architecture:** An SSE response wraps existing planning operations with a scoped
event sink. AgentRuntime generates a streamed readable draft, includes it in its
subsequent structured request, and retains existing validation and persistence.

**Tech stack:** FastAPI, httpx, contextvars, bounded queues, browser ReadableStream.

- [x] Add failing transport tests for incremental UTF-8, truncation and errors.
- [x] Add provider text streaming using the existing request bounds and normalizer.
- [x] Add scoped SSE events and agent preview/extraction tests, with shared budgets.
- [x] Add streaming routes reusing current endpoints and their error contracts.
- [x] Add browser SSE reader, draft display and early-delivery/error tests.
- [x] Run backend and frontend suites, inspect diffs and record results.

Review added regression tests for upstream DONE before socket closure and bounded
worker admission. Targeted checks include early text delivery, usage, timeout/call
budgets, truncated response rejection, preserved needs-input details, saved result
compatibility and disconnect before persistence. Full backend suite: 674 passed
(two dependency deprecation warnings). Frontend suite: 47 passed. Repository
Ruff checks, Python compilation, JavaScript syntax and git diff whitespace checks
passed.
Live provider behavior is exercised with controlled httpx byte streams; no real
model request or live browser session was used for validation.
