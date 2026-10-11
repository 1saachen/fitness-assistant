# Personal History Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add deterministic local tools for recent feedback, 7/14/21-day trends, and similar-feedback retrieval, then expose them through read-only APIs and a compact feedback trend view.

**Architecture:** `fitness/history.py` owns issue classification, date filtering, metric filtering, deterministic trend calculations, and similarity scoring over confirmed SQLite feedback records. `fitness/main.py` exposes read-only endpoints and the frontend renders their returned summaries; the Agent remains unchanged in this stage. Missing measurements stay `null` with explicit sample counts and data-quality messages.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic-compatible JSON records, SQLite through the existing `Store`, vanilla JavaScript, Node test runner, pytest.

---

### Task 1: Add an explicit diet execution fact

**Files:**
- Modify: `fitness/models.py`
- Modify: `fitness/agent.py`
- Modify: `fitness/static/app.js`
- Test: `tests/test_models.py`
- Test: `tests/test_agent.py`

- [x] Add failing tests proving `diet_followed_plan` accepts `true`, `false`, or `null`, and that the demo parser only sets it for explicit plan-adherence language.
- [x] Run the focused tests and confirm they fail because the field does not exist.
- [x] Add `diet_followed_plan: bool | None = None` to `FeedbackData`, conservative parser rules, and an editable frontend field.
- [x] Run the focused tests and confirm they pass.

### Task 2: Implement recent-feedback and trend tools

**Files:**
- Create: `fitness/history.py`
- Create: `tests/test_history.py`

- [x] Add failing tests for confirmed-only date windows, issue and metric filters, missing values, 7/14/21-day sample counts, sleep/weight summaries, fatigue report rate, training completion rate, and explicit diet execution rate.
- [x] Run `pytest tests/test_history.py -q` and confirm import failure for `fitness.history`.
- [x] Implement `get_recent_feedback()` and `summarize_recent_trend()` with inclusive calendar windows, stable newest-first ordering, and no inferred values.
- [x] Run the focused tests and confirm they pass.

### Task 3: Implement similar-feedback retrieval

**Files:**
- Modify: `fitness/history.py`
- Modify: `tests/test_history.py`

- [x] Add failing tests for deterministic ranking, current-record exclusion, issue overlap, matched-signal explanations, limits, and insufficient comparable history.
- [x] Run the focused tests and confirm the new tests fail for the missing function.
- [x] Implement `find_similar_feedback()` using issue overlap and explicit categorical signals; include previous advice summaries but never infer outcomes or medical causality.
- [x] Run the focused tests and confirm they pass.

### Task 4: Expose read-only history APIs

**Files:**
- Modify: `fitness/main.py`
- Modify: `tests/test_api.py`
- Modify: `docs/api-contract.md`

- [x] Add failing API tests for `/api/history/recent`, `/api/history/trends`, and `/api/history/similar/{feedback_id}`, including invalid windows and missing records.
- [x] Run the focused API tests and confirm 404/validation failures.
- [x] Add the three endpoints using the local history functions and structured errors.
- [x] Run the focused API tests and confirm they pass.

### Task 5: Add the compact trend view

**Files:**
- Modify: `fitness/static/index.html`
- Modify: `fitness/static/app.js`
- Modify: `fitness/static/export.css`
- Modify: `tests/frontend/context.test.cjs`

- [x] Add failing frontend tests for trend formatting, explicit insufficient-data labels, and zero/false preservation.
- [x] Run the focused Node tests and confirm the missing formatter failure.
- [x] Add a 7/14/21-day selector and compact cards for sleep, weight, fatigue reports, training completion, and explicit diet execution.
- [x] Load trends on application start and after feedback confirmation, without blocking the core page when the endpoint fails.
- [x] Run the frontend tests and syntax check.

### Task 6: Document, verify, and commit

**Files:**
- Modify: `README.md`
- Modify: `docs/work-log.md`

- [x] Document history endpoints, metric semantics, and the rule that missing values are not inferred.
- [x] Mark the completed P1 history/trend items in the work log and add a dated update.
- [x] Run `pytest -q`, Ruff, compileall, all frontend tests, JavaScript syntax check, and `git diff --check`.
- [x] Commit the completed stage with a focused message.
