# History Adaptation Implementation Plan

> Execute in the current workspace against the user's uncommitted implementation. Use test-driven-development and requesting-code-review. Do not commit unrelated work.

**Goal:** Make recent history, training performance, memory corrections and critical facts reliable inputs to future plans.

**Architecture:** Shared daily fact merging and bounded context selection feed existing model agents. Extend JSON contracts compatibly and preserve immutable reports and versioned plan/memory storage.

**Tech Stack:** Python/Pydantic/SQLite/FastAPI, vanilla JS, pytest, node:test.

- [x] Task 1: Add regression tests in tests/test_history_adaptation.py for same-day statistics, correction ordering, empty lists and bounded context. Implement fitness/feedback_facts.py, fitness/history.py and fitness/feedback_memory.py context selection. Wire coach/training/nutrition dates. Run focused history/daily tests.
- [x] Task 2: Add tests/test_exercise_sessions.py covering set contracts, source validation, same-exercise retrieval and JSON/CSV/Markdown round trips. Extend models.py, safety.py, exporting.py and data_transfer.py. Add training history performance summary and render recorded sets. Keep old result inputs working.
- [x] Task 3: Add tests/test_memory_lifecycle.py for dated evidence, expiry, source revision changes, supersession and protected compression. Extend feedback_contracts.py and introduce focused lifecycle helpers; wire coach normalization/validation and memory context. Keep legacy records readable.
- [x] Task 4: Add partial-fact and critical-confirmation tests. Keep valid optional facts when another field fails; expose guarded confirmation API and front-end actions, invalidate previous analysis and prevent stale plan execution. Verify downstream daily cycle advancement.
- [x] Task 5: Update README, API contract and data boundaries to match current behavior. Independently review implementation, fix findings, run full pytest, frontend tests and ruff. Record verification results and residual limitations.

Regression command: `.\.venv\Scripts\python.exe -m pytest -q`.
Frontend command: `node --test tests/frontend/*.test.cjs` (resolve node runtime if needed).
Lint command: `.\.venv\Scripts\python.exe -m ruff check fitness tests`.

## Verification (2026-10-21)

- Backend: 761 passed in 38.01s; two existing Starlette/AnyIO dependency deprecation warnings.
- Frontend: 51 passed. Ruff: all checks passed. Tracked diff whitespace check passed.
- Independent review: reported findings fixed and rechecked; no remaining P1/P2 findings reported.
- Browser: isolated synthetic SQLite database, live disabled, port 8786. Verified three actual sets (8/8/7 at45kg, only final RPE9), preference confirmation (memory v1 to v2), retirement (v3), and explicit training completion (feedback revision3, prior coaching stale). All three confirmation POSTs returned200; no browser error logs. Test server stopped after inspection.
- Screenshot: `C:/Users/isaac/.codex/visualizations/2026/10/21/01a15c20-e09d-7123-a22d-ff6f2ce9b826/history-adaptation-qa.png`.
- Limits: no real provider evaluation in this change; quoted evidence cannot prove every natural-language interpretation. Missing session IDs group same-day same-action reports; unclear sets remain unknown. Existing user records were not seeded with synthetic data.
