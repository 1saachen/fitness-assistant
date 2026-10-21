# Model-led feedback and memory implementation plan

**Goal:** Natural feedback becomes a model conversation with durable evidence-backed memory; end-of-day reviews leave today's plan intact.

**Architecture:** Save raw feedback before analysis. A bounded read-only model run produces a response, memory changes, optional evidenced facts and a plan decision. Store versioned memory and analysis atomically with input guards. Only decisions invoke planners, with long-term outputs remaining drafts. Compression uses model summaries while retaining source records and protected entries.

**Tech stack:** Existing FastAPI, Pydantic, SQLite, AgentRuntime, plain JavaScript and pytest/node tests. Execute inline in the existing working checkout to preserve ongoing changes.

1. [x] Add behavioral tests in `tests/test_feedback_coach.py`: raw persistence on failure, narrative memory without fields, review/current-day boundary, next-day/long-term decisions, follow-up context, retry, stale inputs, citations and compression.
2. [x] Add migration 5 in `fitness/storage.py`; `fitness/feedback_memory.py` manages source registration, version snapshots, evidence validation, atomic writes and retry state. Extend backup table validation in `fitness/data_transfer.py`.
3. [x] Implement contracts, historical read tools and model orchestration in `fitness/feedback_coach.py`. Use existing AgentRuntime; default review disallows current-day rewrites. Failure keeps source and old plans. Compaction validates references and protected keys before committing.
4. [x] Expose submit/retry/personal-memory APIs in `fitness/main.py`; retain legacy parse/edit APIs but remove unconditional regeneration on confirmation. Include memory and recent raw narrative in future training/nutrition contexts with snapshot guards.
5. [x] Update feedback UI to submit and display natural responses/questions and link follow-up answers; offer retry after analysis failure, show plan status and personal memory. Suppress feedback-driven page auto-regeneration. Preserve old editor for legacy data.
6. [x] Run focused tests then full pytest, frontend tests and Ruff; review correctness and run a live synthetic feedback test using a temporary database. Restart the local app and verify served UI/API. Record actual outcomes and limitations.

Verification commands: `.\.venv\Scripts\python.exe -m pytest tests/test_feedback_coach.py -q`, `.\.venv\Scripts\python.exe -m pytest -q`, `node --test tests/frontend/*.test.cjs`, `.\.venv\Scripts\ruff.exe check fitness tests`.

Verification (2026-10-21): 683 Python tests, 48 frontend tests and Ruff passed. Browser verified default live/review with four existing personal feedback records preserved. Synthetic live runs exercised narrative replies, correction, compaction and future-day generation; long-term decisions were proposed without confirmation, but the final real planner attempt returned output_invalid and did not save a draft. Failures retain original plans and expose retry. See data/local/feedback-memory-live/report.json for the last run.
