# RAG Plan And Feedback Integration Design

## Goal

Use the complete approved local knowledge base in two main user workflows: comprehensive baseline plan generation and targeted adjustments after confirmed daily feedback. Every use of knowledge must be visible, source-traceable, deterministic in demo mode, and safe when retrieval returns nothing.

## Scope

- Consolidate all 74 currently approved knowledge records into an auditable baseline strategy library.
- Generate a comprehensive weekly plan from every baseline strategy module relevant to the saved profile.
- Retrieve focused approved knowledge separately for each issue detected in daily feedback.
- Store the strategy and citation snapshots used for every generated plan or advice.
- Show plan foundations, adjustment reasons, and source video links in the existing plan and feedback views.
- Keep the standalone knowledge search and review workflows.

This iteration does not add embeddings, a vector database, an external model, individualized supplement dosages, diagnosis, or automatic medical decisions.

## Chosen Architecture

The knowledge workflow has two layers with different jobs.

### Layer 1: Baseline strategy library

All approved knowledge cards are assigned to one or more structured strategy modules. The modules synthesize overlapping cards once, retain disagreements and limitations, and provide stable inputs for comprehensive planning.

The initial modules are:

1. Fat-loss targets and energy balance.
2. Diet structure and protein planning.
3. Resistance training and strength retention.
4. Cardio and daily activity.
5. Sleep, fatigue, and recovery.
6. Supplement priority and safety.
7. Monitoring, plateaus, and adjustment rules.

The strategy library provides coverage without injecting all 74 raw natural-language claims into every request.

### Layer 2: Issue-level retrieval

Daily feedback is split into independent issues such as short sleep, training fatigue, weight plateau, diet adherence, or a named supplement. Each issue gets a focused search over the approved manifest. Results are merged and deduplicated after retrieval.

The limit of three to five cards applies to one issue, not to the whole feedback or the whole plan. A multi-issue feedback may use more than five cards in total.

`KnowledgeContextService` owns strategy selection, issue extraction, focused retrieval, deduplication, and citation shaping. The FastAPI layer asks this service for context before calling `DemoAgent`. The agent receives explicit context values and does not read knowledge files directly.

This boundary keeps the system independently testable and allows keyword search to be replaced by embeddings later without changing plan, feedback, storage, or frontend contracts.

## Baseline Strategy Data

Create `data/knowledge/baseline-strategies.json` as a reviewable generated artifact. Each strategy contains:

```text
id
domain
title
summary
action_rules[]
applicability[]
limitations[]
safety_boundary
knowledge_item_ids[]
```

Every approved item must be assigned to at least one module or explicitly marked `reference_only` with a reason. Validation fails if an approved item is silently omitted or if a referenced item is missing from the manifest.

Repeated claims are summarized once. Conflicting claims remain visible in `limitations` and cannot become automatic action rules until resolved. Creator opinions keep their original evidence labels and are not upgraded to guidelines.

The library is regenerated deliberately after knowledge publication and reviewed as a versioned artifact. It is not silently regenerated during a user request.

## Comprehensive Plan Inputs

The service selects strategy modules from saved profile facts:

- Primary goal: fat loss, muscle gain, or general health.
- Training availability, experience, equipment, and gym access.
- Meal source, food budget, dietary restrictions, and allergies.
- Current supplements when provided.
- Usual sleep duration and schedule when provided.

A fat-loss plan normally uses all seven modules because training, diet, sleep, supplements, monitoring, and energy balance interact. A narrower goal may omit modules only when they have no applicable rule; the trace records which modules were selected and why.

The plan is built from structured strategy rules plus program-owned calculations and safety constraints. Knowledge informs the complete plan, while program logic remains authoritative for validation, exercise availability, and unsupported personal details.

## Daily Feedback Inputs

Issue extraction uses:

- The confirmed structured feedback.
- The original raw feedback text.
- The saved profile goal.
- Recent history when it provides an explicit repeated trend.

Examples:

- Short sleep plus fatigue becomes a sleep/recovery issue and a training-readiness issue.
- A two-week weight plateau becomes an energy-balance, adherence, and daily-activity issue.
- Strength loss becomes a resistance-training, diet, and recovery issue.
- A named supplement becomes a supplement-specific issue.

Known enum values and signals map to Chinese search terms. User-entered supplement names are retained as search terms.

## Issue-Level Retrieval And Ranking

Only `build_manifest()` output is eligible, so pending and rejected knowledge can never enter the workflow.

For each detected issue:

1. Search focused topic terms instead of the entire profile text.
2. Rank exact title matches above collection matches and generic body matches.
3. Return three cards by default.
4. Expand to at most five cards when the first three do not cover the issue's distinct subtopics.
5. Merge results from all issues by knowledge item ID while preserving which issue selected each card.

There is no whole-feedback limit of five cards. Stable item ID ordering resolves score ties. Empty retrieval for one issue is valid and does not block other issues or advice generation.

## Data Contract

Add shared models:

```text
KnowledgeVideo
  bvid (optional for legacy non-Bilibili sources)
  title
  url
  published_at

KnowledgeCitation
  id
  title
  collection
  excerpt
  creator_name
  videos[]
  matched_issues[]

StrategySnapshot
  id
  title
  summary
  action_rules[]
  knowledge_item_ids[]
```

Add `strategy_context: list[StrategySnapshot]` and `knowledge_context: list[KnowledgeCitation]` to `PlanData`. Add `knowledge_context: list[KnowledgeCitation]` to `AdviceData`.

Keep `source_ids` for compatibility and populate it with the knowledge IDs directly used in the result. Citation excerpts are bounded snapshots of approved claims and remain labeled as creator-sourced context.

The complete snapshots are stored inside the existing plan `data` or feedback `advice` JSON, so no SQLite migration is required. Existing records without the new fields remain valid through empty default lists.

## Plan Flow

1. `POST /api/plans` loads and validates the saved profile.
2. `KnowledgeContextService.for_plan(profile)` selects every applicable baseline strategy module.
3. `DemoAgent.generate_plan(profile, start_date, strategies)` generates the rule-based plan using the complete selected strategy set.
4. The plan stores strategy snapshots and the knowledge IDs supporting those strategies.
5. The storage layer saves the complete plan JSON unchanged.
6. The frontend renders a concise `方案依据` section with expandable modules and underlying knowledge sources.

Strategy rules may enrich the plan summary, nutrition approach, recovery instructions, monitoring instructions, and supplement priority. They do not bypass model validation or create individualized supplement doses or medical conclusions.

## Feedback Flow

1. The user confirms parsed feedback.
2. `POST /api/feedback/{id}/advice` loads the confirmed record, raw text, profile, and relevant history.
3. `KnowledgeContextService.for_feedback(...)` identifies issues and retrieves three to five cards per issue.
4. `DemoAgent.advice(..., context)` produces rule-based suggestions and attaches citations.
5. Suggestions state which reported issue triggered an adjustment.
6. The storage layer saves advice and citation snapshots together.
7. The frontend renders `本次调整依据` beneath the advice.

The feedback workflow modifies only the affected part of the current recommendation. It does not regenerate or silently replace the complete baseline plan.

Creator statements remain labeled as reference knowledge. The agent cannot turn a general claim into an individualized dose or medical conclusion.

## API And Source Presentation

Plan and feedback endpoints keep their existing top-level response shapes. The nested `data` and `advice` objects gain the new context fields.

The frontend renders stored snapshots directly. A plan strategy displays:

- Module title and summary.
- Action rules used in the plan.
- The number of supporting knowledge cards.
- An expandable list of the underlying cards and videos.

A feedback citation displays:

- The issue that triggered retrieval.
- Knowledge title, collection, and concise excerpt.
- Creator name.
- One link for every source video.

Links must use `https:` and open with `noopener noreferrer`. All text uses `textContent`; knowledge text is never inserted as raw HTML.

The existing `GET /api/sources` endpoint remains available for legacy static sources. New snapshots do not depend on it and remain stable if the knowledge base changes later.

## Empty And Error Behavior

- No applicable plan module: generate the original rule-based section and record that no knowledge strategy applied.
- No match for a feedback issue: keep rule-based advice, display the unmatched issue, and do not fabricate a source.
- Missing or invalid knowledge files: keep the main workflow usable and record `knowledge_retrieval` as degraded in the trace.
- Invalid source URL: display citation text but omit the link.
- Knowledge updated after generation: historical plans and advice retain their stored snapshots.
- Feedback corrected after advice: existing behavior clears advice; regeneration performs fresh issue extraction and retrieval.

## Traceability

Plan traces record strategy selection:

```json
{
  "steps": ["baseline_strategy_selection", "planner"],
  "strategy_ids": ["fat-loss-energy", "strength-retention"],
  "knowledge_item_ids": ["mvp-diet_fat_loss-005"],
  "knowledge_status": "ok"
}
```

Advice traces record issue-level retrieval:

```json
{
  "steps": ["issue_extraction", "knowledge_retrieval", "advisor"],
  "issues": ["short_sleep", "training_fatigue"],
  "knowledge_query_terms": ["睡眠", "恢复", "疲劳"],
  "knowledge_item_ids": ["mvp-sleep_recovery-005"],
  "knowledge_status": "ok"
}
```

When knowledge access degrades, `knowledge_status` is `unavailable`, IDs are empty, and the core workflow still completes.

## Frontend Behavior

- Plans show `方案依据`, grouped by baseline strategy module.
- Feedback advice shows `本次调整依据`, grouped by detected issue.
- Sections are concise by default and can expand to all supporting knowledge cards and source videos.
- Empty context shows `本次未采用知识库内容` instead of an empty disclosure.
- Historical records render their saved snapshots.
- Citation text wraps on mobile and source links do not resize the surrounding layout.

## Testing

### Strategy validation tests

- Every approved manifest item is assigned or explicitly marked `reference_only`.
- Strategy references resolve to approved manifest IDs.
- Conflicting or limited claims remain visible and do not become automatic rules.
- Strategy selection returns all modules applicable to the fat-loss profile.

### Retrieval unit tests

- Feedback facts and raw text produce stable issue and topic terms.
- Retrieval consumes only the approved manifest.
- Each issue retrieves three cards by default and at most five when broader coverage is required.
- Multi-issue feedback can return more than five total cards.
- Merging deduplicates cards while retaining all matched issues.
- Empty or invalid knowledge roots degrade without blocking generation.
- Citation snapshots retain every source video.

### API tests

- A generated fat-loss plan contains all applicable strategy snapshots and trace IDs.
- Confirmed feedback about short sleep contains sleep/recovery citations.
- Multi-issue feedback contains citations across the relevant issues.
- No-match requests still return valid plans and advice.
- Correcting feedback clears old advice and fresh generation retrieves again.

### Frontend tests

- Plan strategy sections render module summaries and expandable sources.
- Feedback citation sections render safe text and valid video links.
- Empty context renders the no-knowledge message.
- Legacy records without the new fields still render.

### End-to-end verification

- Generate a plan from the existing local fat-loss profile and observe all seven applicable strategy domains.
- Confirm feedback mentioning short sleep and training fatigue and observe both issue groups.
- Confirm every displayed knowledge ID exists in the 74-item approved manifest.
- Verify desktop and mobile layouts and check for browser console errors.

## Acceptance Criteria

- Every approved knowledge item is represented in the baseline strategy library or explicitly documented as reference-only.
- A comprehensive plan uses every applicable strategy module instead of an arbitrary top-five card list.
- Daily advice retrieves three to five cards per detected issue and may use more than five in total.
- Every knowledge-derived statement is visible with its source video link.
- Pending and rejected knowledge cannot be used.
- Existing saved records remain readable.
- Knowledge failure never blocks core plan or feedback workflows.
- No creator claim silently changes exercise prescription, supplement dose, or medical guidance.
- No external model API is called in demo mode.
