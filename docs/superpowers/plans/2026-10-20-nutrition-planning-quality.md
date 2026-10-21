# 饮食规划质量与反馈校准实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提升增肌、减脂与维持餐单的可执行性，并用连续反馈提供保守、可解释的营养复盘建议。

**Architecture:** 保留 `NutritionPlannerAgent` 的本地目标估算和硬性饮食限制。改进餐食模板使具体份量与餐项宏量估算一致；从现有14天历史趋势推导复盘建议，只展示建议而不改已确认长期目标。

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, vanilla JavaScript, pytest, Node test runner.

---

### Task 1: 明确餐食份量与目标计算的一致性

**Files:**
- Modify: `fitness/nutrition_agent.py`
- Test: `tests/test_nutrition.py`

- [x] 为增肌、减脂、维持目标分别测试目标方向与宏量热量核算。
- [x] 为标准日餐单测试所有餐项估算总和等于每日目标，建议包含有对应份量的食物以及熟重/份数标记。
- [x] 运行新增测试确认失败，再实现一个集中式餐项分配函数：按早餐、午餐、晚餐、加餐的明确比例分配每日宏量目标，并以蛋白质/脂肪/碳水4/9/4 kcal 校准热量。
- [x] 保持已吃食物不引发补偿性少吃，休息日不改长期能量目标，过敏/素食/纯素限制仍优先。
- [x] 运行 `pytest tests/test_nutrition.py -q`。

### Task 2: 根据连续体重与执行反馈生成复盘建议

**Files:**
- Modify: `fitness/daily_planning.py`
- Test: `tests/test_daily_plans.py`

- [x] 测试数据样本不足、低于4次称重、执行度未知及单日波动时不生成热量调整建议。
- [x] 测试减脂停滞、减脂下降过快伴随疲劳、增肌未增重、增肌增重过快且执行稳定时的有依据建议。
- [x] 实现纯函数消费截至规划日的反馈记录：至少14天窗口、至少4个体重样本、至少4条明确执行记录；按前后7天均值判断趋势，输出证据和约两周复核提示。
- [x] 建议每次只提出约100至200 kcal/日内的小步调整，不改写长期计划中的 `daily_targets`。
- [x] 运行 `pytest tests/test_daily_plans.py -q`。

### Task 3: 将复盘建议呈现给用户并保留来源说明

**Files:**
- Modify: `fitness/daily_planning.py`
- Modify: `fitness/static/daily-plans.js`
- Modify: `fitness/static/styles.css`
- Test: `tests/frontend/daily-plans.test.cjs`

- [x] 结构化营养复盘证据存入 trace，旧日计划缺字段时正常显示。
- [x] 在当天复盘区域展示建议、采用的趋势证据和不确定性；没有足够证据时不显示热量调整指令。
- [x] 添加前端回归测试验证建议内容按文本安全渲染且旧计划兼容。
- [x] 运行 `node tests/frontend/daily-plans.test.cjs`。

### Task 4: 回归与文档

**Files:**
- Modify: `README.md`
- Modify: `docs/api-contract.md`
- Modify: `docs/work-log.md`

- [x] 说明餐食营养和价格为估算，趋势建议需要持续记录并由用户确认新长期计划后才生效。
- [x] 运行 `.venv\Scripts\python.exe -m pytest -q`、`.venv\Scripts\ruff.exe check fitness tests`、全部 `tests/frontend/*.test.cjs` 和 `git diff --check`。
- [x] 查看差异，确认未修改既有用户数据或覆盖其他未提交改动。
