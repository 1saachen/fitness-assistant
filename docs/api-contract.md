# MVP HTTP contract

## Required user model configuration (2026-10-21)

All generation requests accept only `mode: "live"`, which is also the default when omitted. `demo` is rejected with 422. Long-term, daily, legacy weekly, nutrition, feedback parsing/advice, feedback understanding and plan retry endpoints require the user's configured model API. Missing configuration returns 503 with `detail.code: "model_not_configured"` before generation starts, including for streaming endpoints. Set `FITNESS_API_KEY`, `FITNESS_BASE_URL` and `FITNESS_MODEL` in `.env` and restart; the old `FITNESS_LIVE_ENABLED` environment switch is no longer used.

`GET /api/state` always returns `mode: "live"`, plus `model_configured: boolean` and `available_modes: ["live"]` when configured or `[]` otherwise. `/api/planning/state` also includes `model_configured`. These fields indicate local configuration presence, not a successful upstream authentication check. Neither endpoint exposes the key.

Profile/history access and original feedback recording remain available without a model. Model errors preserve existing plans and reports, and never return a locally generated replacement. Legacy provider failures return 502 (504 for timeout) with a safe reason code; current planning failures retain their structured error contract. Local validation and urgent-symptom safety stops remain active.

## Model-led daily feedback and personal memory (2026-10-21)

Profiles accept optional `training.strength_baseline` fields: `squat_1rm_kg`, `bench_press_1rm_kg`, `deadlift_1rm_kg` (positive kg, total including bar), `pull_up_max_reps` (nonnegative integer for strict bodyweight pull-ups), `recorded_on` and `notes`. Missing measurements stay null, including for existing profiles. Notes identify estimated versus tested 1RM and differences in dates/technique. These user-reported starting references remain separate from planned `weight_kg` / `target_rpe` and feedback's actual performance. Planning models receive all three sources and prioritize comparable recent performance when calibrating future loads; feedback never silently overwrites profile 1RM. The feedback page no longer displays or fetches the trend panel; historical APIs and model read tools remain available.

`POST /api/feedback/record` accepts `{text, date, request_key, timing?: "review" | "remaining", parent_feedback_id?: string}`. It saves the original user report independently of model availability and returns the feedback with a `coaching` state. Reusing a request key with identical content returns the same record; changing its content returns 409. `review` is the default; `remaining` is valid only for today.

`POST /api/feedback/{id}/understand` interprets that saved report in live mode. The response includes `coaching.status` (`saved`, `processing`, `ready`, `failed`, or computed `stale`), natural reply, suggestions/questions, evidence-backed memory changes and a plan decision. Successful retries are idempotent. `?refresh=true` explicitly reinterprets a correction or retries failed memory organization. `POST /api/feedback/{id}/retry-plan` retries a failed plan application; outdated inputs require reinterpretation. Failures preserve the original report. Planning failure does not erase a completed response or memory update.

`keep` leaves plans intact; `adjust_next` applies a future daily plan; `propose_long_term` creates a future draft without confirming it. `adjust_remaining` is accepted only in explicit remaining mode for today. Legacy field confirmation no longer regenerates today's plan. Reopening an existing daily plan is read-only. Completed content and confirmed long-term nutrition targets remain protected by planners.

`GET /api/personal-memory` returns current version, active entries, source references, stale keys, approximate context budget and compression trace. `GET /api/feedback/{id}` retrieves the original and response. Follow-up answers use a new record with `parent_feedback_id`; the model sees the parent's original reply and questions. Memory snapshots and coaching state are included in schema-5 database backups. Ordinary legacy feedback exports do not export the whole memory database.

Compaction retains original reports and old snapshots, protects active restrictions/preferences/open questions and cannot promote inferred patterns into facts. It may remain over its preferred budget when protected content dominates. Optional structured statistics with invalid schema or unsupported evidence are discarded as a group and recorded in `trace.ignored_optional_facts`; the remaining response, memory and decision must still pass all checks. Structural checks and quoted evidence do not guarantee the semantic correctness of every model interpretation; users can correct memory through subsequent feedback.

All endpoints are same-origin JSON under `/api`. This release runs locally as a single-user app. Errors return a structured `detail` object with `code`, `message`, and `retryable`, or standard validation errors.

## Profile

- `GET /api/state`: `{profile, profile_version, plans, feedback, mode, available_modes, model, model_configured, plan_changes, example_available, knowledge_status, today}`. Profile may be null; plans/feedback are newest first. Always reports `mode: "live"`; `model_configured` shows whether an API key is present, and `available_modes` is `["live"]` or `[]`. Today uses Asia/Shanghai by default. `knowledge_status` is `unknown` before a profile exists, otherwise `ok`, `unavailable`, or `capacity_exceeded`.
- `GET /api/example-profile`: the raw nested local example JSON, only on explicit click. No automatic database import.
- `PUT /api/profile`: `{profile: <nested JSON>, expected_version: <0 for first save>}` → `{version, data, created_at}`. Profile retains the structure of `data/examples/demo-profile.json`. Extra fields rejected. Nullable fields stay null. Conflict returns 409.

- `GET /api/export/{plan|feedback|advice}?format={json|csv|markdown}`: downloads local records. Optional `plan_id` or `feedback_id` narrows the export. Empty selections return `404` with `detail.code: "export_not_found"`; unsupported formats return `400` with `detail.code: "export_format_invalid"`.

Mutation conflicts use stable codes: profile version conflicts use `profile_version_conflict`; feedback revision or concurrent advice conflicts use `feedback_revision_conflict`.

## Long-term and daily plans (schema 4)

The primary workflow uses a versioned long-term plan and a dated daily execution plan. Weekly plans below remain a compatibility API and history view. The main agent coordinates `TrainingPlannerAgent` and `NutritionPlannerAgent`; local tools validate and persist all progress, restrictions, versions, and calculations.

- `GET /api/planning/state?date=YYYY-MM-DD`: read-only `{long_term_plans, daily_plans, profile_version, today}`. Long-term plans are newest version first; daily plans contain the latest revision per date. `today` is the current application date, independent of the selected date. Reading state never generates or revises a plan.
- `POST /api/long-term-plans`: `{start_date, cycle_labels?: [string], mode}` → draft long-term record. Default cycle is `["推", "拉", "腿", "休息"]`; accepts 1–14 nonempty labels, each at most 200 characters. Records contain `{id, version, profile_version, start_date, status, data, trace, created_at}`.
- `POST /api/long-term-plans/{id}/confirm`: no body → confirmed record; idempotent, checks the current profile version and superseding confirmed versions.
- Long-term data contains `{title, goals, cycle, nutrition, supplements?, supplement_sources?, review_after, review_rules, recovery_guidance, strategy_context, knowledge_context}`. Live plans include supplement assessments and immutable per-plan snapshots of cited approved cards; legacy plans may omit them. Each item has `consider`, `conditional`, `not_needed`, or `needs_review` priority, reasons, conditions, food alternatives, cautions and source IDs. Default candidates are creatine, fish oil, vitamin D3/K2 and magnesium glycinate, selected for the user's needs with reasons; other products require an individual need (e.g. protein powder for insufficient dietary protein). Unnecessary new products are omitted unless explicitly asked about; current products remain assessed. Cards are retrieved only when the user explicitly asks about a supplement. Uncited model advice uses empty source IDs; cited IDs must match approved cards actually returned by the tool. Content guidance is handled by the prompt, not local prose filtering.
- `POST /api/daily-plans`: `{date, conditions?: string|null, mode}` → daily record `{id, date, revision, long_term_id, profile_version, data, trace, input_fingerprint, created_at}`. Requires a confirmed long-term plan effective on that date matching the current profile. `conditions: null` retains that day's saved conditions; an empty string clears the current text but does not release previously reported injuries. Identical inputs return the existing revision, except that explicitly resubmitting a released condition records a new report even when its text is unchanged. The trace retains `conditions_recorded_at` so automatic refreshes do not create new symptom reports.
- Daily data contains `{date, conditions, cycle_index, training, decision, nutrition, water, completed_meals, training_completed, recovery_guidance, review_suggestions}`. Water is `{base_ml, note}`. Training uses the cycle-step shape. `decision` retains the action, cycle position, reasons, questions, provider metadata and persistent restrictions. Missing training completion remains `null`. Nutrition review evidence is saved in `trace.nutrition_review`; any suggested calorie change is advisory only and never mutates the confirmed long-term targets.
- `POST /api/daily-plans/{id}/meals/complete`: `{meal, expected_revision}` → new daily revision with that meal completed. Only a meal in the current saved plan can be completed. Subsequent generation preserves its original food/portion snapshot; completed training is also preserved when confirmed by feedback.
- `POST /api/daily-plans/{id}/restrictions/release`: `{area, expected_revision, confirmation_text}` → new daily revision with an explicit release event and audit information. Confirmation text must be 5–1000 characters. The operation records the user's recovery statement, does not make a medical judgment, and does not automatically regenerate training. Subsequent evaluation respects the release; newly reported injury can activate a restriction again.
- Progress defaults to deferring unfinished training. Confirmed completion advances the cycle; explicit skip advances without creating a catch-up task. Fatigue, injury, equipment and time can cause deferral, skip, reduction, substitution or pause. Restrictions persist across days and long-term versions until explicitly released; injury checks include supporting joints.
- Mutations compare profile, effective long-term plan, confirmed feedback and daily snapshots transactionally; stale revisions/dependencies return `409`. Failed live training runs return an explicit error without saving a local substitute; models cannot move progress directly or clear injury restrictions.

The client reads an existing **today** plan on opening the daily view, and can generate it automatically only if no plan for today exists. Saving feedback reloads the displayed plans without regenerating today; the model's explicitly scoped decision handles future adjustments. It does not run a background scheduler. Viewing history or a future date only reads; explicit generation or a feedback decision is required to write those dates. Long-term targets change only after a new long-term draft is confirmed. Daily nutrition retains the confirmed long-term energy target rather than cutting calories automatically after a missed workout. The legacy numeric nutrition review requires at least two weigh-ins in each half of a 14-day window and four explicit diet-adherence records at >=75% adherence; recommendations are small, evidence-backed and user-confirmed through a new long-term plan.

## Weekly plans (compatibility)

- `POST /api/plans`: `{start_date: "YYYY-MM-DD", mode?: "live"}` → model-generated plan record. Missing API configuration returns 503; `demo` is rejected.
- `POST /api/plans/{id}/confirm`: no body → confirmed record; repeat confirmation is idempotent. If profile changed since generation, returns 409.
- Plan record: `{id, version, profile_version, status: "draft"|"confirmed", created_at, data, trace, mode}`.
- Plan data: `{title, summary, days, nutrition, questions, source_ids, strategy_context, knowledge_context}`.
- `strategy_context` is a list of persisted baseline snapshots: `{id, title, summary, action_rules, knowledge_item_ids}`. Plan generation selects every reviewed baseline strategy applicable to the profile's primary goal; it does not retrieve a small top-k subset.
- `knowledge_context` is a list of persisted source snapshots: `{id, title, excerpt, creator_name, collection, videos, matched_issues}`. Each `videos` entry is `{bvid, title, url, published_at}`. For plans it contains the approved knowledge referenced by all selected baseline strategies, subject to the data model's atomic persistence limits.
- Day: `{day_index: 0..6, label, kind: "training"|"rest", exercises, estimated_minutes}`.
- Exercise: `{exercise_id, sets, reps_min, reps_max, rest_seconds, name}`. The server enriches names and computes duration. Rest days have no exercises and zero duration.
- Nutrition: `{approach, daily_targets, meal_options: [{meal, suggestions, estimated_kcal, protein_g, fat_g, carbs_g, estimated_cost_cny, alternatives}], budget_note, questions}`. Targets and meal values are local starting estimates with explicit assumptions; cafeteria and takeaway prices/portion sizes remain uncertain.
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

## Nutrition planning

- `POST /api/nutrition/plan`: `{date, feedback_id?, meal?, conditions?, available_foods?, desired_foods?, already_eaten?, budget_amount?, mode}` -> `{profile_version, data}`. The local nutrition planner calculates an initial calorie/protein/fat/carbohydrate target, then returns concrete foods, portions, estimated macros, cost and alternatives. If `feedback_id` is supplied it must be a confirmed feedback row; its meal conditions and foods fill missing request fields. The request is read/preview only and never changes the profile.
- `POST /api/nutrition/memory/preview`: `{text}` -> explicit allergy/intolerance/disliked-food candidates, each retaining the source text and `requires_confirmation: true`. The endpoint never writes profile memory. In the profile UI, users can select candidates to populate the editable profile form; the candidate only becomes persistent after the user saves that profile.
- Feedback data may include `meal_to_plan`, `meal_conditions`, `available_foods`, `desired_foods`, and `already_eaten`. These are user-confirmed facts for that record; they do not become long-term preferences automatically.

## Knowledge availability and compatibility

Knowledge loading is optional context enrichment. If approved knowledge or the reviewed strategy artifact is missing, unreadable, or invalid, model planning can proceed without that context and reports `trace.knowledge_status: "unavailable"`; it never substitutes a locally generated plan. Storage failures, request validation failures, and unexpected programming errors are not converted to a knowledge fallback.

## Personal History

- `GET /api/history/recent?days={7|14|21}&end_date=YYYY-MM-DD&issue=<optional>&metric=<optional>` returns confirmed feedback in an inclusive calendar window, newest first. Supported metric filters are `sleep_hours`, `weight_kg`, `fatigue`, `training_completed`, and `diet_followed_plan`; a metric filter only returns records with an explicit non-null value.
- `GET /api/history/trends?days={7|14|21}&end_date=YYYY-MM-DD` merges confirmed records by date before computing independent metric samples. `record_count` counts reporting days, `raw_record_count` counts source records, and `sample_unit` is `day`. Each scalar uses its last actual field revision; missing/null/empty fields do not erase known facts. Numeric fields include average/minimum/maximum/range; weight also includes chronological change when at least two distinct dates exist. A single sampled day is marked `insufficient_data`.
- `GET /api/history/similar/{feedback_id}?limit=3` ranks confirmed historical feedback by shared issue and explicit categorical signals. It excludes the current record and may return a previous advice summary, but never an inferred outcome.
- Unsupported windows, metrics, or limits return `400` with `detail.code: "history_query_invalid"`.

Records created before this contract may omit `strategy_context`, `knowledge_context`, `source_ids`, or the new trace fields. Clients must treat absent nested lists and trace lists as empty and an absent knowledge status as unknown; no database migration is required to read those records safely.

## Interface requirements

Five tabs: 概览, 我的档案, 长期计划, 当天计划, 每日反馈 (history on daily feedback). Weekly history remains in a collapsed compatibility section on the long-term page. Profile form must retain unknown optional fields and support at least the existing sample fields, session duration, dietary restrictions and recovery. Gym equipment values: `dumbbell`, `barbell`, `machine`, `bodyweight`; null means unspecified, not empty set. Primary goals: `fat_loss`, `muscle_gain`, `general_health`. Health/allergy status: `none_known_self_reported`, `unknown`, `has_conditions` / `has_allergies` with a separate detail string if needed.

Do not hard-code user profile numbers into tracked HTML/JS; obtain them only when the user clicks import. Use an honest mode selector, visible save confirmations, reversible draft edits, loading buttons, dates, friendly errors and source links where supported. Source IDs are resolved using `GET /api/sources` → list of `{id, title, url, note}`. Exercise IDs resolved server-side. Treat all generated content as untrusted text, never raw HTML.
# P1/P2 additions (2026-10-11)

`GET /api/state` returns `available_modes`, `model_configured`, optional configured `model`, and `plan_changes`. All generation uses the configured provider; provider errors return a sanitized explicit error and never substitute local generated content.

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

## Model-led training requests and errors (phase 1)

Long-term generation additionally accepts optional conditions (up to 10000 characters). Both long-term and daily generation accept expected_snapshot_token (64 hexadecimal characters). Submit the token from a needs-input response together with new conditions to establish a fresh run. Input changes return 409; no hidden model conversation is resumed. The model produces the complete cycle candidate.

Success retains existing record shapes. Long-term data adds summary, assumptions and training_questions. Long-term generation also runs SupplementPlannerAgent after nutrition planning; errors or questions prevent saving a partial plan. Its `supplement_provider` trace includes knowledge status and exact source snapshots. Daily decision adds model explanations, assumptions, optional scheduled_time and load_description. Trace records training_source, nutrition_source, mode, provider calls/usage, tool sequence, revisions, validation errors and retrieved source snapshots.

Errors return detail: {code, status, run_id, message, questions, retryable, snapshot_token}. Needs information returns 422 (planning_needs_input, retryable=false); provider/output failures return 502; timeouts return 504. Stale inputs remain 409. Failures never append a formal plan. Users can manually retry transient provider failures or answer questions through conditions.

Legacy feedback confirmation returns `planning_update: {status: "none"}` and does not regenerate a daily plan. The UI shows model-planning failure separately, preserves the saved response and offers explicit retry. Generation failures are never replaced by local generated output.

## Readable plan streaming (2026-10-21)

`POST /api/long-term-plans/stream` and `POST /api/daily-plans/stream` accept the
same bodies as the JSON endpoints and return `text/event-stream`. The UI uses
these routes for live generation. Events are `phase: {message}`, `status:
{message}`, `text: {text}`, `result: <saved plan record>`, or `error: {status,
detail}`. `result` and `error` are terminal. HTTP request validation and disabled
live mode still return ordinary HTTP errors before streaming begins. Failures
within a stream carry the original HTTP status and planning detail inside the
error event, including needs-input questions and snapshot tokens. Clients must
require a terminal result, retain incomplete text as a draft, and avoid automatic
POST retries when a connection drops.

Each live training/nutrition agent first streams readable draft text and then
extracts its structured candidate from that exact draft. Preview calls count
towards the existing call/time budgets and usage totals. Validation may revise
the draft; only the completed saved result has plan authority. This adds a model
call per active agent and can increase total latency and token usage while making
content readable sooner. SSE includes keepalives; disconnect aborts at the next
event/phase boundary. A persistence operation already in progress may complete,
so inspect planning history before retrying after a dropped connection.

## History and memory reliability (2026-10-21)

`FeedbackData.exercise_results[]` remains compatible with legacy action-level
`weight_kg` and `rpe`. Optional fields now include `exercise_name`, `session_id`,
`sets`, `form_notes`, and `goal_completed`. Each set requires positive strict
integer `reps`, with optional actual `weight_kg`, `rpe` (0.5 increments), and
strict boolean `completed`. Unknown values remain null. Model-extracted values
must be grounded in the action's actual report; planned performance is not an
actual result. Omitted session IDs group the same action on the same date.
CSV stores the full list as JSON in `exercise_results`.

The model tool `get_training_history` accepts `days: 7|14|21`, optional
`exercise_id`, and `session_limit: 1..8` (default 3 per exercise). Its
`exercise_history` includes sessions, actual total reps, known external load
volume, volume completeness, and contributing feedback IDs/revisions. Summaries
are byte bounded and expose truncation; full source records remain stored.

`GET /api/personal-memory` adds event dates, evidence quotes, expiry,
supersession and verification metadata. Context includes `expired_keys`,
`future_keys`, `legacy_keys`, `stale_keys` and `superseded_keys`. New entries
require a quote for each `(feedback_id, revision)` source. Facts default to a
14-day lifetime and patterns to 21 days; patterns require two distinct source
dates. Compression cannot renew those dates or manufacture confirmation.
Changed source revisions suspend ordinary entries; unresolved restrictions
remain active with `source_changed_recheck` until an explicit targeted release.

| Endpoint | Request and result |
| --- | --- |
| `POST /api/feedback/{id}/facts/confirm` | `{expected_revision, training_completed?: boolean, diet_followed_plan?: boolean}`; at least one strict boolean. Saves a feedback revision and returns the feedback view, preserving raw text. Earlier coaching becomes stale and requires explicit reanalysis; does not generate a plan. |
| `POST /api/personal-memory/{key}/confirm` | `{expected_version, action: "confirm"\|"retire"}`; only active preferences. Writes an auditable user statement plus a memory version and returns current memory context. Restrictions use their explicit release flow. |

Both operations check the expected revision/version inside the write
transaction; conflicts return 409. Feedback views expose
`coaching.fact_status.ignored_fields` and completion fields with
`status: confirmed|needs_confirmation|unknown` plus nullable `value`.
An invalid optional fact is discarded individually; valid sibling fields can
still be saved. See [history and memory behavior](history-and-memory.md) for
calendar windows, user-visible confirmation, compatibility and limitations.
