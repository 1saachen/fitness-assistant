function preservedMode(current, payload) {
  const available = payload.available_modes || ['demo'];
  return available.includes(current) ? current : (payload.mode || 'demo');
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
    feedback: [],
    trends: null,
    plan: null,
    selectedFeedback: null,
    mode: "demo",
    knowledgeStatus: "unknown",
    feedbackDirty: false,
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
      primary: "general_health",
      secondary: [],
      deadline_negotiable: true,
      target_date: null,
      target_weight_kg: null,
      target_body_fat_percent: null,
    },
    training: {
      experience_years: null,
      available_sessions_per_week: null,
      session_duration_minutes: null,
      gym_access: null,
      available_equipment: null,
      preferred_weekdays: null,
      current_routine: null,
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
        ["training.available_sessions_per_week", "每周训练次数", "number"],
        ["training.session_duration_minutes", "每次时长（分钟）", "number"],
        ["training.gym_access", "有健身房", "boolean"],
        ["training.current_routine", "当前训练安排", "text"],
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
      const grid = document.createElement("div");
      grid.className = "field-grid";
      defs.forEach(([path, label, type, options]) => {
        const wrap = document.createElement("label");
        wrap.textContent = label;
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
            "personal.height_cm",
            "personal.weight_kg",
          ].includes(path)
        )
          input.required = true;
        if (
          [
            "personal.age_years",
            "training.available_sessions_per_week",
            "training.session_duration_minutes",
          ].includes(path)
        )
          input.step = "1";
        if (path === "goals.deadline_negotiable") {
          input.required = true;
          input.options[0].disabled = true;
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
    if (!["overview", "profile", "plan", "feedback", "knowledge"].includes(view))
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
    window.location.hash = view;
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
      : "告诉我们你的目标、可用时间与饮食偏好。";
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
            `${app.profile.training.available_sessions_per_week ?? "未知"} 次`,
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
          ["本周计划", "等待生成", "保存档案后开始"],
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
          "生成本周计划",
          app.plans.length ? "已有计划记录，可继续查看" : "根据档案生成草案",
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
    card.append(head, node("p", data.summary, "plan-summary"));
    card.append(
      node(
        "p",
        `${fmt(plan.start_date)} 起 · ${plan.mode === 'live' ? '在线辅助草案' : '演示草案'} · 使用档案版本 ${plan.profile_version}`,
        "metadata",
      ),
      renderExportActions("plan", plan.id),
    );
    const planStatusMessage = knowledgeStatusMessage(plan.trace?.knowledge_status);
    if (planStatusMessage) card.append(node("p", planStatusMessage, "notice-inline"));
    if (plan.trace?.provider?.status === 'fallback') card.append(node('p', '在线模型未完成，已使用本地规则生成。', 'notice-inline'));
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
    const nutrition = document.createElement("div");
    nutrition.className = "nutrition-grid";
    data.nutrition.meal_options.forEach((meal) => {
      const section = document.createElement("section");
      section.append(node("h3", meal.meal));
      const list = document.createElement("ul");
      meal.suggestions.forEach((x) => list.append(node("li", x)));
      section.append(list);
      nutrition.append(section);
    });
    card.append(
      nutrition,
      node("p", data.nutrition.budget_note, "notice-inline"),
    );
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
    card.append(...renderPlanContextSections(data, app.sources));
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
        `${fmt(item.date)} · ${item.status === "confirmed" ? "已确认" : "草稿"}\n${item.data?.training_summary || item.raw_text}`,
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
  function renderTrends() {
    const root = $("trend-metrics");
    root.replaceChildren();
    if (!app.trends) {
      root.append(node("div", "趋势数据暂不可用。", "empty-state"));
      return;
    }
    const window = app.trends.window;
    $("trend-range").textContent =
      `${window.start_date} 至 ${window.end_date} · ${app.trends.record_count} 条已确认反馈`;
    [
      "sleep_hours",
      "weight_kg",
      "fatigue_reports",
      "training_completion",
      "diet_execution",
    ].forEach((key) => {
      const presentation = trendMetricPresentation(key, app.trends.metrics?.[key]);
      const card = node("article", "", `trend-metric${presentation.insufficient ? " insufficient" : ""}`);
      card.append(
        node("span", presentation.label),
        node("strong", presentation.value),
        node("small", presentation.detail),
      );
      if (presentation.insufficient) card.append(node("small", "数据不足"));
      root.append(card);
    });
    $("trend-message").textContent =
      "各指标只使用自身的非空样本；单条记录不会被判定为长期趋势。";
  }
  async function loadTrends() {
    const days = Number($("trend-window").value || 7);
    const endDate = $("feedback-date").value || today();
    app.trends = await api(
      `/api/history/trends?days=${encodeURIComponent(days)}&end_date=${encodeURIComponent(endDate)}`,
    );
    renderTrends();
  }
  function renderFeedbackEditor(item) {
    app.feedbackDirty = false;
    const root = $("feedback-editor");
    root.replaceChildren();
    if (!item) return;
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
          const confirmed = await api(`/api/feedback/${item.id}/confirm`, {
            method: "POST",
            body: JSON.stringify({ data, expected_revision: item.revision }),
          });
          app.feedback = app.feedback.map((x) =>
            x.id === confirmed.id ? confirmed : x,
          );
          app.selectedFeedback = confirmed;
          renderFeedbackHistory();
          renderFeedbackEditor(confirmed);
          renderOverview();
          loadTrends().catch(() => {
            app.trends = null;
            renderTrends();
          });
          show("反馈已保存。");
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
              body: JSON.stringify({ mode: $("mode").value }),
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
      if (item.trace?.provider?.status === 'fallback') advice.append(node('p', '在线模型未完成，已回退为本地规则建议。', 'notice-inline'));
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
    $("mode").value = app.mode;
    [...$("mode").options].find(option => option.value === 'live').textContent = '在线模型';
    [...$("mode").options].forEach((option) => {
      option.disabled = !(payload.available_modes || ["demo"]).includes(
        option.value,
      );
    });
    $("import-profile").disabled = !payload.example_available;
    $("today-label").textContent = `今天是 ${payload.today || today()}`;
    $("mode-note").textContent =
      app.mode === "live"
        ? `在线模型：${payload.model || "已配置"}。生成前仍会要求你确认草稿。`
        : "演示模式：使用本地规则生成，不调用外部模型。";
    const globalKnowledgeStatus = knowledgeStatusMessage(app.knowledgeStatus);
    if (globalKnowledgeStatus) $("mode-note").textContent += ` ${globalKnowledgeStatus}`;
    renderProfile();
    renderOverview();
    renderPlans();
    renderFeedbackHistory();
    renderFeedbackEditor(app.selectedFeedback);
    renderTrends();
    renderKnowledgeList();
    renderKnowledgeDetail();
  }
  document.addEventListener("DOMContentLoaded", async () => {
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
            renderAll(await api('/api/state')); await loadTrends();
            show('历史反馈已导入。');
          } catch(error) {show(error.message, true);} finally {busy(button, false);}
        }));
      } catch(error) {show(error.message, true);} finally {busy(target, false);}
    });
    window.addEventListener("hashchange", () =>
      go(window.location.hash.slice(1)),
    );
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
    $("mode").addEventListener("change", () => {
      app.mode = $("mode").value;
      $("mode-note").textContent = app.mode === "live"
        ? "在线模型：使用本地工具读取事实；失败或输出未通过校验时回退本地结果，并显示原因。"
        : "演示模式：使用本地规则生成，不调用外部模型。";
      const status = knowledgeStatusMessage(app.knowledgeStatus);
      if (status) $("mode-note").textContent += ` ${status}`;
      show(
        app.mode === "live"
          ? "已切换到在线模型；失败时将保留本地结果并显示回退原因。"
          : "已切换到演示模式。",
      );
    });
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
            mode: $("mode").value,
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
        const item = await api("/api/feedback/parse", {
          method: "POST",
          body: JSON.stringify({
            text: $("feedback-text").value,
            date: $("feedback-date").value,
            mode: $("mode").value,
          }),
        });
        app.feedback.unshift(item);
        app.selectedFeedback = item;
        renderFeedbackHistory();
        renderFeedbackEditor(item);
        renderOverview();
        show("反馈草稿已生成，请核对字段后保存。");
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
        await loadTrends().catch(() => {
          app.trends = null;
          renderTrends();
        });
        show("历史记录已刷新。");
      } catch (error) {
        show(error.message, true);
      } finally {
        busy(target, false);
      }
    });
    $("trend-window").addEventListener("change", async () => {
      try {
        await loadTrends();
      } catch (error) {
        app.trends = null;
        renderTrends();
        show(`无法加载趋势：${error.message}`, true);
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
      await loadKnowledgeReview();
      renderAll(payload);
      $("plan-date").value = payload.today;
      $("feedback-date").value = payload.today;
      await loadTrends().catch(() => {
        app.trends = null;
        renderTrends();
      });
      go(window.location.hash.slice(1) || "overview");
    } catch (error) {
      show(`无法连接本地服务：${error.message}`, true);
      renderProfile();
    }
  });
}
