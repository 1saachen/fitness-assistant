# MVP HTTP contract

All endpoints are same-origin JSON under `/api`. This release runs locally as a single-user app. Errors return a structured `detail` object with `code`, `message`, and `retryable`, or standard validation errors.

## Profile

- `GET /api/state`: `{profile, profile_version, plans, feedback, mode, available_modes, model, plan_changes, example_available, knowledge_status, today}`. Profile may be null; plans/feedback are newest first. Default reports `mode: "demo"`, `available_modes: ["demo"]`, and `model: null`; explicit provider enablement and key add live availability. Today uses Asia/Shanghai by default. `knowledge_status` is `unknown` before a profile exists, otherwise `ok`, `unavailable`, or `capacity_exceeded`.
- `GET /api/example-profile`: the raw nested local example JSON, only on explicit click. No automatic database import.
- `PUT /api/profile`: `{profile: <nested JSON>, expected_version: <0 for first save>}` → `{version, data, created_at}`. Profile retains the structure of `data/examples/demo-profile.json`. Extra fields rejected. Nullable fields stay null. Conflict returns 409.

- `GET /api/export/{plan|feedback|advice}?format={json|csv|markdown}`: downloads local records. Optional `plan_id` or `feedback_id` narrows the export. Empty selections return `404` with `detail.code: "export_not_found"`; unsupported formats return `400` with `detail.code: "export_format_invalid"`.

Mutation conflicts use stable codes: profile version conflicts use `profile_version_conflict`; feedback revision or concurrent advice conflicts use `feedback_revision_conflict`.

## Plans

- `POST /api/plans`: `{start_date: "YYYY-MM-DD", mode: "demo" | "live"}` → plan record.
- `POST /api/plans/{id}/confirm`: no body → confirmed record; repeat confirmation is idempotent. If profile changed since generation, returns 409.
- Plan record: `{id, version, profile_version, status: "draft"|"confirmed", created_at, data, trace, mode}`.
- Plan data: `{title, summary, days, nutrition, questions, source_ids, strategy_context, knowledge_context}`.
- `strategy_context` is a list of persisted baseline snapshots: `{id, title, summary, action_rules, knowledge_item_ids}`. Plan generation selects every reviewed baseline strategy applicable to the profile's primary goal; it does not retrieve a small top-k subset.
- `knowledge_context` is a list of persisted source snapshots: `{id, title, excerpt, creator_name, collection, videos, matched_issues}`. Each `videos` entry is `{bvid, title, url, published_at}`. For plans it contains the approved knowledge referenced by all selected baseline strategies, subject to the data model's atomic persistence limits.
- Day: `{day_index: 0..6, label, kind: "training"|"rest", exercises, estimated_minutes}`.
- Exercise: `{exercise_id, sets, reps_min, reps_max, rest_seconds, name}`. The server enriches names and computes duration. Rest days have no exercises and zero duration.
- Nutrition: `{approach, meal_options: [{meal, suggestions: [string]}], budget_note}`. Qualitative only in this version; no fabricated calorie or cost totals.
- `questions` and `source_ids` are string lists. `source_ids` exactly identifies the snapshots actually persisted in `knowledge_context`; when the complete context exceeds persistence limits, strategy and knowledge snapshots degrade together to empty lists rather than saving a partial baseline. Need-information errors have `detail: {message, fields: [string]}`.
- Plan `trace` is `{steps: ["baseline_strategy_selection", "planner"], strategy_ids, knowledge_item_ids, knowledge_status}`. `knowledge_item_ids` mirrors the persisted plan `source_ids`, including an empty list after atomic capacity degradation. `knowledge_status` is `"ok"`, `"unavailable"`, or `"capacity_exceeded"`; `"capacity_exceeded"` means an otherwise available context exceeded 20 strategy snapshots or 100 citation snapshots, so both snapshot lists and their trace IDs were atomically omitted while core rule-based planning continued.

## Feedback

- `POST /api/feedback/parse`: `{text, date: "YYYY-MM-DD", mode}` → feedback record in draft status.
- Feedback record: `{id, date, raw_text, status, revision, data, advice, advice_error, mode, trace, created_at, updated_at}`.
- Feedback data: `{date, training_summary, training_completed: true|false|null, food_summary, diet_followed_plan: true|false|null, sleep_hours, sleep_date, fatigue, weight_kg, intake_kcal, uncertainties: [string]}`. All scalar fields other than date are nullable. `diet_followed_plan` is populated only from an explicit user statement; food descriptions do not imply adherence. `intake_kcal` stays null unless explicitly provided by the user. Sleep date may be null to indicate ambiguity.
- `POST /api/feedback/{id}/confirm`: `{data: <editable feedback data>, expected_revision: <current>}` → confirmed record. Same confirmed content is idempotent. A correction uses the current revision, preserves audit history, and atomically clears the prior advice, advice error, and knowledge-retrieval trace; its trace returns to `{steps: ["parser"]}` until advice is generated again.
- `POST /api/feedback/{id}/advice`: `{mode}` → updated record. Requires confirmed feedback; no mutation of plans. Advice data is `{summary, suggestions, source_ids, knowledge_context}` and uses the same knowledge citation snapshot shape as plans.
- Advice retrieval extracts issues from the confirmed structured feedback, the feedback row's stored `raw_text`, and feedback history (newest first). The saved profile's primary goal supplies auxiliary terms and collection preferences for each extracted issue but does not create issues by itself. Exact full-title matches rank before collection preferences; otherwise each issue's preferred collections rank before goal-preferred collections and the rest of the library. Each issue retrieves 3 items by default and may expand to 5 to cover otherwise unmatched query terms. Results are deduplicated across issues, so a sleep/fatigue/diet response may persist more than 5 total citations. `matched_issues` records every issue supported by a citation.
- Advice `trace` is `{steps: ["issue_extraction", "knowledge_retrieval", "advisor"], issues, profile_goal, issue_goal_context, knowledge_query_terms, knowledge_item_ids, knowledge_status}`. `issues` contains issue IDs. `profile_goal` records the primary goal used when advice was generated. `issue_goal_context` preserves one ordered `{issue, terms, collections}` entry per extracted issue; these auxiliary goal terms remain separate from the backward-compatible `knowledge_query_terms`, which contains only the deterministic issue terms. `knowledge_item_ids` mirrors the advice `source_ids` actually persisted. The response returns the trace saved atomically with the advice, and later `GET /api/state` responses expose the same persisted trace even if the profile changes afterward. When knowledge is unavailable, `profile_goal` is still recorded and `issue_goal_context` is empty. Advice uses the same `"ok"`, `"unavailable"`, and `"capacity_exceeded"` status values as plans; capacity degradation atomically omits all citation snapshots and IDs, suppresses citation-derived suggestions, and preserves the core rule-based advice.
- Advice persistence is conditional on the feedback revision and `updated_at` snapshot read before generation, and on the profile version used for generation. If that feedback snapshot is already consumed or either dependency changes, the endpoint returns 409 without overwriting the newer record. Other feedback-history rows are read newest first but are not part of this strict CAS token.
- A failed advice save with no generated advice replaces any prior retrieval trace with `{steps: ["advisor"], status: "failed"}` instead of retaining stale issues or source IDs. Successful legacy callers that omit a replacement trace preserve the existing trace.
- `GET /api/feedback/{id}/revisions`: list of `{revision, data, created_at}`.

## Knowledge availability and compatibility

Knowledge loading and validation are optional enrichment. If approved knowledge or the reviewed strategy artifact is missing, unreadable, or invalid, plan and advice generation still return 200 using the core rule-based behavior. Their nested context lists and trace ID lists are empty and `trace.knowledge_status` is `"unavailable"`. Storage failures, request validation failures, and unexpected programming errors are not converted to this fallback.

## Personal History

- `GET /api/history/recent?days={7|14|21}&end_date=YYYY-MM-DD&issue=<optional>&metric=<optional>` returns confirmed feedback in an inclusive calendar window, newest first. Supported metric filters are `sleep_hours`, `weight_kg`, `fatigue`, `training_completed`, and `diet_followed_plan`; a metric filter only returns records with an explicit non-null value.
- `GET /api/history/trends?days={7|14|21}&end_date=YYYY-MM-DD` returns independent sample counts and deterministic summaries for sleep, weight, fatigue reports, training completion, and explicit diet execution. Numeric fields include average/minimum/maximum/range; weight also includes chronological change when at least two samples exist. A single sample is always marked `insufficient_data`.
- `GET /api/history/similar/{feedback_id}?limit=3` ranks confirmed historical feedback by shared issue and explicit categorical signals. It excludes the current record and may return a previous advice summary, but never an inferred outcome.
- Unsupported windows, metrics, or limits return `400` with `detail.code: "history_query_invalid"`.

Records created before this contract may omit `strategy_context`, `knowledge_context`, `source_ids`, or the new trace fields. Clients must treat absent nested lists and trace lists as empty and an absent knowledge status as unknown; no database migration is required to read those records safely.

## Interface requirements

Four tabs: 概览, 我的档案, 本周计划, 每日反馈 (history on daily feedback). Profile form must retain unknown optional fields and support at least the existing sample fields, session duration, dietary restrictions and recovery. Gym equipment values: `dumbbell`, `barbell`, `machine`, `bodyweight`; null means unspecified, not empty set. Primary goals: `fat_loss`, `muscle_gain`, `general_health`. Health/allergy status: `none_known_self_reported`, `unknown`, `has_conditions` / `has_allergies` with a separate detail string if needed.

Do not hard-code user profile numbers into tracked HTML/JS; obtain them only when the user clicks import. Use an honest mode selector, visible save confirmations, reversible draft edits, loading buttons, dates, friendly errors and source links where supported. Source IDs are resolved using `GET /api/sources` → list of `{id, title, url, note}`. Exercise IDs resolved server-side. Treat all generated content as untrusted text, never raw HTML.
# P1/P2 additions (2026-10-11)

`GET /api/state` returns `available_modes`, optional configured `model`, and `plan_changes`. `demo` never calls a provider. `live` requires explicit enablement and a key; provider errors fall back to deterministic results with `trace.provider.status="fallback"` and a sanitized reason.

The single agent saves ordered `trace.tool_calls`, deterministic trend and prior-only similar-history results, validated explanations, provider token totals and any parser provider metadata. Source snapshots and the previous optimistic revision/profile guards remain in place.

| Endpoint | Contract |
| --- | --- |
| `POST /api/import/feedback/preview` | `{content, format}` with format json/csv/markdown; validates facts without writing and returns batch_id/items/errors/skipped |
| `POST /api/import/feedback/confirm` | same content and format plus `batch_id`, `confirmed:true`; all-or-nothing import, fingerprints/idempotency, ignores generated advice/trace |
| `GET /api/feedback/{id}/training-adjustment` | current-day-only conservative reduction preview; empty changes when not applicable |
| `POST /api/feedback/{id}/training-adjustment/confirm` | `{proposal:<exact preview>, confirmed:true}`; recomputes and rejects stale/tampered preview, transactional immutable-base audit |
| `GET /api/plans/{id}/changes` | chronological confirmed change records |

Adjustment paths are restricted to `days.<day_index>.exercises.<exercise_index>.sets`; only reductions to at least one set are allowed. Date, confirmed feedback, profile version, revision, feedback timestamp and prior change count must agree. The stored base plan JSON is unchanged. State responses suppress previously confirmed obsolete proposals while stored trace remains an audit snapshot.

Plan data adds optional `recovery_guidance` and `supplement_guidance`; advice adds optional `explanations` with issue/facts/rule/history/knowledge_ids. Old records read with default empty lists. Explanations do not imply medical causality. Similar history never includes same-day or future records.
