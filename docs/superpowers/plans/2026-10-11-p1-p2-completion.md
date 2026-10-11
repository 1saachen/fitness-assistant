# P1/P2 completion plan

Approved basis: `docs/work-log.md`, the user's single-agent decisions, and the request to continue through P2 without further checkpoints.

Keep the existing `codex/fitness-mvp` checkout. Four independent ownership areas may run in parallel; integration, reviews and final acceptance run sequentially.

## Acceptance requirements

- [x] Retrieval evaluation: committed cases for sleep, fatigue, diet, plateau, supplements and irrelevant feedback; preferred collection, top-3 coverage, misleading recall and cross-issue dedup metrics; local JSON/Markdown reports.
- [x] Knowledge governance: readable distinction between creator statements, editorial synthesis and system judgement, evidence/limitations, supplement review checklist, manifest/strategy membership change check and unavailable regression.
- [x] Single-agent orchestration: typed tools for profile/current plan/knowledge/history/trend/similar feedback; deterministic demo and bounded optional model tool selection; chronological tool trace, safe failures and preserved optimistic locks.
- [x] Local plan changes: preview and explicit confirmation of bounded today-only training changes; immutable base plan; auditable old/new values, trigger, evidence and revision/profile safeguards.
- [x] Similar history explanations: past advice and explicitly observed subsequent facts only; no invented outcomes or causality.
- [x] Nutrition: budget and period, meal source, occasional options, allergy and restrictions materially affect options; unknown allergy requests clarification instead of claiming safe meals.
- [x] UI: brief optional why explanations, correction/regeneration workflow, trends, live-mode availability and fallback messages, plan change preview/confirmation.
- [x] Provider: explicit enablement, OpenAI-compatible HTTP adapter, timeout, bounded tool loop, structured output validation, safe fallback, metadata-only logs and usage accounting; demo never calls provider.
- [x] Safety: independently enforce no model-written training prescriptions, supplement dosing or diagnosis; facts are validated and never saved before user confirmation.
- [x] Vector evaluation gate assessed: same-case keyword/TF-IDF lexical control completed; no local neural embedding model available and no semantic benefit measured, so neural candidate and vector infrastructure are explicitly deferred. This is an assessed/deferred gate, not a completed semantic benchmark.
- [x] Database: versioned migrations, old-snapshot compatibility, consistent backup/restore and validated JSON/CSV/Markdown feedback import preview/confirmation with idempotency; existing exports retained.
- [x] Boundaries: multi-user/auth isolation and migration design, local/Docker/cloud assessment, secrets/log/network boundaries, external platform and Apple Health/Health Connect assessment; no private API or account writes.
- [x] Verification: focused red/green tests, full Python/frontend checks, real library evaluation/governance, fresh demo walkthrough, browser workflow, independent spec/code review, requirement-by-requirement evidence audit.
- [x] Update README, API contract, work log and final completion report with actual evidence; commit finished changes.

## Sequence and ownership

1. Knowledge task: `fitness/evaluation.py`, `fitness/evaluation_cli.py`, `fitness/governance.py`, fixtures/reports and related tests/docs only.
2. Provider task: `fitness/provider.py`, `fitness/safety.py`, `fitness/config.py`, provider/safety tests and provider docs only. Adapter API is `complete(messages, tools=None) -> ProviderReply(content, tool_calls, usage)`; config `live_enabled` gates all network calls.
3. Data task: `fitness/storage.py`, `fitness/data_transfer.py`, data CLI and tests/docs only. Expose `Store.record_plan_change(...)`, `Store.plan_changes(...)`, versioned migration and backup.
4. Primary integration: typed local tools and orchestration, nutrition, models/API/frontend, integration tests; coordinate data/provider contracts.
5. Review each area's specification then code quality, repair and rerun. Audit all route-map requirements, reconcile obsolete multi-agent wording with the approved single-agent architecture.

No live provider call without the application's explicit opt-in; tests use local HTTP transports. No third-party synchronization writes. Evaluations may conclude that an optional integration is deferred when evidence supports that conclusion; code features above must actually work.

Completion evidence: `docs/p2-completion-audit.md`. P2 deployment and official-platform items are assessments, not deployed services. Provider network tests use MockTransport; no real provider request was made. Final verification: 456 Python tests and 25 frontend tests, real-corpus evaluation, CLI walkthrough/backup/restore, browser confirmation/correction/mobile checks. Changes are retained on the feature branch.
