# RAG Plan And Feedback Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-layer local knowledge workflow in which every approved card contributes to a reviewable baseline strategy library, comprehensive plans use all applicable strategies, and daily feedback retrieves three to five cards per detected issue.

**Architecture:** Generate seven structured baseline modules from the approved manifest and validate complete coverage. A focused `KnowledgeContextService` selects modules for plans and performs issue-level retrieval for feedback. Persist strategy and citation snapshots in the existing plan/advice JSON, then render them in the existing frontend without a database migration.

**Tech Stack:** Python 3.11, Pydantic 2, FastAPI, SQLite JSON fields, vanilla JavaScript/CSS, pytest, Node test runner.

---

## File Map

- Create `fitness/knowledge_context.py`: strategy definitions, artifact generation, strategy selection, issue extraction, focused retrieval, and citation shaping.
- Create `fitness/strategy_cli.py`: deliberately regenerate and validate `baseline-strategies.json` after knowledge publication.
- Create `data/knowledge/baseline-strategies.json`: the reviewable seven-module artifact derived from the current 74-item manifest.
- Create `tests/test_knowledge_context.py`: strategy coverage, selection, retrieval, deduplication, and degradation tests.
- Create `tests/frontend/context.test.cjs`: pure frontend citation grouping and URL validation tests.
- Modify `fitness/models.py`: add strategy/citation contracts and backward-compatible context fields.
- Modify `fitness/planning.py`: accept selected strategies and citation snapshots.
- Modify `fitness/agent.py`: pass knowledge context into planning and advice.
- Modify `fitness/main.py`: orchestrate context retrieval and persist trace details.
- Modify `fitness/static/app.js`: render plan foundations and feedback adjustment sources.
- Modify `fitness/static/styles.css`: style compact expandable context sections responsively.
- Modify `tests/test_models.py`, `tests/test_api.py`, and `docs/api-contract.md`.

---

### Task 1: Add Backward-Compatible Knowledge Context Contracts

**Files:**
- Modify: `fitness/models.py:1-145`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Add tests proving a citation retains multiple videos, a plan can carry strategies and 74 source IDs, and old payloads still default to empty context:

```python
from fitness.models import AdviceData, KnowledgeCitation, PlanData


def test_knowledge_citation_retains_all_source_videos():
    citation = KnowledgeCitation.model_validate({
        "id": "mvp-training-001",
        "title": "减脂运动选择",
        "collection": "training",
        "excerpt": "作者讨论了运动选择与总消耗。",
        "creator_name": "测试创作者",
        "videos": [
            {"bvid": "BV1", "title": "视频一", "url": "https://example.com/BV1"},
            {"bvid": "BV2", "title": "视频二", "url": "https://example.com/BV2"},
        ],
        "matched_issues": ["daily_activity"],
    })
    assert [video.bvid for video in citation.videos] == ["BV1", "BV2"]


def test_legacy_advice_defaults_to_empty_knowledge_context():
    advice = AdviceData(summary="保持观察", suggestions=["继续记录"])
    assert advice.knowledge_context == []
```

Extend the existing plan fixture to validate `strategy_context == []`, `knowledge_context == []`, and allow `source_ids` with 74 IDs.

- [ ] **Step 2: Run the focused tests and observe the expected failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_models.py -q
```

Expected: FAIL because `KnowledgeCitation`, `KnowledgeVideo`, and `StrategySnapshot` do not exist.

- [ ] **Step 3: Implement the contracts**

Add these models before `PlanData`:

```python
KnowledgeCollection = Literal["training", "fat_loss", "supplements", "sleep_recovery"]


class KnowledgeVideo(Contract):
    bvid: Short | None = None
    title: Short
    url: Text
    published_at: Short | None = None


class KnowledgeCitation(Contract):
    id: Short
    title: Short
    collection: KnowledgeCollection
    excerpt: Text
    creator_name: Short
    videos: list[KnowledgeVideo] = Field(default_factory=list, max_length=20)
    matched_issues: list[Short] = Field(default_factory=list, max_length=20)


class StrategySnapshot(Contract):
    id: Short
    title: Short
    summary: Text
    action_rules: list[Text] = Field(default_factory=list, max_length=20)
    knowledge_item_ids: list[Short] = Field(default_factory=list, max_length=100)
```

Add to `PlanData`:

```python
strategy_context: list[StrategySnapshot] = Field(default_factory=list, max_length=20)
knowledge_context: list[KnowledgeCitation] = Field(default_factory=list, max_length=100)
source_ids: list[Short] = Field(default_factory=list, max_length=100)
```

Add to `AdviceData`:

```python
knowledge_context: list[KnowledgeCitation] = Field(default_factory=list, max_length=100)
source_ids: list[Short] = Field(default_factory=list, max_length=100)
```

- [ ] **Step 4: Run model tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_models.py -q
```

Expected: all model tests PASS.

- [ ] **Step 5: Commit the contract change**

```powershell
git add fitness/models.py tests/test_models.py
git commit -m "feat: add knowledge context contracts"
```

---

### Task 2: Generate And Validate The Seven-Module Baseline Strategy Library

**Files:**
- Create: `fitness/knowledge_context.py`
- Create: `fitness/strategy_cli.py`
- Create: `tests/test_knowledge_context.py`
- Generate: `data/knowledge/baseline-strategies.json`

- [ ] **Step 1: Write failing strategy coverage tests**

Use the real manifest to require complete coverage and valid references:

```python
from pathlib import Path

from fitness.knowledge import build_manifest
from fitness.knowledge_context import build_strategy_library, validate_strategy_coverage


def test_real_manifest_is_completely_covered_by_baseline_strategies():
    root = Path(__file__).parents[1] / "data/knowledge"
    manifest = build_manifest(root)
    strategies = build_strategy_library(manifest)
    report = validate_strategy_coverage(manifest, strategies)

    assert len(manifest) == 74
    assert len(strategies) == 7
    assert report == {"approved": 74, "covered": 74, "reference_only": 0}
    assert {row["id"] for row in strategies} == {
        "fat-loss-energy",
        "diet-protein",
        "strength-retention",
        "cardio-activity",
        "sleep-recovery",
        "supplement-priority",
        "monitoring-adjustment",
    }
```

Add an isolated test where a new unknown approved ID raises `StrategyCoverageError` instead of being omitted.

- [ ] **Step 2: Run the focused test and observe the expected import failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_context.py -q
```

Expected: FAIL because `fitness.knowledge_context` does not exist.

- [ ] **Step 3: Implement explicit membership rules and strategy text**

In `fitness/knowledge_context.py`, define exact current membership sets:

```python
TRAINING_CARDIO = {f"mvp-training-{n:03d}" for n in (1, 2, 3, 4, 12)}
TRAINING_STRENGTH = {f"mvp-training-{n:03d}" for n in (4, 5, 6, 7, 8, 9, 10)}
TRAINING_ENERGY = {f"mvp-training-{n:03d}" for n in (11, 13)}
TRAINING_MONITORING = {f"mvp-training-{n:03d}" for n in (11, 12, 13)}

DIET_ENERGY = {
    f"mvp-diet_fat_loss-{n:03d}" for n in (1, 2, 3, 4, 5, 8, 10, 12, 13, 14, 16, 17)
}
DIET_STRUCTURE = {
    f"mvp-diet_fat_loss-{n:03d}" for n in (6, 7, 8, 9, 11, 13, 14, 15, 16, 18)
}
DIET_ACTIVITY = {"mvp-diet_fat_loss-017"}
DIET_MONITORING = {
    f"mvp-diet_fat_loss-{n:03d}" for n in (2, 3, 4, 7, 10, 14, 15, 16, 17)
}
```

Assign every `supplements` item to `supplement-priority`, every `sleep_recovery` item to `sleep-recovery`, and every legacy `couren-*` sleep-supplement item to both modules. Use static reviewed module summaries and rules:

```python
STRATEGY_TEXT = {
    "fat-loss-energy": {
        "title": "减脂目标与能量平衡",
        "summary": "用多周趋势评估适度热量缺口，避免把出汗或单日体重变化当作减脂结果。",
        "action_rules": [
            "采用可持续的热量缺口，并根据多周体重与执行情况调整。",
            "出现明显疲劳、恢复下降或过度节食信号时先检查缺口是否过大。",
        ],
    },
    "diet-protein": {
        "title": "饮食结构与蛋白质",
        "summary": "优先建立可持续的总摄入、蛋白质和必需脂肪来源，再处理进餐时机。",
        "action_rules": [
            "每餐优先保留可识别的蛋白质来源并记录外食中的隐藏热量。",
            "不因减脂而长期压低必需脂肪摄入。",
        ],
    },
    "strength-retention": {
        "title": "抗阻训练与力量保持",
        "summary": "减脂期保留规律抗阻训练、动作质量和可恢复的训练强度。",
        "action_rules": [
            "优先维持主要动作的技术和训练强度，再按恢复情况调整训练量。",
            "负重、间歇和动作选择必须匹配经验、器械和当日状态。",
        ],
    },
    "cardio-activity": {
        "title": "有氧与日常活动",
        "summary": "用可持续的有氧和日常活动增加总消耗，不夸大单次后燃或局部出汗。",
        "action_rules": [
            "有氧安排服从力量训练恢复和长期执行。",
            "平台期同时检查日常活动量，不只增加正式训练。",
        ],
    },
    "sleep-recovery": {
        "title": "睡眠、疲劳与恢复",
        "summary": "先处理睡眠时长、环境、咖啡因酒精和行为习惯，再考虑补充剂。",
        "action_rules": [
            "连续睡眠不足或疲劳时降低当日训练压力并观察趋势。",
            "可穿戴数据用于观察趋势，不能替代症状和专业评估。",
        ],
    },
    "supplement-priority": {
        "title": "补剂优先级与安全边界",
        "summary": "补剂是饮食、训练和睡眠之后的可选工具，应结合缺口、适用条件和产品质量。",
        "action_rules": [
            "不因视频提及就默认推荐，也不自动生成个体剂量。",
            "疾病、药物、特殊人群或高剂量场景必须转向专业评估。",
        ],
    },
    "monitoring-adjustment": {
        "title": "监测、平台期与调整",
        "summary": "结合多周体重、围度、力量、睡眠、疲劳和执行率判断是否调整。",
        "action_rules": [
            "单日波动不触发长期计划变更。",
            "先定位执行、记录、活动量和恢复问题，再改变热量或训练安排。",
        ],
    },
}
```

`build_strategy_library()` must output sorted `knowledge_item_ids`, `applicability`, `limitations`, and `safety_boundary`. `validate_strategy_coverage()` must reject missing and unknown IDs.

- [ ] **Step 4: Add the deliberate regeneration CLI**

Implement `fitness.strategy_cli` to call `build_manifest()`, build strategies, validate coverage, and write UTF-8 JSON atomically:

```python
def main() -> int:
    manifest = build_manifest(Path("data/knowledge"))
    strategies = build_strategy_library(manifest)
    report = validate_strategy_coverage(manifest, strategies)
    write_json(Path("data/knowledge/baseline-strategies.json"), {
        "version": 1,
        "coverage": report,
        "strategies": strategies,
    })
    print(f"built {len(strategies)} strategies covering {report['covered']} items")
    return 0
```

- [ ] **Step 5: Generate the artifact and run coverage tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m fitness.strategy_cli
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_context.py -q
```

Expected output includes `built 7 strategies covering 74 items`; tests PASS.

- [ ] **Step 6: Commit the strategy library**

```powershell
git add fitness/knowledge_context.py fitness/strategy_cli.py tests/test_knowledge_context.py data/knowledge/baseline-strategies.json
git commit -m "feat: build complete baseline strategy library"
```

---

### Task 3: Select Complete Plan Strategies And Retrieve Per Feedback Issue

**Files:**
- Modify: `fitness/knowledge_context.py`
- Modify: `tests/test_knowledge_context.py`

- [ ] **Step 1: Write failing plan-selection and issue-retrieval tests**

Add tests using the synthetic fat-loss profile and a small temporary manifest:

```python
def test_fat_loss_plan_selects_all_seven_strategy_modules(profile_data, real_service):
    context = real_service.for_plan(Profile.model_validate(profile_data))
    assert len(context.strategies) == 7
    assert len(context.citations) == 74
    assert context.status == "ok"


def test_multi_issue_feedback_can_use_more_than_five_cards(profile_data, issue_service):
    feedback = FeedbackData(
        date="2026-09-21",
        training_completed=True,
        sleep_hours=5.5,
        fatigue="明显疲劳",
        food_summary="食堂饮食",
    )
    context = issue_service.for_feedback(
        Profile.model_validate(profile_data),
        feedback,
        "昨晚只睡5.5小时，训练很累，食堂饮食也没记录",
        [],
    )
    assert {issue.id for issue in context.issues} >= {
        "short_sleep", "training_fatigue", "diet_adherence"
    }
    assert len(context.citations) > 5
    assert all(1 <= len(issue.knowledge_item_ids) <= 5 for issue in context.issues)
```

Add tests for deduplicating one card selected by two issues, preserving both `matched_issues`, and returning `status="unavailable"` with empty context from a missing strategy file.

- [ ] **Step 2: Run focused tests and observe missing behavior**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_context.py -q
```

Expected: new tests FAIL because `KnowledgeContextService`, `for_plan`, and `for_feedback` do not exist.

- [ ] **Step 3: Implement context result and issue types**

Use focused dataclasses that stay outside persisted API contracts:

```python
@dataclass(frozen=True)
class RetrievalIssue:
    id: str
    label: str
    terms: tuple[str, ...]
    collections: tuple[str, ...]
    knowledge_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeContextResult:
    strategies: tuple[StrategySnapshot, ...] = ()
    citations: tuple[KnowledgeCitation, ...] = ()
    issues: tuple[RetrievalIssue, ...] = ()
    query_terms: tuple[str, ...] = ()
    status: str = "ok"
```

- [ ] **Step 4: Implement deterministic strategy selection and citation shaping**

`for_plan(profile)` loads the reviewed artifact, selects all strategies whose applicability includes `all` or `goal:<primary>`, unions their IDs, and resolves each ID through `build_manifest()`. Convert sources with structured `videos`; when legacy `videos` is empty, create one fallback `KnowledgeVideo` from `video_title` and `video_url` with `bvid=None`.

- [ ] **Step 5: Implement issue extraction and focused scoring**

Create stable issue rules:

```python
if feedback.sleep_hours is not None and feedback.sleep_hours < 7:
    issues.append(issue("short_sleep", "睡眠不足", ("睡眠", "睡眠时长", "恢复"), ("sleep_recovery", "supplements")))
if feedback.fatigue:
    issues.append(issue("training_fatigue", "训练疲劳", ("疲劳", "恢复", "训练量"), ("training", "sleep_recovery")))
if feedback.food_summary or any(word in raw_text for word in ("吃", "食堂", "外卖", "饮食")):
    issues.append(issue("diet_adherence", "饮食执行", ("饮食记录", "隐藏热量", "蛋白质"), ("fat_loss",)))
if feedback.weight_kg is not None:
    issues.append(issue("weight_trend", "体重趋势", ("体重变化", "长期减脂评估"), ("fat_loss",)))
```

Detect exact approved supplement titles present in `raw_text` as `supplement_question`. Score title occurrences above text occurrences, add a preferred-collection bonus, return three per issue by default, and allow five when the issue has three or more distinct terms with matches. Merge by ID and append every selecting issue to `matched_issues`.

- [ ] **Step 6: Run context tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_context.py -q
```

Expected: all strategy and retrieval tests PASS.

- [ ] **Step 7: Commit context retrieval**

```powershell
git add fitness/knowledge_context.py tests/test_knowledge_context.py
git commit -m "feat: retrieve knowledge by feedback issue"
```

---

### Task 4: Make Demo Planning And Advice Consume Explicit Knowledge Context

**Files:**
- Modify: `fitness/planning.py`
- Modify: `fitness/agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write failing agent tests**

Test that plan context is preserved and that advice labels a directly relevant retrieved claim as a video viewpoint:

```python
def test_plan_keeps_complete_strategy_and_citation_snapshots(profile, strategy_context):
    plan = DemoAgent().generate_plan(profile, date(2026, 9, 21), strategy_context)
    assert len(plan.strategy_context) == 7
    assert len(plan.knowledge_context) == 74
    assert set(plan.source_ids) == {citation.id for citation in plan.knowledge_context}


def test_advice_uses_bounded_creator_reference(profile, feedback, feedback_context):
    advice = DemoAgent().advice(profile, feedback, [], feedback_context)
    assert advice.knowledge_context
    assert any(text.startswith("知识库参考（视频观点）：") for text in advice.suggestions)
    assert advice.source_ids == [citation.id for citation in advice.knowledge_context]
```

- [ ] **Step 2: Run tests and observe signature failures**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent.py -q
```

Expected: FAIL because the agent methods do not accept knowledge context.

- [ ] **Step 3: Extend planning without changing exercise prescriptions**

Change the signatures:

```python
def generate_plan(profile, start_date, context=None):
    context = context or KnowledgeContextResult()
    # existing schedule and nutrition construction remains program-owned
    return PlanData(
        ...,
        strategy_context=list(context.strategies),
        knowledge_context=list(context.citations),
        source_ids=[citation.id for citation in context.citations],
    )
```

Append a concise summary sentence naming the selected strategy titles. Do not change sets, repetitions, session count, or add supplement doses from retrieved claims.

- [ ] **Step 4: Extend advice with one bounded reference suggestion per issue group**

Pass `KnowledgeContextResult` to `DemoAgent.advice`. Preserve existing rule suggestions, attach all citations, and add at most one shortened excerpt per distinct issue:

```python
reference = citation.excerpt.split("。", 1)[0][:120]
suggestions.append(f"知识库参考（视频观点）：{reference}。请结合适用条件理解。")
```

Respect the existing eight-suggestion model limit by prioritizing rule-based safety suggestions before knowledge references.

- [ ] **Step 5: Run agent and existing plan tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent.py tests/test_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit agent integration**

```powershell
git add fitness/planning.py fitness/agent.py tests/test_agent.py
git commit -m "feat: apply knowledge context to plans and advice"
```

---

### Task 5: Orchestrate Retrieval And Persist Trace Details In The API

**Files:**
- Modify: `fitness/main.py:25-215`
- Modify: `tests/test_api.py`
- Modify: `docs/api-contract.md`

- [ ] **Step 1: Extend the API fixture with approved knowledge and a strategy artifact**

Create a temporary `KnowledgeContextService` in the existing `client` fixture and monkeypatch `main.knowledge_context_service`. Use at least six approved items across training, sleep, and diet so a multi-issue test can exceed five total citations.

- [ ] **Step 2: Write failing API tests**

Add assertions to the complete flow:

```python
plan = client.post("/api/plans", json={"start_date": "2026-09-21", "mode": "demo").json()
assert plan["data"]["strategy_context"]
assert plan["data"]["knowledge_context"]
assert plan["trace"]["steps"] == ["baseline_strategy_selection", "planner"]
assert plan["trace"]["knowledge_status"] == "ok"

advised = client.post(path + "/advice", json={"mode": "demo"}).json()
assert advised["advice"]["knowledge_context"]
assert "short_sleep" in advised["trace"]["issues"]
assert advised["trace"]["knowledge_item_ids"]
```

Add a second fixture with a missing strategy artifact and assert plan/advice still return 200 with `knowledge_status == "unavailable"` and empty context.

- [ ] **Step 3: Run API tests and observe missing context**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -q
```

Expected: new assertions FAIL because API routes do not invoke the context service.

- [ ] **Step 4: Initialize and call the context service**

In `fitness/main.py`:

```python
knowledge_context_service = KnowledgeContextService(
    ROOT / "data/knowledge",
    ROOT / "data/knowledge/baseline-strategies.json",
)
```

For plans, call `for_plan(profile)` before `agent.generate_plan` and save trace fields from the result. For advice, pass `row["raw_text"]` and `store.feedback()` to `for_feedback`, then pass the result into `agent.advice`.

Do not catch storage or validation errors as retrieval degradation. Only knowledge loading/validation failures should produce an unavailable context.

- [ ] **Step 5: Document the nested response fields and trace contract**

Update `docs/api-contract.md` with `strategy_context`, `knowledge_context`, issue-level retrieval semantics, fallback behavior, and the fact that existing records omit these fields safely.

- [ ] **Step 6: Run API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py tests/test_storage.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit API integration**

```powershell
git add fitness/main.py tests/test_api.py docs/api-contract.md
git commit -m "feat: integrate knowledge context into api workflows"
```

---

### Task 6: Render Plan Foundations And Feedback Adjustment Sources

**Files:**
- Modify: `fitness/static/app.js:1-1040`
- Modify: `fitness/static/styles.css`
- Create: `tests/frontend/context.test.cjs`

- [ ] **Step 1: Write failing frontend helper tests**

Export and test pure helpers:

```javascript
test('groups one citation under every matched feedback issue', () => {
  const groups = ui.groupKnowledgeByIssue([
    { id: 'a', matched_issues: ['short_sleep', 'training_fatigue'] },
    { id: 'b', matched_issues: ['short_sleep'] },
  ]);
  assert.deepEqual(groups.short_sleep.map((row) => row.id), ['a', 'b']);
  assert.deepEqual(groups.training_fatigue.map((row) => row.id), ['a']);
});

test('accepts https source videos and rejects unsafe protocols', () => {
  assert.equal(ui.safeVideoUrl('https://www.bilibili.com/video/BV1'), 'https://www.bilibili.com/video/BV1');
  assert.equal(ui.safeVideoUrl('javascript:alert(1)'), null);
});
```

Add a legacy normalization test where missing context becomes `[]`.

- [ ] **Step 2: Run frontend tests and observe missing exports**

Run:

```powershell
node --test tests/frontend/*.test.cjs
```

Expected: FAIL because the new helpers do not exist.

- [ ] **Step 3: Implement safe pure helpers**

Add and export:

```javascript
function safeVideoUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch (_) {
    return null;
  }
}

function groupKnowledgeByIssue(citations = []) {
  return citations.reduce((groups, citation) => {
    (citation.matched_issues || []).forEach((issue) => {
      (groups[issue] ||= []).push(citation);
    });
    return groups;
  }, {});
}
```

- [ ] **Step 4: Replace the legacy static-source disclosure**

Keep `sourceLinks()` for old records with static IDs. Add:

- `renderPlanFoundations(strategy_context, knowledge_context)`.
- `renderAdjustmentSources(knowledge_context)`.
- `renderKnowledgeCitation(citation)` using `textContent` and `safeVideoUrl()`.

In `renderPlan()`, append `方案依据` after nutrition. Group citations by `strategy.knowledge_item_ids`, show module summary and action rules, and put all source cards in nested disclosures.

In `renderFeedbackEditor()`, append `本次调整依据` inside the advice panel, grouped by `matched_issues`. When context is missing or empty, append `本次未采用知识库内容`.

- [ ] **Step 5: Add restrained responsive styles**

Add `.context-panel`, `.strategy-row`, `.citation-row`, `.citation-meta`, and `.source-video-list` styles. Use existing borders and colors, `overflow-wrap:anywhere`, stable spacing, and a one-column mobile layout. Do not create nested decorative cards.

- [ ] **Step 6: Run frontend and syntax tests**

Run:

```powershell
node --test tests/frontend/*.test.cjs
node --check fitness/static/app.js
```

Expected: all tests PASS and syntax check exits 0.

- [ ] **Step 7: Commit frontend integration**

```powershell
git add fitness/static/app.js fitness/static/styles.css tests/frontend/context.test.cjs
git commit -m "feat: show plan and feedback knowledge sources"
```

---

### Task 7: Full Verification And Local Browser Check

**Files:**
- Modify: `README.md`
- Verify all files above.

- [ ] **Step 1: Update local usage documentation**

Document:

- `python -m fitness.strategy_cli` after publishing approved knowledge.
- Baseline plan modules versus per-issue feedback retrieval.
- The absence of external model calls in demo mode.
- How to inspect saved plan/advice source snapshots.

- [ ] **Step 2: Regenerate both knowledge artifacts**

Run:

```powershell
.\.venv\Scripts\python.exe -m fitness.knowledge_cli
.\.venv\Scripts\python.exe -m fitness.strategy_cli
```

Expected: manifest reports 74 approved items and strategy output reports seven modules covering all 74.

- [ ] **Step 3: Run the complete automated verification suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/frontend/*.test.cjs
.\.venv\Scripts\python.exe -m ruff check fitness tests
.\.venv\Scripts\python.exe -m compileall -q fitness tests
node --check fitness/static/app.js
```

Expected: all tests pass, Ruff reports `All checks passed!`, and syntax/compile commands exit 0. Existing dependency deprecation warnings may remain but no new warnings or errors are accepted.

- [ ] **Step 4: Start the local server**

Run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn fitness.main:app --host 127.0.0.1 --port 8000
```

Use a free alternate port only if 8000 is already occupied by another process.

- [ ] **Step 5: Verify the comprehensive plan in the browser**

Using the saved local fat-loss profile:

- Generate a new plan.
- Confirm all seven strategy domains appear under `方案依据`.
- Expand at least one module and verify every displayed source link uses HTTPS.
- Verify the plan trace includes all selected strategy IDs and approved knowledge IDs.

- [ ] **Step 6: Verify issue-level feedback retrieval**

Create and confirm a feedback such as `昨晚只睡了5.5小时，今天训练很累，食堂饮食也没记录`.

- Generate advice.
- Confirm the UI shows sleep, fatigue, and diet adjustment groups.
- Confirm total citations may exceed five while each issue uses no more than five.
- Confirm correcting the feedback clears the old advice and a new advice request performs fresh retrieval.

- [ ] **Step 7: Verify responsive layout and browser health**

Check desktop and 390-by-844 mobile viewports:

- No horizontal overflow.
- Long titles and excerpts wrap.
- Nested disclosures remain readable and do not overlap plan or advice actions.
- Browser console has no errors.

- [ ] **Step 8: Commit documentation and any verification-only corrections**

```powershell
git add README.md
git commit -m "docs: explain two-layer local rag workflow"
```

Leave the verified local server running and provide the direct plan and feedback URLs.
