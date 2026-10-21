# 长期计划与当天计划实施计划

> 使用 superpowers:subagent-driven-development 执行，并在当前会话完成集成及复核。用户已确认设计与实施。

**Goal:** 将产品入口改成长期计划与根据反馈更新的当天计划，支持训练循环及训练规划模块。

**Architecture:** 独立训练决策模块，SQLite 新增版本化长期和当天记录；FitnessAgent 协调训练和饮食。新页面使用新 API，旧接口和记录兼容保留。

**Tech Stack:** Python/FastAPI/Pydantic/SQLite、原生 JavaScript、pytest/node:test。

## Task 1：训练决策（独立代理）
- [x] 在 tests/test_training_agent.py 先覆盖练三休一、顺延、伤痛限制、显式跳过、缺失反馈和模型非法决策，运行失败用例。
- [x] 新建 fitness/training_agent.py，提供 build_cycle(profile, labels)、plan_day(profile, cycle, cycle_index, day, history, restrictions, conditions, mode)，输出受校验的决策及来源。
- [x] 运行训练用例并检查无模型时仍能工作。

## Task 2：存储和主流程
- [x] 新增 tests/test_daily_plans.py，验证长期确认、跨七天循环、完成后推进、重复生成幂等、版本冲突、已完成餐次和旧数据迁移。
- [x] 新增 fitness/daily_models.py、fitness/plan_store.py、fitness/daily_planning.py；storage schema 升级增加新记录，主 Agent 提供两个规划入口。
- [x] 在 main.py 暴露长期生成/确认、当天生成/查询/完成餐次 API，确认反馈后刷新当天（不得改写已完成项目）。

## Task 3：界面
- [x] 编写前端渲染与页面契约测试，验证长期/当天入口、三餐、水量、原因和安全文本渲染。
- [x] 替换默认周计划界面，支持训练循环、当天条件、完成餐次和历史，保留旧记录入口。

## Task 4：验证与文档
- [x] Python 全量、node --test、Ruff、compileall、node --check、git diff --check。
- [x] 临时数据库 walkthrough 验证循环推进、伤痛跨天、已执行保留；独立复核规格和实现。
- [x] 同步 README/API/work-log，报告实际验证及限制。

验收补充：2026-10-20 全量 Python 547 passed（2 条依赖弃用警告）、前端 32 passed；Ruff、Python 编译、两个页面脚本语法和差异检查通过。新增状态回归覆盖同日重复报告已解除症状、清空条件后伤情跨天保留、无关饮食反馈保留训练意图，以及无关字段编辑不重新激活旧伤情。独立复审 82 项定向测试和手动状态转换通过，原四项问题未再复现。
