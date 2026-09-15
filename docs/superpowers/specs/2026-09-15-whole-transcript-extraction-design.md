# 整集字幕综合抽取设计

日期：2026-09-15

## 目标

将每集视频的字幕按原始顺序拼接成连续转写文本，再让模型结合整集上下文识别 ASR 错别字并提取补剂、排名、适用场景、剂量和风险等作者观点。先用第 133 集做 v2 对照，避免直接批量消耗 token。

## 输入与上下文

输入使用现有 `*-transcript.txt`。脚本去除每行的时间戳标记，只保留字幕文本，并按顺序用换行拼接。标题和集数作为定位信息一并提供。模型提示明确：转写可能有错别字，可以根据上下文纠正明显术语，但不能使用外部知识补齐，也不能把作者观点升级为医学事实。

## 输出

每个条目保留 `ingredient`、`raw_name`、`name_confidence`、`author_rank`、`scope`、`claim`、`conditions`、`dose_as_stated`、`risks_as_stated`、`quote`、`uncertainties`、`source_type` 和 `review_status`。v2 不要求精确时间戳；`quote` 用于从整集转写中人工回看。来源集数、标题和视频 URL 由脚本补充。无法确认的标准名称填 `null`，并写明不确定原因。

## 排名与去重

不同场景的排名分别保存，不合并成一个总排名。同一集内重复表达的观点只保留一个条目；跨视频的去重和冲突整理留给后续审核阶段。

## 版本与账本

v2 输出使用独立文件名，例如 `133-v2-request.json`、`133-v2-api-response.json` 和 `133-v2-extracted.json`，不覆盖旧结果。每次请求在 `usage.jsonl` 中记录 `pipeline_version=whole_transcript_v2`。模型供应商返回的 token usage 是唯一计量依据；没有返回 usage 的请求单独标记为未知。未审核条目不进入正式知识索引。

## 校验与验收

脚本验证 JSON 结构、集数、必需字段、`review_status=pending` 和 `source_type=creator_opinion`。另外检查每个条目有原词或标准名称、有简短引句，并输出条目数、不确定名称数和 token 用量。第 133 集 v2 完成后，与旧版条目数量、名称确认情况和用量并列报告。
