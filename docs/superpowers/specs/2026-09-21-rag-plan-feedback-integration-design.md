# RAG Plan And Feedback Integration Design

## Goal

Use the 74 approved local knowledge records in the two main user workflows: weekly plan generation and advice after a confirmed daily feedback. Every use of knowledge must be visible, source-traceable, deterministic in demo mode, and safe when retrieval returns nothing.

## Scope

- Retrieve approved knowledge when generating a weekly plan.
- Retrieve approved knowledge when generating advice for confirmed feedback.
- Store a citation snapshot with each generated plan or advice.
- Show the retrieved knowledge and its Bilibili source links in the existing plan and feedback views.
- Keep the current standalone knowledge search and review workflows.

This iteration does not add embeddings, a vector database, an external model, individualized supplement dosages, diagnosis, or automatic plan mutation based on creator claims.

## Chosen Approach

Use deterministic topic extraction plus the existing approved manifest search.

A new `KnowledgeContextService` owns query construction, retrieval, collection balancing, deduplication, and citation shaping. The FastAPI layer asks this service for context before calling `DemoAgent`. The agent remains responsible for plan and advice wording and receives an explicit context value rather than reading files itself.

This boundary keeps retrieval independently testable and allows keyword search to be replaced by embeddings later without changing the plan, feedback, storage, or frontend contracts.

## Retrieval Inputs

### Weekly plan

The service derives topics from saved profile facts:

- Primary goal: fat loss, muscle gain, or general health.
- Training availability, experience, equipment, and gym access.
- Meal source, food budget, dietary restrictions, and allergies.
- Current supplements when provided.
- Usual sleep duration and schedule when provided.

Known enum values map to Chinese knowledge terms. For example, `fat_loss` contributes terms such as `减脂`, `热量缺口`, and `力量保持`; gym training contributes `训练`; meal constraints contribute `饮食`; and short sleep contributes `睡眠` and `恢复`.

### Daily feedback

The service derives topics from:

- The confirmed structured feedback.
- The original raw feedback text.
- The saved profile goal.
- Recent history only when it contributes an explicit repeated signal.

Training completion or fatigue contributes training/recovery terms. Food text contributes diet terms. Reported sleep contributes sleep terms. Weight and fat-loss goals contribute fat-loss terms. Supplement names present in the raw text are retained as search terms.

## Retrieval And Ranking

Only `build_manifest()` output is eligible, so pending and rejected knowledge can never enter the workflow.

The service performs focused searches per topic instead of concatenating the entire profile into one query. Results are merged by knowledge item ID. Repeated hits increase rank. Exact title matches and collection matches rank above generic body matches. Stable item ID ordering resolves ties.

Plan retrieval returns at most five records, with collection diversity when matches exist:

- Up to two diet/fat-loss records.
- Up to two training or sleep/recovery records.
- Up to one supplement record unless the profile explicitly lists supplements.

Feedback retrieval returns at most four records and favors the signals present in that feedback. Empty retrieval is valid and must not prevent plan or advice generation.

## Data Contract

Add a shared `KnowledgeCitation` model containing:

```text
id
title
collection
excerpt
creator_name
videos[]: {bvid, title, url, published_at}
```

`excerpt` is a bounded snapshot of the approved claim. It is displayed as creator-sourced reference context and is not rewritten as medical fact.

Add `knowledge_context: list[KnowledgeCitation]` to both `PlanData` and `AdviceData`. Keep `source_ids` for compatibility and populate it with the selected knowledge item IDs. The full citation snapshot is stored inside the existing plan `data` or feedback `advice` JSON, so no SQLite migration is required.

Existing records without `knowledge_context` remain valid through an empty default list.

## Plan Flow

1. `POST /api/plans` loads and validates the saved profile.
2. `KnowledgeContextService.for_plan(profile)` retrieves approved context.
3. `DemoAgent.generate_plan(profile, start_date, context)` generates the existing rule-based plan.
4. The plan includes selected knowledge IDs and citation snapshots.
5. The storage layer saves the complete plan JSON unchanged.
6. The frontend renders a collapsed `参考知识` section beneath the plan.

Retrieved knowledge may add a bounded explanatory note to the plan summary or nutrition approach. It does not change exercise sets, repetitions, session count, supplement dosage, or health restrictions in this iteration.

## Feedback Flow

1. The user confirms parsed feedback as today.
2. `POST /api/feedback/{id}/advice` loads the confirmed record and profile.
3. `KnowledgeContextService.for_feedback(profile, feedback, raw_text, history)` retrieves approved context.
4. `DemoAgent.advice(..., context)` produces the existing rule-based suggestions and attaches citations.
5. At most one short `知识库参考` suggestion may be derived from a retrieved excerpt when it directly matches the reported signal.
6. The storage layer saves the advice and citation snapshot together.
7. The frontend renders citations beneath the advice.

Creator statements remain labeled as reference knowledge. The agent must not convert a general claim into an individualized dose or medical conclusion.

## API And Source Presentation

Plan and feedback endpoints keep their existing top-level response shapes. The nested `data` or `advice` object gains `knowledge_context`.

The frontend renders citations directly from the stored snapshot. Each citation displays:

- Knowledge title and collection label.
- A concise excerpt.
- Creator name.
- One link for every source video in the citation.

Links must use `https:` and open with `noopener noreferrer`. All text continues to use `textContent`; no knowledge text is inserted as raw HTML.

The existing `GET /api/sources` endpoint remains available for legacy static sources. New knowledge citations do not depend on it, because the stored snapshot is complete and historically stable.

## Empty And Error Behavior

- No relevant match: generate the normal rule-based result with an empty citation list and show `本次未采用知识库内容`.
- Missing or invalid knowledge file: treat retrieval as unavailable, keep the main workflow usable, and record `knowledge_retrieval` as degraded in the trace.
- Invalid source URL: display the citation text but omit the link.
- Knowledge updated after generation: old plans and advice retain their saved citation snapshot.
- Feedback corrected after advice: existing behavior clears advice; regenerated advice performs a fresh retrieval.

## Traceability

Plan and advice traces record:

```json
{
  "steps": ["knowledge_retrieval", "planner"],
  "knowledge_query_terms": ["减脂", "训练"],
  "knowledge_item_ids": ["mvp-diet_fat_loss-005"],
  "knowledge_status": "ok"
}
```

When retrieval degrades, `knowledge_status` is `unavailable`, item IDs are empty, and the workflow still completes.

## Frontend Behavior

The existing reference section is renamed from `参考资料（预置目录，尚未进行知识检索）` to `参考知识`.

- A non-empty section shows the number of cited cards and expands to structured citation rows.
- An empty section shows a quiet inline message instead of an empty disclosure control.
- Plan and feedback history render the snapshot stored with that specific record.
- Citation text wraps on mobile and source links do not resize the surrounding layout.

## Testing

### Unit tests

- Profile facts produce stable plan topic terms.
- Feedback facts and raw text produce stable feedback topic terms.
- Retrieval excludes unapproved entries by consuming only the manifest.
- Ranking deduplicates records and respects limits and collection diversity.
- Empty or invalid knowledge roots degrade without blocking generation.
- Citation snapshots retain every source video.

### API tests

- A generated plan contains retrieved citations and trace IDs.
- Confirmed feedback advice contains relevant citations.
- No-match requests still return valid plans and advice.
- Correcting feedback clears old advice and fresh generation retrieves again.

### Frontend tests

- Citation sections render safe text and valid video links.
- Empty context renders the no-knowledge message.
- Legacy records without `knowledge_context` still render.

### End-to-end verification

- Generate a plan from the existing local fat-loss profile and observe citations from approved cards.
- Confirm feedback mentioning short sleep and observe sleep/recovery citations.
- Confirm all displayed citation IDs exist in the 74-item manifest.
- Verify desktop and mobile layouts and check for browser console errors.

## Acceptance Criteria

- Weekly plans and daily advice use approved local knowledge without external model calls.
- Every retrieved claim is visible with its source video link.
- Pending and rejected knowledge cannot be retrieved.
- Existing saved records remain readable.
- Retrieval failure never blocks core plan or feedback workflows.
- No retrieved creator claim silently changes exercise prescription, supplement dose, or medical guidance.
