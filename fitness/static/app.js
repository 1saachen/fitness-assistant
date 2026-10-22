function preservedMode() {
  return 'live';
}

function renderBriefExplanation(advice = {}, trace = {}) {
  const detail = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = '为什么这样建议';
  detail.append(summary);
  normalizeContextList(advice.explanations).forEach(explanation => {
    const section = document.createElement('section');
    const label = document.createElement('strong');
    label.textContent = feedbackIssueLabel(explanation.issue);
    section.append(label);
    [...normalizeContextList(explanation.facts), explanation.rule,
      ...normalizeContextList(explanation.history)].filter(Boolean).forEach(text => {
      const p = document.createElement('p'); p.textContent = text; section.append(p);
    });
    detail.append(section);
  });
  normalizeContextList(trace.similar_history?.matches).forEach(match => {
    const p = document.createElement('p');
    p.textContent = `${match.date} 相似记录：${normalizeContextList(match.previous_suggestions).join('；') || match.previous_advice_summary || '没有保存当时建议'}。${match.outcome_notice || '不推断执行效果或因果。'}`;
    detail.append(p);
    if (match.next_observation) {
      const fact = document.createElement('p');
      fact.textContent = `随后 ${match.next_observation.date} 的明确记录：${JSON.stringify(match.next_observation.data)}`;
      detail.append(fact);
    }
  });
  return detail;
}

function fieldValue(value, type) {
  if (value === "" || value == null) return null;
  if (type === "number") return Number(value);
  if (type === "boolean") return value === "true" || value === true;
  return value;
}

function mergeFields(obj, fields) {
  const out = JSON.parse(JSON.stringify(obj));
  for (const field of fields) {
    const parts = field.path.split(".");
    let current = out;
    for (let index = 0; index < parts.length - 1; index += 1)
      current = current[parts[index]] ?? (current[parts[index]] = {});
    current[parts.at(-1)] = fieldValue(field.value, field.type);
  }
  return out;
}
function reviewLabel(status) {
  return { pending: "待审核", approved: "已批准", rejected: "已拒绝" }[status] || status;
}

function filterReviewCards(cards, filters) {
  const query = (filters.query || "").trim().toLowerCase();
  return cards.filter((card) => {
    if (filters.collection !== "all" && card.collection !== filters.collection) return false;
    if (filters.status !== "all" && card.review_status !== filters.status) return false;
    const statements = (card.creator_statement || []).map((row) => row.statement).join(" ");
    const haystack = (card.title + " " + statements).toLowerCase();
    return !query || haystack.includes(query);
  });
}

function safeVideoUrl(value) {
  if (typeof value !== "string" || !value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? value : null;
  } catch (_) {
    return null;
  }
}

function normalizeContextList(value) {
  return Array.isArray(value) ? value : [];
}

function appendKnowledgeGroup(groups, key, citation) {
  if (!Object.prototype.hasOwnProperty.call(groups, key))
    Object.defineProperty(groups, key, {
      value: [],
      enumerable: true,
      configurable: true,
      writable: true,
    });
  groups[key].push(citation);
}

function groupKnowledgeByIssue(citations = [], fallbackKey = null) {
  return normalizeContextList(citations).reduce((groups, citation) => {
    const issues = [];
    normalizeContextList(citation?.matched_issues).forEach((value) => {
      if (typeof value !== "string") return;
      const issue = value.trim();
      if (issue && !issues.includes(issue)) issues.push(issue);
    });
    if (!issues.length && typeof fallbackKey === "string" && fallbackKey.trim())
      issues.push(fallbackKey.trim());
    issues.forEach((issue) => appendKnowledgeGroup(groups, issue, citation));
    return groups;
  }, {});
}

function assignPlanKnowledge(strategies = [], citations = []) {
  const knowledgeRows = normalizeContextList(citations);
  const citationById = new Map(
    knowledgeRows
      .filter((citation) => citation && citation.id != null)
      .map((citation) => [citation.id, citation]),
  );
  const matchedIds = new Set();
  const assignedStrategies = normalizeContextList(strategies).map((strategy) => {
    const seen = new Set();
    const matched = normalizeContextList(strategy?.knowledge_item_ids).flatMap((id) => {
      const citation = citationById.get(id);
      if (!citation || seen.has(id)) return [];
      seen.add(id);
      matchedIds.add(id);
      return [citation];
    });
    return { strategy, citations: matched, supportCount: matched.length };
  });
  return {
    strategies: assignedStrategies,
    unmatched: knowledgeRows.filter(
      (citation) => citation?.id == null || !matchedIds.has(citation.id),
    ),
  };
}

const feedbackIssueLabels = {
  short_sleep: "睡眠不足",
  training_fatigue: "训练疲劳",
  training_frequency: "训练频率",
  progression: "训练进阶",
  diet: "饮食",
  diet_adherence: "饮食执行",
  daily_activity: "日常活动",
  weight_trend: "体重趋势",
  weight_plateau: "体重平台期",
  supplement_question: "补剂问题",
  other: "其他依据",
};

function feedbackIssueLabel(issue) {
  return Object.prototype.hasOwnProperty.call(feedbackIssueLabels, issue)
    ? feedbackIssueLabels[issue]
    : issue;
}

function knowledgeStatusMessage(status) {
  if (status === "unavailable")
    return "知识库当前不可用，已使用本地规则继续生成；本次没有引用知识库内容。";
  if (status === "capacity_exceeded")
    return "知识引用超过本地保存容量，已使用本地规则继续生成；本次未保存知识依据。";
  if (status === "unknown")
    return "知识库状态未知，当前结果仅使用已保存的本地规则。";
  return null;
}

function trendMetricPresentation(key, metric = {}) {
  const count = Number(metric.valid_count ?? metric.record_count ?? 0);
  const display = (value) =>
    value == null ? "暂无数据" : String(Number(value.toFixed?.(2) ?? value));
  if (key === "sleep_hours")
    return {
      label: "平均睡眠",
      value: metric.average == null ? "暂无数据" : `${display(metric.average)} 小时`,
      detail:
        count && metric.minimum != null && metric.maximum != null
          ? `${count} 条有效记录 · ${display(metric.minimum)}–${display(metric.maximum)} 小时`
          : `${count} 条有效记录`,
      insufficient: Boolean(metric.insufficient_data),
    };
  if (key === "weight_kg")
    return {
      label: "平均体重",
      value: metric.average == null ? "暂无数据" : `${display(metric.average)} kg`,
      detail: `${count} 条有效记录 · ${metric.change == null ? "变化数据不足" : `变化 ${metric.change > 0 ? "+" : ""}${display(metric.change)} kg`}`,
      insufficient: Boolean(metric.insufficient_data),
    };
  const isTraining = key === "training_completion";
  const positiveCount = Number(
    metric[isTraining ? "completed_count" : key === "diet_execution" ? "followed_count" : "reported_count"] ?? 0,
  );
  return {
    label:
      key === "training_completion"
        ? "训练完成率"
        : key === "diet_execution"
          ? "饮食执行率"
          : "疲劳记录比例",
    value: metric.rate == null ? "暂无数据" : `${Math.round(metric.rate * 100)}%`,
    detail:
      count === 0
        ? `0 条${key === "fatigue_reports" ? "确认反馈" : "明确记录"}`
        : `${positiveCount} / ${count} 条${key === "fatigue_reports" ? "确认反馈" : "明确记录"}`,
    insufficient: Boolean(metric.insufficient_data),
  };
}

function safeCitationVideos(videos = []) {
  return normalizeContextList(videos).flatMap((video) => {
    const safeUrl = safeVideoUrl(video?.url);
    return safeUrl ? [{ ...video, safeUrl }] : [];
  });
}

function textNode(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value ?? "";
  if (className) element.className = className;
  return element;
}

function renderKnowledgeCitation(citation) {
  const detail = document.createElement("details");
  detail.className = "citation-row";
  detail.append(textNode("summary", citation?.title || citation?.id || "知识来源"));
  if (citation?.excerpt)
    detail.append(textNode("p", citation.excerpt, "citation-excerpt"));
  const meta = [citation?.creator_name, citation?.collection]
    .filter((value) => typeof value === "string" && value.trim())
    .join(" · ");
  if (meta) detail.append(textNode("p", meta, "citation-meta"));
  const videos = safeCitationVideos(citation?.videos);
  if (videos.length) {
    const list = document.createElement("ul");
    list.className = "source-video-list";
    videos.forEach((video) => {
      const item = document.createElement("li");
      const link = textNode("a", video.title || video.bvid || video.safeUrl);
      link.href = video.safeUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
      if (video.published_at)
        item.append(document.createTextNode(` · ${video.published_at}`));
      list.append(item);
    });
    detail.append(list);
  }
  return detail;
}

function renderPlanFoundations(strategies, citations) {
  const panel = document.createElement("section");
  panel.className = "context-panel";
  panel.append(textNode("h3", "方案依据"));
  const strategyRows = normalizeContextList(strategies);
  const knowledgeRows = normalizeContextList(citations);
  if (!strategyRows.length && !knowledgeRows.length) {
    panel.append(textNode("p", "本次未采用知识库内容", "muted"));
    return panel;
  }
  const assignment = assignPlanKnowledge(strategyRows, knowledgeRows);
  assignment.strategies.forEach(({ strategy, citations: matched, supportCount }) => {
    const detail = document.createElement("details");
    detail.className = "strategy-row";
    detail.append(
      textNode(
        "summary",
        `${strategy?.title || strategy?.id || "策略模块"} · ${supportCount} 张支持知识卡`,
      ),
    );
    if (strategy?.summary)
      detail.append(textNode("p", strategy.summary, "strategy-summary"));
    const rules = normalizeContextList(strategy?.action_rules);
    if (rules.length) {
      detail.append(textNode("p", "执行规则", "citation-meta"));
      const list = document.createElement("ul");
      list.className = "detail-list";
      rules.forEach((rule) => list.append(textNode("li", rule)));
      detail.append(list);
    }
    if (matched.length) {
      detail.append(textNode("p", "知识来源", "citation-meta"));
      matched.forEach((citation) =>
        detail.append(renderKnowledgeCitation(citation)),
      );
    }
    panel.append(detail);
  });
  if (assignment.unmatched.length) {
    const detail = document.createElement("details");
    detail.className = "strategy-row";
    detail.append(
      textNode("summary", `其他方案依据 · ${assignment.unmatched.length} 张知识卡`),
    );
    assignment.unmatched.forEach((citation) =>
      detail.append(renderKnowledgeCitation(citation)),
    );
    panel.append(detail);
  }
  return panel;
}

function renderAdjustmentSources(citations) {
  const panel = document.createElement("section");
  panel.className = "context-panel";
  panel.append(textNode("h3", "本次调整依据"));
  const knowledgeRows = normalizeContextList(citations);
  if (!knowledgeRows.length) {
    panel.append(textNode("p", "本次未采用知识库内容", "muted"));
    return panel;
  }
  Object.entries(groupKnowledgeByIssue(knowledgeRows, "other")).forEach(
    ([issue, rows]) => {
      const group = document.createElement("section");
      group.className = "strategy-row";
      group.append(textNode("h4", feedbackIssueLabel(issue)));
      rows.forEach((citation) =>
        group.append(renderKnowledgeCitation(citation)),
      );
      panel.append(group);
    },
  );
  return panel;
}

function sourceLinks(ids = [], sources = []) {
  const container = document.createElement("details");
  container.append(
    textNode("summary", "参考资料（预置目录，尚未进行知识检索）"),
  );
  normalizeContextList(ids).forEach((id) => {
    const source = normalizeContextList(sources).find((item) => item.id === id);
    if (!source) return;
    const url = safeVideoUrl(source.url);
    if (!url) return;
    const link = textNode("a", source.title);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const row = textNode("p", "");
    row.append(link);
    container.append(row);
  });
  return container;
}

function renderPlanContextSections(planData = {}, sources = []) {
  const knowledgeRows = normalizeContextList(planData?.knowledge_context);
  const sections = [
    renderPlanFoundations(planData?.strategy_context, knowledgeRows),
  ];
  if (!knowledgeRows.length && normalizeContextList(planData?.source_ids).length)
    sections.push(sourceLinks(planData.source_ids, sources));
  return sections;
}

function renderAdviceContextSections(advice = {}, sources = []) {
  const knowledgeRows = normalizeContextList(advice?.knowledge_context);
  const sections = [renderAdjustmentSources(knowledgeRows)];
  if (!knowledgeRows.length && normalizeContextList(advice?.source_ids).length)
    sections.push(sourceLinks(advice.source_ids, sources));
  return sections;
}

if (typeof module !== "undefined")
  module.exports = {
    preservedMode,
    renderBriefExplanation,
    fieldValue,
    mergeFields,
    reviewLabel,
    filterReviewCards,
    safeVideoUrl,
    normalizeContextList,
    groupKnowledgeByIssue,
    assignPlanKnowledge,
    feedbackIssueLabel,
    knowledgeStatusMessage,
    trendMetricPresentation,
    safeCitationVideos,
    renderKnowledgeCitation,
    renderPlanFoundations,
    renderAdjustmentSources,
    sourceLinks,
    renderPlanContextSections,
    renderAdviceContextSections,
  };

if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const app = {
    profile: null,
    profileDraft: null,
    version: 0,
    plans: [],
    dailyPlans: [],
    feedback: [],
    plan: null,
    selectedFeedback: null,
    mode: null,
    knowledgeStatus: "unknown",
    feedbackDirty: false,
    feedbackReplies: new Map(),
    feedbackSubmission: null,
    sources: [],
    reviewCards: [],
    reviewCounts: { total: 0, pending: 0, approved: 0, rejected: 0 },
    selectedReviewCard: null,
    reviewFilters: { collection: "all", status: "all", query: "" },
  };
  const api = async (url, options = {}) => {
    const mutation = options.method && options.method !== "GET";
    if (mutation && app.pending) throw new Error("正在保存，请稍候再操作。");
    const controls = mutation
      ? [
          ...document.querySelectorAll(
            "main button, main input, main select, main textarea",
          ),
        ].map((el) => [el, el.disabled])
      : [];
    if (mutation) {
      app.pending = true;
      controls.forEach(([el]) => {
        el.disabled = true;
      });
    }
    try {
      const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const error = new Error(
          Array.isArray(body.detail)
            ? body.detail
                .map((issue) => `${issue.loc.slice(1).join(".")}：${issue.msg}`)
                .join("\n")
            : typeof body.detail === "string"
              ? body.detail
              : body.detail?.message || `请求失败（${response.status}）`,
        );
        error.code = body.detail?.code;
        error.retryable = body.detail?.retryable;
        throw error;
      }
      return await response.json();
    } finally {
      if (mutation) {
        app.pending = false;
        controls.forEach(([el, disabled]) => {
          el.disabled = disabled;
        });
      }
    }
  };
  const show = (message, error = false) => {
    const target = $(error ? "error" : "notice");
    const other = $(error ? "notice" : "error");
    other.hidden = true;
    target.textContent = message || "";
    target.hidden = !message;
    if (message)
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const busy = (node, on) => {
    if (!node) return;
    node.disabled = on;
    node.dataset.label ??= node.textContent;
    node.textContent = on ? "处理中…" : node.dataset.label;
  };
  const node = (tag, value, className) => {
    const el = document.createElement(tag);
    el.textContent = value ?? "";
    if (className) el.className = className;
    return el;
  };
  const action = (label, className, fn) => {
    const el = node("button", label, className || "button");
    el.type = "button";
    el.addEventListener("click", fn);
    return el;
  };
  const renderExportActions = (kind, ident = null) => {
    const wrap = document.createElement("div");
    wrap.className = "export-actions";
    const label = node("label", "导出", "export-label");
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${kind} 导出格式`);
    [
      ["json", "JSON"],
      ["csv", "CSV"],
      ["markdown", "Markdown"],
    ].forEach(([value, text]) => select.add(new Option(text, value)));
    label.append(select);
    const button = action("下载", "button secondary", () => {
      const params = new URLSearchParams({ format: select.value });
      if (ident) params.set(kind === "plan" ? "plan_id" : "feedback_id", ident);
      window.location.href = `/api/export/${kind}?${params.toString()}`;
    });
    wrap.append(label, button);
    return wrap;
  };
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const fmt = (value) => (value ? String(value).slice(0, 10) : "未记录");
  const today = () =>
    new Intl.DateTimeFormat("sv-SE", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  const base = () => ({
    schema_version: 1,
    source: "user_entered",
    profile_status: "incomplete",
    personal: {
      age_years: null,
      sex: null,
      height_cm: null,
      weight_kg: null,
      weight_measured_on: null,
      body_fat_percent: null,
      body_fat_source: null,
      body_fat_measurement_method: null,
      body_fat_measured_on: null,
    },
    goals: {
      primary: null,
      secondary: [],
      deadline_negotiable: null,
      target_date: null,
      target_weight_kg: null,
      target_body_fat_percent: null,
    },
    training: {
      experience_years: null,
      available_sessions_per_week: null,
      training_frequency: null,
      session_duration_minutes: null,
      gym_access: null,
      available_equipment: null,
      preferred_weekdays: null,
      current_routine: null,
      usual_training_time: null,
      strength_baseline: {
        squat_1rm_kg: null,
        bench_press_1rm_kg: null,
        deadlift_1rm_kg: null,
        pull_up_max_reps: null,
        recorded_on: null,
        notes: null,
      },
    },
    nutrition: {
      primary_meal_source: null,
      occasional_meal_sources: [],
      food_budget: {
        amount: null,
        currency: "CNY",
        period: null,
        approximate: true,
      },
      food_allergy_status: "unknown",
      food_allergy_details: null,
      food_intolerances: null,
      other_dietary_restrictions: null,
    },
    supplements: {
      budget_separate_from_food: true,
      budget: {
        amount: null,
        currency: "CNY",
        period: null,
        approximate: true,
      },
      current_products: null,
    },
    health: {
      exercise_limiting_conditions_status: "unknown",
      exercise_limiting_conditions_details: null,
      medications_status: "unknown",
      medications: null,
    },
    recovery: { usual_sleep_hours: null, sleep_schedule: null },
    daily_activity_level: null,
  });
  const get = (obj, path) => path.split(".").reduce((v, key) => v?.[key], obj);
  const set = (obj, path, value) => {
    const parts = path.split(".");
    let current = obj;
    parts.slice(0, -1).forEach((part) => {
      current[part] ??= {};
      current = current[part];
    });
    current[parts.at(-1)] = value;
  };
  const profileFields = [
    [
      "基本情况",
      [
        ["personal.age_years", "年龄", "number"],
        ["personal.height_cm", "身高（cm）", "number"],
        ["personal.weight_kg", "体重（kg）", "number"],
        ["personal.body_fat_percent", "体脂率（%）", "number"],
        ["personal.sex", "性别（可留空）", "text"],
        ["personal.weight_measured_on", "体重测量日期", "date"],
        ["personal.body_fat_measured_on", "体脂测量日期", "date"],
        ["personal.body_fat_measurement_method", "体脂测量方法", "text"],
      ],
    ],
    [
      "目标",
      [
        [
          "goals.primary",
          "主要目标",
          "select",
          [
            ["", "未知 / 暂不设置"],
            ["fat_loss", "减脂"],
            ["muscle_gain", "增肌"],
            ["general_health", "保持健康"],
          ],
        ],
        ["goals.target_date", "目标日期", "date"],
        ["goals.target_weight_kg", "目标体重（kg）", "number"],
        ["goals.target_body_fat_percent", "目标体脂率（%）", "number"],
        [
          "goals.secondary",
          "次要目标（逗号分隔，例如 maintain_strength 保持力量）",
          "list",
        ],
        ["goals.deadline_negotiable", "期限可协商", "boolean"],
      ],
    ],
    [
      "训练条件",
      [
        ["training.experience_years", "训练年限", "number"],
        ["training.training_frequency", "训练频率", "text"],
        ["training.session_duration_minutes", "每次时长（分钟）", "number"],
        ["training.gym_access", "有健身房", "boolean"],
        ["training.current_routine", "当前训练安排", "text"],
        ["training.usual_training_time", "通常训练时间", "text"],
        [
          "training.available_equipment",
          "可用器械（Ctrl/Command 多选，未选为未知）",
          "equipment",
          [
            ["bodyweight", "自重"],
            ["dumbbell", "哑铃"],
            ["barbell", "杠铃"],
            ["machine", "固定器械"],
          ],
        ],
      ],
    ],
    [
      "力量参考（选填）",
      [
        ["training.strength_baseline.squat_1rm_kg", "深蹲单次最大重量 / 估算1RM（kg）", "number"],
        ["training.strength_baseline.bench_press_1rm_kg", "卧推单次最大重量 / 估算1RM（kg）", "number"],
        ["training.strength_baseline.deadlift_1rm_kg", "硬拉单次最大重量 / 估算1RM（kg）", "number"],
        ["training.strength_baseline.pull_up_max_reps", "严格自重引体最大连续次数（次，做不了填0）", "number"],
        ["training.strength_baseline.recorded_on", "成绩日期（可留空）", "date"],
        ["training.strength_baseline.notes", "成绩说明（实测或估算、动作标准、不同日期等）", "text"],
      ],
    ],
    [
      "饮食与预算",
      [
        ["nutrition.primary_meal_source", "主要饮食来源", "text"],
        [
          "nutrition.occasional_meal_sources",
          "偶尔的饮食来源（逗号分隔）",
          "list",
        ],
        ["nutrition.food_budget.amount", "饮食预算（元）", "number"],
        [
          "nutrition.food_budget.period",
          "饮食预算周期",
          "select",
          [
            ["", "未知"],
            ["day", "每天"],
            ["week", "每周"],
            ["month", "每月"],
          ],
        ],
        [
          "nutrition.food_allergy_status",
          "食物过敏情况",
          "select",
          [
            ["unknown", "未知"],
            ["none_known_self_reported", "无已知过敏"],
            ["has_allergies", "有，需要说明"],
          ],
        ],
        ["nutrition.food_allergy_details", "食物过敏说明", "text"],
        ["nutrition.food_intolerances", "食物不耐受", "text"],
        ["nutrition.other_dietary_restrictions", "其他饮食限制", "text"],
        ["nutrition.food_preferences", "长期饮食偏好", "text"],
        ["nutrition.disliked_foods", "长期不喜欢的食物", "text"],
      ],
    ],
    [
      "补剂",
      [
        ["supplements.budget.amount", "补剂预算（元）", "number"],
        [
          "supplements.budget.period",
          "补剂预算周期",
          "select",
          [
            ["", "未知"],
            ["day", "每天"],
            ["week", "每周"],
            ["month", "每月"],
          ],
        ],
        ["supplements.current_products", "当前补剂（逗号分隔）", "list"],
      ],
    ],
    [
      "身体情况",
      [
        [
          "health.exercise_limiting_conditions_status",
          "影响运动的问题",
          "select",
          [
            ["none_known_self_reported", "无已知问题"],
            ["unknown", "暂不确定"],
            ["has_conditions", "有，需要说明"],
          ],
        ],
        ["health.exercise_limiting_conditions_details", "问题说明", "text"],
        [
          "health.medications_status",
          "用药状态",
          "select",
          [
            ["unknown", "未知"],
            ["none_known_self_reported", "未服用药物"],
            ["taking", "正在用药"],
          ],
        ],
        ["health.medications", "用药情况", "text"],
      ],
    ],
    [
      "作息恢复",
      [
        ["recovery.usual_sleep_hours", "通常睡眠（小时）", "number"],
        ["recovery.sleep_schedule", "睡眠作息", "text"],
        ["daily_activity_level", "日常活动水平", "text"],
      ],
    ],
  ];
  function renderProfile() {
    const root = $("profile-fields");
    root.replaceChildren();
    const profile = app.profileDraft || app.profile || base();
    profileFields.forEach(([title, defs]) => {
      const card = document.createElement("section");
      card.className = "card";
      card.append(node("h2", title));
      if (title === "力量参考（选填）") card.append(node("p",
        "填已有成绩即可，不必专门测试极限。1RM是单次最大重量，杠铃总重含杆；估算值请在说明中注明。引体按完整、无借力的自重次数填写，辅助或负重成绩写进说明。未知留空。日常做组重量、次数和RPE可通过每日反馈记录，模型会据此校准后续安排。", "field-hint"));
      const grid = document.createElement("div");
      grid.className = "field-grid";
      defs.forEach(([path, label, type, options]) => {
        const wrap = document.createElement("label");
        wrap.textContent = label;
        if (path === "training.training_frequency") {
          wrap.append(node("small", "例如：一周4练、练3休1；不确定可留空。", "field-hint"));
        }
        let input;
        if (type === "select" || type === "boolean" || type === "equipment") {
          input = document.createElement("select");
          if (type === "equipment") input.multiple = true;
          const choices =
            type === "boolean"
              ? [
                  ["", "暂不确定"],
                  ["true", "是"],
                  ["false", "否"],
                ]
              : options;
          choices.forEach(([value, name]) =>
            input.add(new Option(name, value)),
          );
        } else {
          input = document.createElement(
            type === "text" ? "textarea" : "input",
          );
          if (type !== "text") input.type = type === "list" ? "text" : type;
          else input.rows = 2;
          if (type === "number") input.step = "any";
        }
        input.dataset.path = path;
        input.dataset.type = type === "boolean" ? "boolean" : type;
        const value = get(profile, path);
        input.value = Array.isArray(value) ? value.join(", ") : (value ?? "");
        if (type === "equipment")
          [...input.options].forEach((option) => {
            option.selected = value?.includes(option.value) || false;
          });
        if (
          [
            "personal.age_years",
            "training.available_sessions_per_week",
            "training.session_duration_minutes",
            "training.strength_baseline.pull_up_max_reps",
          ].includes(path)
        )
          input.step = "1";
        if (path === "goals.deadline_negotiable") {
          input.options[0].textContent = "未知 / 暂不设置";
        }
        wrap.append(input);
        grid.append(wrap);
      });
      card.append(grid);
      root.append(card);
    });
    root.append(
      node("p", "空白字段会保留为未知，系统不会自动猜测。", "field-hint"),
    );
    $("profile-save-state").textContent = app.version
      ? `已保存版本 ${app.version} · 修改后请保存`
      : "尚未保存档案";
  }
  function readProfile() {
    const profile = clone(app.profileDraft || app.profile || base());
    document
      .querySelectorAll("#profile-fields [data-path]")
      .forEach((input) => {
        let value = fieldValue(input.value, input.dataset.type);
        if (input.dataset.type === "list")
          value = value
            ? value
                .split(/[,，]/)
                .map((x) => x.trim())
                .filter(Boolean)
            : input.dataset.path === "supplements.current_products"
              ? null
              : [];
        if (input.dataset.type === "equipment") {
          value = [...input.selectedOptions].map((option) => option.value);
          if (!value.length) value = null;
        }
        set(profile, input.dataset.path, value);
      });
    return profile;
  }
  function go(view) {
    const sourceId = view.startsWith('feedback-') ? decodeURIComponent(view.slice(9)) : null;
    const longTermId = view.startsWith('plan-') ? decodeURIComponent(view.slice(5)) : null;
    if (sourceId) view = 'feedback';
    if (longTermId) view = 'plan';
    if (!["overview", "profile", "plan", "daily", "feedback", "knowledge"].includes(view))
      view = "overview";
    document.querySelectorAll(".view").forEach((section) => {
      section.hidden = section.id !== `view-${view}`;
    });
    document.querySelectorAll(".nav-button").forEach((nav) => {
      const active = nav.dataset.view === view;
      nav.classList.toggle("active", active);
      active
        ? nav.setAttribute("aria-current", "page")
        : nav.removeAttribute("aria-current");
    });
    window.location.hash = longTermId ? `plan-${encodeURIComponent(longTermId)}` : view;
    if (sourceId) {
      const item = app.feedback.find(row => row.id === sourceId);
      if (item) { app.selectedFeedback = item; renderFeedbackHistory(); renderFeedbackEditor(item); }
      else api('/api/feedback/' + encodeURIComponent(sourceId)).then(putFeedback).catch(error => show(error.message, true));
    }
    if (view === 'feedback') loadPersonalMemory();
    document.dispatchEvent(new CustomEvent('fitness-view-change', {detail: {view, long_term_id: longTermId}}));
  }
  function renderKnowledgeStats() {
    const root = $("knowledge-stats");
    root.replaceChildren();
    [
      ["全部候选", app.reviewCounts.total],
      ["待审核", app.reviewCounts.pending],
      ["已批准", app.reviewCounts.approved],
      ["已拒绝", app.reviewCounts.rejected],
    ].forEach(([label, value]) => {
      const item = node("div", "", "knowledge-stat");
      item.append(node("span", label), node("strong", String(value || 0)));
      root.append(item);
    });
  }
  function renderKnowledgeList() {
    renderKnowledgeStats();
    const root = $("knowledge-list");
    root.replaceChildren();
    const cards = filterReviewCards(app.reviewCards, app.reviewFilters);
    $("knowledge-result-count").textContent = cards.length + " 张卡片";
    if (!cards.length) {
      root.append(node("div", "没有符合当前筛选条件的卡片。", "empty-state"));
      return;
    }
    cards.forEach((card) => {
      const selected = app.selectedReviewCard?.id === card.id ? " selected" : "";
      const item = action("", "knowledge-list-item" + selected, () => {
        app.selectedReviewCard = card;
        renderKnowledgeList();
        renderKnowledgeDetail();
      });
      item.append(
        node("span", card.title, "knowledge-list-title"),
        node("span", reviewLabel(card.review_status), "review-status " + card.review_status),
        node("small", card.collection + " · " + card.source_bvids.length + " 个来源"),
      );
      root.append(item);
    });
  }
  function renderKnowledgeDetail() {
    const root = $("knowledge-detail");
    root.replaceChildren();
    const card = app.selectedReviewCard;
    if (!card) {
      root.append(node("div", "从左侧选择一张知识卡开始审核。", "empty-state"));
      return;
    }
    const header = node("div", "", "knowledge-detail-heading");
    header.append(
      node("h2", card.title, "knowledge-detail-title"),
      node("span", reviewLabel(card.review_status), "review-status " + card.review_status),
    );
    root.append(header, node("p", card.collection, "metadata"));
    const statements = node("section", "", "review-section");
    statements.append(node("h3", "视频观点"));
    card.creator_statement.forEach((row) => statements.append(node("p", row.statement)));
    root.append(statements);
    const source = node("section", "", "review-section");
    source.append(node("h3", "来源"));
    card.source_bvids.forEach((bvid) => {
      const link = node("a", bvid);
      link.href = "https://www.bilibili.com/video/" + encodeURIComponent(bvid);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      source.append(link);
    });
    source.append(node("p", "观点 ID：" + card.source_claim_ids.join("、"), "metadata"));
    root.append(source);
    const limits = node("section", "", "review-section review-limits");
    limits.append(node("h3", "不确定性"), node("p", card.uncertainty));
    limits.append(node("h3", "安全边界"), node("p", card.safety_boundary));
    root.append(limits);
    const label = node("label", "审核备注");
    const note = document.createElement("textarea");
    note.id = "knowledge-review-note";
    note.rows = 3;
    note.maxLength = 2000;
    note.value = card.review_note || "";
    label.append(note);
    root.append(label);
    const actions = node("div", "", "review-actions");
    [
      ["批准", "button", "approved"],
      ["拒绝", "button danger", "rejected"],
      ["恢复待审核", "button secondary", "pending"],
    ].forEach(([text, className, status]) => {
      actions.append(action(text, className, async (event) => {
        const target = event.currentTarget;
        busy(target, true);
        try {
          await api("/api/knowledge/review/" + encodeURIComponent(card.id), {
            method: "POST",
            body: JSON.stringify({ status, note: note.value }),
          });
          await loadKnowledgeReview(card.id);
          show("“" + card.title + "”已标记为" + reviewLabel(status) + "。");
        } catch (error) {
          show(error.message, true);
        } finally {
          busy(target, false);
        }
      }));
    });
    root.append(actions);
  }
  async function loadKnowledgeReview(selectedId = null) {
    const payload = await api("/api/knowledge/review");
    app.reviewCards = payload.cards || [];
    app.reviewCounts = payload.counts || app.reviewCounts;
    const wanted = selectedId || app.selectedReviewCard?.id;
    app.selectedReviewCard =
      app.reviewCards.find((card) => card.id === wanted) || app.reviewCards[0] || null;
    renderKnowledgeList();
    renderKnowledgeDetail();
  }
  function renderOverview() {
    $("hero-title").textContent = app.profile
      ? "档案已就绪，开始你的下一步。"
      : "一份适合你的计划，从你的档案开始。";
    $("hero-copy").textContent = app.profile
      ? "计划先确认，每日反馈先核对，再查看建议。"
      : "先填写你知道的信息；暂时不确定的内容可以留空。";
    const stats = $("overview-stats");
    stats.replaceChildren();
    const values = app.profile
      ? [
          [
            "当前体重",
            `${app.profile.personal.weight_kg ?? "未知"} kg`,
            "最近一次档案",
          ],
          [
            "每周训练",
            app.profile.training.training_frequency || (app.profile.training.available_sessions_per_week == null
              ? "未知" : `每周 ${app.profile.training.available_sessions_per_week} 练`),
            "可按反馈调整",
          ],
          [
            "已确认反馈",
            `${app.feedback.filter((x) => x.status === "confirmed").length} 条`,
            "单日数据不会改变长期计划",
          ],
        ]
      : [
          ["档案状态", "尚未保存", "先填写基本情况"],
          ["长期计划", "等待生成", "可从已有信息开始"],
          ["每日反馈", "0 条", "确认后进入历史"],
        ];
    values.forEach(([label, value, note]) => {
      const card = document.createElement("div");
      card.className = "stat-card";
      card.append(
        node("span", label, "stat-label"),
        node("strong", value),
        node("p", note),
      );
      stats.append(card);
    });
    const steps = $("next-steps");
    steps.replaceChildren();
    const item = app.profile
      ? [
          "查看长期计划与训练循环",
          "确定长期方向，再安排每一天",
          "plan",
        ]
      : ["完成我的档案", "目标、时间和饮食情况可以逐步补充", "profile"];
    const row = document.createElement("div");
    row.className = "step";
    row.append(
      node("span", "1", "step-number"),
      node("p", `${item[0]}\n${item[1]}`),
      action("打开", "text-button", () => go(item[2])),
    );
    row.children[1].style.whiteSpace = "pre-line";
    steps.append(row);
    const recent = $("recent-feedback");
    recent.replaceChildren();
    if (!app.feedback.length)
      recent.append(node("div", "还没有每日反馈。", "empty-state"));
    else
      app.feedback
        .slice(0, 3)
        .forEach((x) =>
          recent.append(
            node(
              "div",
              `${fmt(x.date)} · ${x.status === "confirmed" ? "已确认" : "草稿"}\n${x.data?.training_summary || x.raw_text}`,
              "step",
            ),
          ),
        );
  }
  function renderPlan() {
    const root = $("plan-content");
    root.replaceChildren();
    if (!app.plan) {
      root.append(
        node(
          "div",
          app.plans.length
            ? "请选择一份计划查看。"
            : "保存档案后生成第一份计划。",
          "empty-state",
        ),
      );
      return;
    }
    const plan = app.plan;
    const data = JSON.parse(JSON.stringify(plan.data));
    (app.planChanges || []).filter(change => change.plan_id === plan.id).forEach(change => {
      (change.changes || []).forEach(field => {
        const parts = field.path.split('.');
        if (parts.length === 5 && parts[0] === 'days' && parts[2] === 'exercises' && parts[4] === 'sets') {
          const exercise = data.days?.[Number(parts[1])]?.exercises?.[Number(parts[3])];
          if (exercise) exercise.sets = field.new_value;
        }
      });
    });
    const card = document.createElement("section");
    card.className = "card";
    const head = document.createElement("div");
    head.className = "card-heading";
    head.append(
      node("h2", data.title),
      node(
        "span",
        plan.status === "confirmed" ? "已确认" : "草稿",
        `pill ${plan.status === "confirmed" ? "" : "demo"}`,
      ),
    );
    const visibleSummary = String(data.summary || "")
      .replace(/\s*方案依据（共\d+个模块）：.*$/u, "")
      .trim();
    card.append(head, node("p", visibleSummary, "plan-summary"));
    card.append(
      node(
        "p",
        `${fmt(plan.start_date)} 起 · ${plan.mode === 'live' ? '模型草案' : '历史草案'} · 使用档案版本 ${plan.profile_version}`,
        "metadata",
      ),
      renderExportActions("plan", plan.id),
    );
    if (plan.trace?.provider?.status === 'fallback') card.append(node('p', '历史记录：该计划由旧版本本地规则生成。', 'notice-inline'));
    if (plan.status === "draft" && plan.profile_version !== app.version)
      card.append(
        node(
          "p",
          "档案已改变，这份草案需要重新生成后才能确认。",
          "notice-inline",
        ),
      );
    data.questions?.forEach((q) =>
      card.append(node("p", `待补充：${q}`, "notice-inline")),
    );
    const grid = document.createElement("div");
    grid.className = "day-grid";
    data.days.forEach((day) => {
      const dayCard = document.createElement("article");
      dayCard.className = `day-card ${day.kind === "rest" ? "rest" : ""}`;
      dayCard.append(
        node("h3", `${day.label} · ${day.estimated_minutes} 分钟`),
      );
      if (!day.exercises.length)
        dayCard.append(node("p", "恢复、散步或轻松活动。", "muted"));
      day.exercises.forEach((x) =>
        dayCard.append(
          node(
            "div",
            `${x.name} · ${x.sets} 组 × ${x.reps_min}-${x.reps_max} 次\n组间休息 ${x.rest_seconds} 秒`,
            "exercise",
          ),
        ),
      );
      grid.append(dayCard);
    });
    card.append(grid);
    card.append(
      node("h3", "饮食安排"),
      node("p", data.nutrition.approach, "plan-summary"),
    );
    if (data.nutrition.daily_targets) {
      const target = data.nutrition.daily_targets;
      card.append(node('p', `${target.calories_kcal} 千卡 · 蛋白质 ${target.protein_g}g · 脂肪 ${target.fat_g}g · 碳水 ${target.carbs_g}g`, 'nutrition-targets'));
      card.append(node('p', `${target.method}；${target.assumptions.join('；')}`, 'field-hint'));
    }
    const nutrition = document.createElement("div");
    nutrition.className = "nutrition-grid";
    data.nutrition.meal_options.forEach((meal) => {
      const section = document.createElement("section");
      section.append(node("h3", meal.meal));
      if (meal.estimated_kcal != null)
        section.append(node('p', `${meal.estimated_kcal} 千卡 · 蛋白质 ${meal.protein_g}g · 脂肪 ${meal.fat_g}g · 碳水 ${meal.carbs_g}g${meal.estimated_cost_cny != null ? ` · 约${meal.estimated_cost_cny}元` : ''}`, 'metadata'));
      const list = document.createElement("ul");
      meal.suggestions.forEach((x) => list.append(node("li", x)));
      section.append(list);
      nutrition.append(section);
    });
    card.append(
      nutrition,
      node("p", data.nutrition.budget_note, "notice-inline"),
    );
    const dayForm = document.createElement('form');
    dayForm.className = 'card inline-form nutrition-day-form';
    const mealSelect = document.createElement('select'); mealSelect.name = 'meal';
    [['', '安排全天'], ['早餐', '早餐'], ['午餐', '午餐'], ['晚餐', '晚餐'], ['训练后', '训练后']].forEach(([value, label]) => {
      const option = document.createElement('option'); option.value = value; option.textContent = label; mealSelect.append(option);
    });
    const mealLabel = node('label', '餐次'); mealLabel.append(mealSelect);
    const field = (labelText, name, placeholder, maxLength) => {
      const input = document.createElement('input'); input.name = name; input.maxLength = maxLength; input.placeholder = placeholder;
      const label = node('label', labelText); label.append(input); return label;
    };
    dayForm.append(node('h3', '按今天的条件安排饮食'), mealLabel,
      field('今天的用餐条件', 'conditions', '例如：只能点外卖，预算18元', 500),
      field('能吃到什么', 'available_foods', '例如：鸡肉、米饭、青菜', 500),
      field('想吃什么', 'desired_foods', '例如：今天想吃黄焖鸡', 300),
      field('今天已吃内容', 'already_eaten', '可选：早餐吃了什么和大致份量', 500));
    const submit = node('button', '生成饮食安排', 'button'); submit.type = 'submit'; dayForm.append(submit);
    const dayResult = node('div'); dayResult.className = 'nutrition-day-result'; dayResult.hidden = true;
    dayForm.append(dayResult); card.append(dayForm);
    [['作息与恢复', data.recovery_guidance], ['补剂优先级', data.supplement_guidance]].forEach(([title, rows]) => {
      if (!rows?.length) return;
      card.append(node('h3', title));
      const list = document.createElement('ul'); rows.forEach(text => list.append(node('li', text))); card.append(list);
    });
    if ((app.planChanges || []).some(change => change.plan_id === plan.id)) {
      const history = document.createElement('details'); history.append(node('summary', '已确认的局部调整'));
      app.planChanges.filter(change => change.plan_id === plan.id).forEach(change =>
        history.append(node('p', `${change.day_date}：${change.changes.map(c => `${c.path} ${c.old_value} → ${c.new_value}`).join('；')}`)));
      card.append(history);
    }
    if (plan.status !== "confirmed" && plan.profile_version === app.version)
      card.append(
        action("确认这份计划", "button", async (event) => {
          const target = event.currentTarget;
          busy(target, true);
          try {
            const confirmed = await api(`/api/plans/${plan.id}/confirm`, {
              method: "POST",
            });
            app.plans = app.plans.map((x) =>
              x.id === confirmed.id ? confirmed : x,
            );
            app.plan = confirmed;
            renderPlans();
            renderOverview();
            show("计划已确认，可以开始记录执行情况。");
          } catch (error) {
            show(error.message, true);
          } finally {
            busy(target, false);
          }
        }),
      );
    root.append(card);
  }
  function renderPlans() {
    const history = $("plan-history");
    history.replaceChildren();
    if (!app.plans.length) {
      app.plan = null;
      renderPlan();
      return;
    }
    const select = document.createElement("select");
    select.setAttribute("aria-label", "计划历史");
    app.plans.forEach((x) =>
      select.add(
        new Option(
          `${fmt(x.start_date)} · 版本 ${x.version} · ${x.status === "confirmed" ? "已确认" : "草稿"}`,
          x.id,
        ),
      ),
    );
    select.value = app.plan?.id || app.plans[0].id;
    select.onchange = () => {
      app.plan = app.plans.find((x) => x.id === select.value);
      renderPlans();
    };
    history.append(select);
    app.plan ??= app.plans[0];
    renderPlan();
  }
  function renderFeedbackHistory() {
    const root = $("feedback-list");
    root.replaceChildren();
    if (!app.feedback.length) {
      root.append(node("div", "还没有记录。", "empty-state"));
      return;
    }
    root.append(renderExportActions("feedback"));
    app.feedback.forEach((item) => {
      const el = action(
        `${fmt(item.date)} · ${item.coaching ? (item.coaching.status === 'ready' ? '模型已回应' : '原文已保存') : item.status === "confirmed" ? "已确认" : "草稿"}\n${item.data?.training_summary || item.raw_text}`,
        `history-item ${app.selectedFeedback?.id === item.id ? "selected" : ""}`,
        () => {
          if (app.feedbackDirty) {
            show("当前反馈有未保存修改，请先保存或点击“撤销本次编辑”。", true);
            return;
          }
          app.selectedFeedback = item;
          renderFeedbackHistory();
          renderFeedbackEditor(item);
        },
      );
      el.style.whiteSpace = "pre-line";
      root.append(el);
    });
  }
  async function loadDailyPlans() {
    const state = await api('/api/planning/state');
    app.dailyPlans = state.daily_plans || [];
    return app.dailyPlans;
  }
  function putFeedback(item) {
    const index = app.feedback.findIndex(row => row.id === item.id);
    if (index < 0) app.feedback.unshift(item); else app.feedback[index] = item;
    app.selectedFeedback = item;
    renderFeedbackHistory(); renderFeedbackEditor(item); renderOverview();
  }
  async function loadPersonalMemory() {
    const root = $('personal-memory-content');
    if (!root) return;
    try { FeedbackCoachUI.renderMemory(root, await api('/api/personal-memory'), document, {
      confirmPreference: async (key, version, action) => {
        try {
          await api(`/api/personal-memory/${encodeURIComponent(key)}/confirm`, {method:'POST',
            body:JSON.stringify({expected_version:version,action})});
          await loadPersonalMemory();
          document.dispatchEvent(new CustomEvent('fitness-state-change', {detail:{
            profile_version:app.version,feedback_saved:true}}));
          show(action === 'confirm' ? '偏好已确认，后续规划会采用你的确认。' : '偏好已停用，原始记录和旧版本保留。');
        } catch (error) { show(error.message,true); }
      }
    }); }
    catch (error) { root.textContent = `个人记忆暂时未能加载：${error.message}`; }
  }
  async function understandFeedback(id, refresh = false, retryPlan = false, syncProfile = false) {
    try {
      const path = syncProfile ? 'sync-profile' : retryPlan ? 'retry-plan' : `understand${refresh ? '?refresh=true' : ''}`;
      const item = await api(`/api/feedback/${encodeURIComponent(id)}/${path}`, {method: 'POST'});
      putFeedback(item);
      if (item.coaching?.profile_sync?.updated_fields?.length) await refreshSyncedProfile();
      document.dispatchEvent(new CustomEvent('fitness-state-change', {detail: {
        profile_version: app.version, feedback_saved: true, planning_update: item.coaching?.planning_update}}));
      await Promise.allSettled([loadPersonalMemory(), loadDailyPlans()]);
      show(syncProfile && item.coaching?.status !== 'ready' ? '档案核对未完成，原文已保留，可稍后重试。'
        : syncProfile ? '原计划补充已重新核对，个人档案同步结果已更新。'
        : item.coaching?.status === 'ready' ? '反馈已保存，模型已结合历史给出回应。' : '原文已保存，模型理解未完成，可重试。',
      item.coaching?.status !== 'ready');
    } catch (error) { show(`原文已保存；${error.message}。可稍后重试模型理解。`, true); }
  }
  function renderFeedbackEditor(item) {
    app.feedbackDirty = false;
    const root = $("feedback-editor");
    root.replaceChildren();
    if (!item) return;
    if (item.coaching) {
      FeedbackCoachUI.render(root, item, {retry: understandFeedback,
        retryPlan: id => understandFeedback(id, false, true),
        syncProfile: id => understandFeedback(id, false, false, true),
        confirmFacts: async (id, revision, facts) => {
          try {
            const saved = await api(`/api/feedback/${encodeURIComponent(id)}/facts/confirm`, {
              method:'POST',body:JSON.stringify({expected_revision:revision,...facts})});
            putFeedback(saved);
            document.dispatchEvent(new CustomEvent('fitness-state-change', {detail:{
              profile_version:app.version,feedback_saved:true}}));
            await loadPersonalMemory();
            show('状态已确认保存。可以点击“重试模型理解”，让后续安排采用更正后的记录。');
          } catch (error) { show(error.message,true); }
        },
        replyDraft: app.feedbackReplies.get(item.id)?.text,
        changeDraft: text => app.feedbackReplies.set(item.id, {text}),
        followup: async (id, text) => {
          let draft = app.feedbackReplies.get(id);
          if (!draft?.key || draft.text !== text) {
            draft = {text, key: crypto.randomUUID()}; app.feedbackReplies.set(id, draft);
          }
          const saved = await api('/api/feedback/record', {method: 'POST', body: JSON.stringify({
            text, date: item.date, timing: item.coaching.timing,
            parent_feedback_id: id, request_key: draft.key})});
          app.feedbackReplies.delete(id);
          putFeedback(saved);
          await understandFeedback(saved.id);
        }});
      return;
    }
    const card = document.createElement("section");
    card.className = "card";
    card.append(node("span", "第二步 · 核对反馈", "pill"));
    card.append(
      node(
        "p",
        `${fmt(item.date)} · ${item.status === "confirmed" ? "已确认" : "草稿"} · 修订 ${item.revision}`,
        "metadata",
      ),
    );
    card.append(node("p", `原始记录：${item.raw_text}`, "plan-summary"));
    const grid = document.createElement("div");
    grid.className = "field-grid feedback-fields";
    [
      ["date", "记录日期", "date"],
      ["training_summary", "训练记录", "text"],
      ["food_summary", "饮食记录", "text"],
      ["diet_followed_plan", "饮食是否按计划执行", "boolean"],
      ["training_completed", "是否完成训练", "boolean"],
      ["sleep_hours", "睡眠小时", "number"],
      ["fatigue", "疲劳感受", "text"],
      ["weight_kg", "体重（kg）", "number"],
      ["sleep_date", "睡眠所属日期（不确定留空）", "date"],
      ["intake_kcal", "本人提供的热量（kcal，不确定留空）", "number"],
      ["meal_to_plan", "想规划的餐次（可留空）", "text"],
      ["meal_conditions", "今天的用餐条件", "text"],
      ["available_foods", "今天能吃到什么", "text"],
      ["desired_foods", "今天想吃什么", "text"],
      ["already_eaten", "今天已经吃过什么", "text"],
    ].forEach(([key, label, type]) => {
      const wrap = document.createElement("label");
      wrap.textContent = label;
      let input;
      if (type === "boolean") {
        input = document.createElement("select");
        [
          ["", "未知"],
          ["true", "是"],
          ["false", "否"],
        ].forEach(([value, name]) => input.add(new Option(name, value)));
      } else {
        input = document.createElement(type === "text" ? "textarea" : "input");
        if (type !== "text") input.type = type;
        else input.rows = 2;
        if (type === "number") input.step = "any";
      }
      input.dataset.key = key;
      input.dataset.type = type;
      input.value = item.data?.[key] ?? "";
      if (key === "date") input.required = true;
      wrap.append(input);
      grid.append(wrap);
    });
    card.append(grid);
    const daily = app.dailyPlans.find(row => row.date === item.date);
    const plannedExercises = daily?.data?.training?.exercises || [];
    const savedResults = item.data?.exercise_results || [];
    const resultRows = savedResults.length ? savedResults : plannedExercises.map(exercise => ({
      exercise_id: exercise.exercise_id,
    }));
    if (resultRows.length) {
      const heading = node('h3', '本次动作反馈');
      card.append(heading, node('p', '填写实际完成重量和各动作的主观用力程度（RPE 1–10）；不确定的项留空。', 'field-hint'));
      const resultGrid = document.createElement('div');
      resultGrid.className = 'field-grid feedback-fields';
      resultRows.forEach((result, resultIndex) => {
        const exercise = plannedExercises.find(row => row.exercise_id === result.exercise_id);
        const section = document.createElement('section');
        section.className = 'exercise-feedback';
        section.append(node('strong', exercise?.name || result.exercise_name || result.exercise_id));
        if (result.session_id) section.append(node('p',`场次：${result.session_id}`,'metadata'));
        (result.sets || []).forEach((set,index) => section.append(node('p',
          `第${index+1}组：${set.reps}次${set.weight_kg == null ? '' : ` · ${set.weight_kg} kg`}${set.rpe == null ? '' : ` · RPE ${set.rpe}`}`)));
        if (exercise) {
          const target = [exercise.weight_kg != null ? `计划 ${exercise.weight_kg} kg` : null,
            exercise.target_rpe != null ? `目标 RPE ${exercise.target_rpe}` : null].filter(Boolean).join(' · ');
          if (target) section.append(node('p', target, 'metadata'));
        }
        const fields = document.createElement('div');
        fields.className = 'field-grid exercise-feedback-fields';
        [['weight_kg', '实际重量（kg）', 0, 1000], ['rpe', '实际 RPE', 1, 10]].forEach(([key, label, min, max]) => {
          const wrap = document.createElement('label');
          wrap.textContent = label;
          const input = document.createElement('input');
          input.type = 'number'; input.min = String(min); input.max = String(max);
          input.step = key === 'rpe' ? '0.5' : 'any';
          input.value = result[key] ?? '';
          input.dataset.exerciseId = result.exercise_id;
          input.dataset.resultIndex = String(resultIndex);
          input.dataset.exerciseField = key;
          input.addEventListener('input', () => { app.feedbackDirty = true; });
          wrap.append(input); fields.append(wrap);
        });
        section.append(fields); resultGrid.append(section);
      });
      card.append(resultGrid);
    }
    (item.data.uncertainties || []).forEach((value) =>
      card.append(node("p", value, "notice-inline")),
    );
    const actions = document.createElement("div");
    actions.className = "feedback-actions";
    actions.append(
      action("确认并保存反馈", "button", async (event) => {
        for (const input of card.querySelectorAll("[data-key]"))
          if (!input.reportValidity()) return;
        const target = event.currentTarget;
        busy(target, true);
        try {
          const data = clone(item.data);
          card.querySelectorAll("[data-key]").forEach((input) => {
            data[input.dataset.key] = fieldValue(
              input.value,
              input.dataset.type,
            );
          });
          data.exercise_results = FeedbackCoachUI.mergeExerciseEdits(resultRows,
            [...card.querySelectorAll('[data-exercise-id]')].map(input => ({
              index:Number(input.dataset.resultIndex),field:input.dataset.exerciseField,
              value:fieldValue(input.value,'number')})));
          const confirmed = await api(`/api/feedback/${item.id}/confirm`, {
            method: "POST",
            body: JSON.stringify({ data, expected_revision: item.revision }),
          });
          app.feedback = app.feedback.map((x) =>
            x.id === confirmed.id ? confirmed : x,
          );
          await loadDailyPlans().catch(() => {});
          app.selectedFeedback = confirmed;
          renderFeedbackHistory();
          renderFeedbackEditor(confirmed);
          renderOverview();
          document.dispatchEvent(new CustomEvent('fitness-state-change', {detail: {profile_version: app.version, feedback_saved: true, planning_update: confirmed.planning_update}}));
          const update = confirmed.planning_update;
          const planningFailed = update && update.status === 'failed';
          show(planningFailed ? `反馈已保存；当天计划未更新。${update.message || ''} ${(update.questions || []).join(' ')}` : "反馈已保存。", Boolean(planningFailed));
        } catch (error) {
          show(error.message, true);
        } finally {
          busy(target, false);
        }
      }),
    );
    actions.append(
      action("撤销本次编辑", "button secondary", () =>
        renderFeedbackEditor(item),
      ),
    );
    if (item.status === "confirmed")
      actions.append(
        action("生成今日建议", "button secondary", async (event) => {
          if (app.feedbackDirty) {
            show("请先确认并保存当前修改，再生成建议。", true);
            return;
          }
          const target = event.currentTarget;
          busy(target, true);
          try {
            const updated = await api(`/api/feedback/${item.id}/advice`, {
              method: "POST",
              body: JSON.stringify({ mode: 'live' }),
            });
            app.feedback = app.feedback.map((x) =>
              x.id === updated.id ? updated : x,
            );
            app.selectedFeedback = updated;
            renderFeedbackHistory();
            renderFeedbackEditor(updated);
            show("建议已生成。");
          } catch (error) {
            show(error.message, true);
          } finally {
            busy(target, false);
          }
        }),
      );
    if (item.status === "confirmed") {
      const nutritionButton = action("按这次饮食条件规划", "button secondary", async (event) => {
        if (app.feedbackDirty) {
          show("请先确认并保存当前饮食条件，再规划餐单。", true);
          return;
        }
        const target = event.currentTarget; busy(target, true);
        try {
          const response = await api('/api/nutrition/plan', {method:'POST', body:JSON.stringify({
            date:item.date, feedback_id:item.id, mode:'live',
          })});
          const data = response.data;
          const panel = document.createElement('section'); panel.className = 'advice-panel';
          if (data.daily_targets) {
            const t = data.daily_targets;
            panel.append(node('p', `全天目标 ${t.calories_kcal} 千卡 · 蛋白质 ${t.protein_g}g · 脂肪 ${t.fat_g}g · 碳水 ${t.carbs_g}g`));
          }
          data.questions.forEach(question => panel.append(node('p', question, 'notice-inline')));
          data.meal_options.forEach(meal => {
            panel.append(node('h3', meal.meal));
            panel.append(node('p', `${meal.estimated_kcal} 千卡 · 蛋白质 ${meal.protein_g}g · 脂肪 ${meal.fat_g}g · 碳水 ${meal.carbs_g}g`));
            const list = document.createElement('ul'); meal.suggestions.forEach(value => list.append(node('li', value))); panel.append(list);
          });
          card.querySelector('.nutrition-feedback-result')?.remove(); panel.classList.add('nutrition-feedback-result');
          card.insertBefore(panel, actions);
        } catch (error) { show(error.message, true); }
        finally { busy(target, false); }
      });
      actions.append(nutritionButton);
    }
    card.append(actions);
    card.addEventListener("input", () => {
      app.feedbackDirty = true;
      card.querySelector(".advice-panel")?.remove();
    });
    card.addEventListener("change", () => {
      app.feedbackDirty = true;
      card.querySelector(".advice-panel")?.remove();
    });
    const revisions = document.createElement("div");
    revisions.className = "revision-panel";
    if (item.status === "confirmed")
      card.append(
        action("查看修改历史", "text-button", async (event) => {
          const target = event.currentTarget;
          busy(target, true);
          try {
            const rows = await api(`/api/feedback/${item.id}/revisions`);
            revisions.replaceChildren();
            rows.forEach((row) => {
              const detail = document.createElement("details");
              detail.append(
                node("summary", `修订 ${row.revision} · ${row.created_at}`),
                node("pre", JSON.stringify(row.data, null, 2)),
              );
              revisions.append(detail);
            });
          } catch (error) {
            show(error.message, true);
          } finally {
            busy(target, false);
          }
        }),
      );
    card.append(revisions);
    if (item.advice_error)
      card.append(
        node(
          "p",
          `上次建议生成失败：${item.advice_error}。反馈仍已保存，可重试。`,
          "notice-inline",
        ),
      );
    if (item.advice) {
      const advice = document.createElement("div");
      advice.className = "advice-panel";
      advice.append(
        node("h3", "今日建议"),
        renderExportActions("advice", item.id),
        node("p", item.advice.summary),
      );
      const adviceStatusMessage = knowledgeStatusMessage(item.trace?.knowledge_status);
      if (adviceStatusMessage) advice.append(node("p", adviceStatusMessage, "notice-inline"));
      if (item.trace?.provider?.status === 'fallback') advice.append(node('p', '历史记录：该建议由旧版本本地规则生成。', 'notice-inline'));
      const list = document.createElement("ul");
      item.advice.suggestions.forEach((x) => list.append(node("li", x)));
      advice.append(list);
      advice.append(renderBriefExplanation(item.advice, item.trace));
      const preview = item.trace?.training_adjustment_preview;
      if (preview?.changes?.length) {
        const adjustment = document.createElement('details');
        adjustment.append(node('summary', '预览当日训练调整'), node('p', preview.reason));
        preview.changes.forEach(change => {
          const parts = change.path.split('.');
          const plan = app.plans.find(row => row.id === preview.plan_id);
          const exercise = plan?.data?.days?.[Number(parts[1])]?.exercises?.[Number(parts[3])];
          adjustment.append(node('p', `${exercise?.name || '训练动作'}：${change.old_value} 组 → ${change.new_value} 组`));
        });
        adjustment.append(action('确认这次局部调整', 'button secondary', async (event) => {
          const target = event.currentTarget; busy(target, true);
          try {
            await api(`/api/feedback/${item.id}/training-adjustment/confirm`, {
              method:'POST', body:JSON.stringify({proposal:preview, confirmed:true}),
            });
            renderAll(await api('/api/state'));
            show('局部调整已记录，基础周计划快照已保留。');
          } catch (error) { show(error.message, true); }
          finally { busy(target, false); }
        }));
        advice.append(adjustment);
      }
      card.append(advice);
    }
    root.append(card);
  }
  function renderAll(payload) {
    app.profile = payload.profile;
    app.version = payload.profile_version;
    app.plans = payload.plans || [];
    app.feedback = payload.feedback || [];
    app.planChanges = payload.plan_changes || [];
    app.mode = preservedMode(app.mode, payload);
    app.knowledgeStatus = payload.knowledge_status || "unknown";
    app.plan =
      app.plans.find((x) => x.id === app.plan?.id) || app.plans[0] || null;
    app.selectedFeedback =
      app.feedback.find((x) => x.id === app.selectedFeedback?.id) || null;
    const configured = payload.model_configured === true;
    $("model-status").textContent = configured ? `模型：${payload.model}` : '模型 API 待配置';
    for (const id of ['long-term-submit', 'daily-submit', 'generate-plan']) $(id).disabled = !configured;
    $("import-profile").disabled = !payload.example_available;
    $("today-label").textContent = `今天是 ${payload.today || today()}`;
    $("mode-note").textContent =
      configured
        ? `在线模型：${payload.model || "已配置"}。长期计划草稿需确认；反馈先保存，再由模型理解回应。`
        : "请先在 .env 配置自己的模型 API：FITNESS_API_KEY、FITNESS_BASE_URL 和 FITNESS_MODEL，然后重启服务。配置前可填写档案、保存反馈和查看历史，智能生成暂不可用。";
    const globalKnowledgeStatus = knowledgeStatusMessage(app.knowledgeStatus);
    if (globalKnowledgeStatus) $("mode-note").textContent += ` ${globalKnowledgeStatus}`;
    renderProfile();
    renderOverview();
    renderPlans();
    renderFeedbackHistory();
    renderFeedbackEditor(app.selectedFeedback);
    renderKnowledgeList();
    renderKnowledgeDetail();
    document.dispatchEvent(new CustomEvent('fitness-state-change', {detail: {profile_version: app.version, model_configured: configured}}));
  }
  async function refreshSyncedProfile() {
    const formState = $('profile-save-state');
    const dirty = formState.textContent.includes('未保存') || app.profileDraft;
    const editingVersion = app.version;
    const state = await api('/api/state');
    if (state.profile_version <= app.version) return;
    if (dirty || formState.textContent.includes('未保存') || app.profileDraft || app.version !== editingVersion) {
      formState.textContent = '档案已由补充回答更新，未保存修改已保留；请刷新核对新档案后再保存。';
      return;
    }
    app.profile = state.profile; app.version = state.profile_version;
    renderProfile(); renderOverview(); renderPlans();
  }
  document.addEventListener('fitness-profile-synced', () => {
    refreshSyncedProfile().catch(error => show(`档案已保存，但页面刷新失败：${error.message}`, true));
  });
  document.addEventListener("DOMContentLoaded", async () => {
    $('plan-content').addEventListener('submit', async (event) => {
      const form = event.target.closest('.nutrition-day-form');
      if (!form) return;
      event.preventDefault();
      const submit = form.querySelector('button[type="submit"]'); busy(submit, true);
      const output = form.querySelector('.nutrition-day-result'); output.replaceChildren();
      try {
        const fields = Object.fromEntries(new FormData(form).entries());
        const result = await api('/api/nutrition/plan', {method:'POST', body:JSON.stringify({
          ...fields, date:today(), mode:app.mode,
        })});
        const data = result.data;
        if (data.daily_targets) {
          const t = data.daily_targets;
          output.append(node('p', `全天目标 ${t.calories_kcal} 千卡 · 蛋白质 ${t.protein_g}g · 脂肪 ${t.fat_g}g · 碳水 ${t.carbs_g}g`));
        }
        data.questions.forEach(question => output.append(node('p', question, 'notice-inline')));
        data.meal_options.forEach(meal => {
          output.append(node('h4', meal.meal));
          output.append(node('p', `${meal.estimated_kcal} 千卡 · 蛋白质 ${meal.protein_g}g · 脂肪 ${meal.fat_g}g · 碳水 ${meal.carbs_g}g`));
          const list = document.createElement('ul'); meal.suggestions.forEach(value => list.append(node('li', value))); output.append(list);
        });
        output.append(node('p', data.budget_note, 'field-hint'));
        output.hidden = false;
      } catch(error) { show(error.message, true); }
      finally { busy(submit, false); }
    });
    $('import-feedback-form').addEventListener('submit', async (event) => {
      event.preventDefault();
      if (app.feedbackDirty) {
        show('请先保存或撤销当前反馈编辑，再导入历史。', true);
        return;
      }
      const target = event.currentTarget.querySelector('button'); busy(target, true);
      const root = $('import-preview'); root.replaceChildren();
      try {
        const file = $('import-file').files[0];
        if (!file || file.size > 1_000_000) throw new Error('请选择不超过1MB的反馈文件。');
        const payload = {content:await file.text(), format:$('import-format').value};
        const preview = await api('/api/import/feedback/preview', {method:'POST', body:JSON.stringify(payload)});
        root.append(node('p', `${preview.items.length} 条待导入，${preview.skipped} 条跳过，${preview.errors.length} 条错误。`));
        preview.errors.forEach(error => root.append(node('p', `第${error.index+1}条：${error.error}`, 'notice-inline')));
        preview.items.forEach(item => root.append(node('pre', JSON.stringify(item.data, null, 2))));
        if (!preview.errors.length && preview.items.length) root.append(action('确认导入这些事实', 'button', async (e) => {
          if (app.feedbackDirty) {
            show('请先保存或撤销当前反馈编辑，再确认导入。', true);
            return;
          }
          const button = e.currentTarget; busy(button, true);
          try {
            const result = await api('/api/import/feedback/confirm', {method:'POST', body:JSON.stringify({
              ...payload, batch_id:preview.batch_id, confirmed:true,
            })});
            root.replaceChildren(node('p', `导入${result.imported}条，重复${result.duplicates}条。`));
            renderAll(await api('/api/state'));
            show('历史反馈已导入。');
          } catch(error) {show(error.message, true);} finally {busy(button, false);}
        }));
      } catch(error) {show(error.message, true);} finally {busy(target, false);}
    });
    window.addEventListener("hashchange", () =>
      go(window.location.hash.slice(1)),
    );
    $('personal-memory-panel').addEventListener('toggle', () => {
      if ($('personal-memory-panel').open) loadPersonalMemory();
    });
    $("profile-form").addEventListener("input", () => {
      $("profile-save-state").textContent = "有未保存修改";
    });
    document
      .querySelectorAll(".nav-button")
      .forEach((nav) =>
        nav.addEventListener("click", () => go(nav.dataset.view)),
      );
    document
      .querySelectorAll("[data-go]")
      .forEach((el) => el.addEventListener("click", () => go(el.dataset.go)));
    $("import-profile").addEventListener("click", async (event) => {
      const target = event.currentTarget;
      busy(target, true);
      try {
        app.profileDraft = await api("/api/example-profile");
        renderProfile();
        show("示例档案已载入表单，请检查后再保存。");
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("profile-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const target = $("save-profile");
      busy(target, true);
      try {
        const saved = await api("/api/profile", {
          method: "PUT",
          body: JSON.stringify({
            profile: readProfile(),
            expected_version: app.version,
          }),
        });
        app.profile = saved.data;
        app.profileDraft = null;
        app.version = saved.version;
        renderProfile();
        renderOverview();
        renderPlans();
        show("档案已保存。");
        document.dispatchEvent(new CustomEvent('fitness-state-change', {detail: {profile_version: app.version}}));
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("plan-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const target = $("generate-plan");
      busy(target, true);
      try {
        const plan = await api("/api/plans", {
          method: "POST",
          body: JSON.stringify({
            start_date: $("plan-date").value,
            mode: 'live',
          }),
        });
        app.plans.unshift(plan);
        app.plan = plan;
        renderPlans();
        show("计划草案已生成，请检查后确认。");
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("parse-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (app.feedbackDirty) {
        show("当前反馈有未保存修改，请先保存或撤销本次编辑。", true);
        return;
      }
      const target = $("parse-feedback");
      busy(target, true);
      try {
        const body = {text: $('feedback-text').value, date: $('feedback-date').value,
          timing: $('feedback-timing').value, parent_feedback_id: null};
        const signature = JSON.stringify(body);
        if (app.feedbackSubmission?.signature !== signature) app.feedbackSubmission = {
          signature, key: crypto.randomUUID()};
        const item = await api('/api/feedback/record', {method:'POST',
          body:JSON.stringify({...body, request_key:app.feedbackSubmission.key})});
        putFeedback(item);
        show('原文已保存，模型正在结合以往反馈与个人记忆理解。');
        await understandFeedback(item.id);
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("refresh-history").addEventListener("click", async (event) => {
      if (app.feedbackDirty) {
        show("请先保存或撤销当前反馈编辑，再刷新历史。", true);
        return;
      }
      const target = event.currentTarget;
      busy(target, true);
      try {
        const payload = await api("/api/state");
        app.feedback = payload.feedback;
        app.selectedFeedback =
          app.feedback.find((x) => x.id === app.selectedFeedback?.id) || null;
        renderFeedbackHistory();
        renderFeedbackEditor(app.selectedFeedback);
        renderOverview();
        await loadPersonalMemory();
        show("历史记录已刷新。");
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    ["knowledge-collection", "knowledge-status"].forEach((id) => {
      $(id).addEventListener("change", () => {
        app.reviewFilters.collection = $("knowledge-collection").value;
        app.reviewFilters.status = $("knowledge-status").value;
        renderKnowledgeList();
      });
    });
    $("knowledge-query").addEventListener("input", () => {
      app.reviewFilters.query = $("knowledge-query").value;
      renderKnowledgeList();
    });
    $("refresh-knowledge").addEventListener("click", async (event) => {
      const target = event.currentTarget;
      busy(target, true);
      try {
        await loadKnowledgeReview();
        show("知识候选已刷新。");
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("publish-knowledge").addEventListener("click", async (event) => {
      const target = event.currentTarget;
      busy(target, true);
      try {
        const result = await api("/api/knowledge/review/publish", { method: "POST" });
        show(
          "已发布 " + result.published_cards + " 张审核通过的卡片；当前 RAG manifest 共 " +
          result.manifest_items + " 条。",
        );
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("plan-date").value = today();
    $("feedback-date").value = today();
    try {
      const payload = await api("/api/state");
      app.sources = await api("/api/sources").catch(() => []);
      await loadDailyPlans().catch(() => {});
      await loadKnowledgeReview();
      renderAll(payload);
      $("plan-date").value = payload.today;
      $("feedback-date").value = payload.today;
      go(window.location.hash.slice(1) || "overview");
    } catch (error) {
      show(`无法连接本地服务：${error.message}`, true);
      renderProfile();
    }
  });
}
