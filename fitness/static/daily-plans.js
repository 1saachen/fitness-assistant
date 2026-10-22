(function () {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
  const text = value => value == null ? '未记录' : String(value);
  const goals = {fat_loss: '减脂', muscle_gain: '增肌', general_health: '保持健康'};
  const actions = {train: '按计划训练', rest: '休息', defer: '顺延训练', skip: '跳过本次', reduce: '降低训练量', substitute: '替换动作', pause: '暂停相关训练'};
  const areas = {shoulder: '肩部', knee: '膝部', back: '腰背', wrist: '手腕', elbow: '肘部', hip: '髋部', unspecified: '待明确部位'};

  function planningError(payload, status) {
    const detail = payload.detail;
    const base = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(x => x.msg).join('；') : detail?.message || `请求失败（${status}）`;
    const extra = detail?.status === 'failed' && !base.includes('原有计划尚未按本次条件更新') ? '原有计划尚未按本次条件更新。' : '';
    const memory = detail?.conditions_memory?.message;
    const error = new Error([base, ...list(detail?.questions), memory && !base.includes(memory) ? memory : '', extra].filter(Boolean).join('\n'));
    error.detail = detail;
    error.httpStatus = status;
    return error;
  }

  async function readPlanStream(response, onEvent) {
    const reader = response.body?.getReader();
    if (!reader) throw new Error('无法读取计划生成进度，请检查计划历史后重试。');
    const decoder = new TextDecoder('utf-8', {fatal: true});
    let buffer = '';
    try {
      while (true) {
        const {done, value} = await reader.read();
        buffer += decoder.decode(value, {stream: !done});
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          let name = 'message';
          const data = [];
          for (const line of frame.split(/\r?\n/)) {
            if (line.startsWith('event:')) name = line.slice(6).trim();
            if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
          }
          if (!data.length) continue;
          const payload = JSON.parse(data.join('\n'));
          if (name === 'error') throw planningError({detail: payload.detail}, payload.status);
          if (name === 'result') return payload;
          onEvent(name, payload);
        }
        if (done) throw new Error('生成连接中断，草稿尚未完成。请检查计划历史后重试。');
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function parseCycleLabels(value) {
    const labels = String(value || '').split(/[,，、\n]/).map(x => x.trim()).filter(Boolean);
    if (!labels.length || labels.length > 14 || labels.some(x => x.length > 200))
      throw new Error('训练循环需要 1 至 14 个步骤，每个步骤不超过 200 字。');
    return labels;
  }
  function shouldRefreshToday(state, date, profileVersion) {
    const active = list(state.long_term_plans).find(plan => plan.status === 'confirmed' && plan.start_date <= date);
    return date === state.today && Boolean(active) && !list(state.daily_plans).some(plan => plan.date === date)
      && (profileVersion == null || active.profile_version === profileVersion);
  }
  function node(doc, tag, content, className) {
    const el = doc.createElement(tag);
    if (content != null) el.textContent = String(content);
    if (className) el.className = className;
    return el;
  }
  function lines(doc, root, title, values, className = '') {
    const rows = list(values).filter(Boolean);
    if (!rows.length) return;
    root.append(node(doc, 'h3', title));
    rows.forEach(value => root.append(node(doc, 'p', value, className)));
  }
  function button(doc, label, callback, disabled = false) {
    const el = node(doc, 'button', label, 'button secondary');
    el.type = 'button'; el.disabled = disabled;
    el.addEventListener('click', callback);
    return el;
  }
  function optionalQuestions(doc, root, groups) {
    const questions = [...new Set(groups.flatMap(list).filter(Boolean))];
    if (!questions.length) return;
    const section = node(doc, 'section', null, 'field-hint');
    section.append(node(doc, 'h3', '可选补充'),
      node(doc, 'p', '以下问题不影响使用当前计划；愿意补充时，可在上方条件框回答后更新计划。'));
    questions.forEach(question => section.append(node(doc, 'p', question)));
    root.append(section);
  }
  function training(doc, root, step = {}) {
    root.append(node(doc, 'h3', `${step.label || '训练安排待生成'} · ${step.kind === 'rest' ? '恢复 / 休息' : '训练'}${step.estimated_minutes ? ` · 约 ${step.estimated_minutes} 分钟` : ''}`));
    list(step.exercises).forEach(exercise => {
      const prescription = [exercise.weight_kg != null ? `${exercise.weight_kg} kg` : null,
        exercise.target_rpe != null ? `目标 RPE ${exercise.target_rpe}` : null].filter(Boolean).join(' · ');
      root.append(node(doc, 'p',
        `${exercise.name || exercise.exercise_id}：${text(exercise.sets)} 组 × ${text(exercise.reps_min)}–${text(exercise.reps_max)} 次 · 组间休息 ${text(exercise.rest_seconds)} 秒${prescription ? ` · ${prescription}` : ''}`));
      if (exercise.notes) root.append(node(doc, 'p', exercise.notes, 'field-hint'));
    });
  }
  function nutrition(doc, root, data = {}, options = {}) {
    root.append(node(doc, 'h2', '饮食安排'));
    if (data.approach) root.append(node(doc, 'p', data.approach, 'plan-summary'));
    const target = data.daily_targets;
    if (target) {
      root.append(node(doc, 'p', `全天目标 ${text(target.calories_kcal)} 千卡 · 蛋白质 ${text(target.protein_g)}g · 脂肪 ${text(target.fat_g)}g · 碳水 ${text(target.carbs_g)}g`, 'nutrition-targets'));
      if (target.method) root.append(node(doc, 'p', `起始估算：${target.method} · 置信度 ${ {low: '低', medium: '中', high: '高'}[target.confidence] || '未记录' }`, 'metadata'));
      lines(doc, root, '估算条件', target.assumptions, 'field-hint');
    } else root.append(node(doc, 'p', '档案资料不足以估算个体化热量和宏量目标。', 'field-hint'));
    const grid = node(doc, 'div', null, 'nutrition-grid');
    list(data.meal_options).forEach(meal => {
      const section = node(doc, 'section');
      const completed = list(options.completed).includes(meal.meal);
      section.append(node(doc, 'h3', `${meal.meal}${completed ? ' · 已完成，保留原安排' : ''}`));
      list(meal.suggestions).forEach(value => section.append(node(doc, 'p', value)));
      if ([meal.estimated_kcal, meal.protein_g, meal.fat_g, meal.carbs_g].some(value => value != null))
        section.append(node(doc, 'p', `估算 ${text(meal.estimated_kcal)} 千卡 · 蛋白质 ${text(meal.protein_g)}g · 脂肪 ${text(meal.fat_g)}g · 碳水 ${text(meal.carbs_g)}g`, 'metadata'));
      if (meal.estimated_cost_cny != null) section.append(node(doc, 'p', `预计费用 ¥${meal.estimated_cost_cny}，以实际价格为准`, 'metadata'));
      lines(doc, section, '可替换选择', meal.alternatives);
      if (options.complete) section.append(button(doc, completed ? '已完成' : `记录${meal.meal}已完成`, () => options.complete(meal.meal), completed));
      grid.append(section);
    });
    root.append(grid);
    if (data.budget_note) root.append(node(doc, 'p', data.budget_note, 'field-hint'));
  }
  function supplements(doc, root, data, options = {}) {
    const plan = data.supplements;
    if (!plan) return;
    const section = node(doc, 'section');
    section.append(node(doc, 'h2', '补剂建议'));
    section.append(node(doc, 'p', plan.summary, 'plan-summary'));
    section.append(node(doc, 'p', plan.budget_note));
    if (options.knowledgeStatus && options.knowledgeStatus !== 'ok') section.append(node(doc, 'p',
      options.knowledgeStatus === 'capacity_exceeded' ? '补剂知识库超过本次处理容量，未生成新的补剂推荐。' : '补剂知识库暂不可用，未生成新的补剂推荐。', 'notice-inline'));
    section.append(node(doc, 'p', '知识卡获批仅代表允许引用，不代表科学共识；建议需结合适用条件，不构成个体服用剂量。', 'notice-inline'));
    const priorities = {consider: '可以考虑', conditional: '条件满足再考虑', not_needed: '目前没有必要', needs_review: '需要核实'};
    const evidence = {experience: '经验观点', limited: '有限证据', research: '研究标签', guideline: '指南标签'};
    const types = {creator_opinion: '创作者观点', research_summary: '研究摘要', professional_guidance: '专业指导', mixed: '混合来源'};
    list(plan.items).forEach(item => {
      const entry = node(doc, 'section');
      entry.append(node(doc, 'h3', item.name));
      entry.append(node(doc, 'p', priorities[item.priority] || '需要核实', 'pill'));
      if (item.current_product) entry.append(node(doc, 'p', `当前产品：${item.current_product}`, 'metadata'));
      entry.append(node(doc, 'p', item.reason));
      lines(doc, entry, '适用与核实条件', item.conditions);
      lines(doc, entry, '饮食替代', item.food_alternatives);
      lines(doc, entry, '注意事项与证据局限', item.cautions);
      if (!list(item.source_ids).length) entry.append(node(doc, 'p', '暂无已审核知识依据，需核实产品成分与适用性。', 'notice-inline'));
      list(item.source_ids).forEach(id => {
        const source = list(data.supplement_sources).find(row => row.id === id);
        if (!source) { entry.append(node(doc, 'p', '来源快照未记录，需重新核实。', 'metadata')); return; }
        const meta = source.metadata || {}, origin = source.source || {}, detail = node(doc, 'details');
        detail.append(node(doc, 'summary', `知识依据：${source.title} · ${types[meta.source_type] || '来源类型未记录'} · ${evidence[meta.evidence_level] || '证据未记录'}`));
        detail.append(node(doc, 'p', `来源主张：${text(meta.claim)}`));
        if (meta.explanation) detail.append(node(doc, 'p', meta.explanation));
        if (meta.safety_level) detail.append(node(doc, 'p', `安全边界：${meta.safety_level}`));
        detail.append(node(doc, 'p', `${text(origin.creator_name)} · ${text(origin.video_title)} · 来源原文仅供核对，不作为服用安排。`, 'metadata'));
        if (/^https?:\/\/[^\s]+$/i.test(origin.video_url || '')) {
          const link = node(doc, 'a', '查看来源视频');
          link.href = origin.video_url; link.target = '_blank'; link.rel = 'noopener noreferrer';
          detail.append(link);
        }
        entry.append(detail);
      });
      section.append(entry);
    });
    root.append(section);
  }
  function renderLongTerm(root, record, handlers = {}, doc = document) {
    root.replaceChildren();
    if (!record) { root.append(node(doc, 'p', '保存档案后生成长期计划，确认后即可安排每一天。', 'empty-state')); return; }
    const data = record.data || {}, card = node(doc, 'article', null, 'card');
    card.append(node(doc, 'h2', data.title || '长期计划'));
    card.append(node(doc, 'p', `版本 ${record.version} · ${record.status === 'confirmed' ? '已确认' : '草稿'} · 开始 ${record.start_date} · 档案版本 ${text(record.profile_version)}`, 'metadata'));
    const goal = data.goals || {};
    card.append(node(doc, 'p', `目标：${goals[goal.primary] || goal.primary || '未记录'}${goal.target_weight_kg != null ? ` · 目标体重 ${goal.target_weight_kg} kg` : ''}${goal.target_body_fat_percent != null ? ` · 目标体脂 ${goal.target_body_fat_percent}%` : ''}${goal.target_date ? ` · 目标日期 ${goal.target_date}` : ''}`));
    card.append(node(doc, 'h2', '训练循环'));
    if (data.summary) card.append(node(doc, 'p', data.summary, 'plan-summary'));
    lines(doc, card, '训练规划假设', data.assumptions);
    if (record.trace?.training_source) card.append(node(doc, 'p', `训练来源：${record.trace.training_source === 'model' ? '在线模型' : '旧版本地规则记录'}`, 'metadata'));
    if (record.trace?.nutrition_source) card.append(node(doc, 'p', `饮食来源：${record.trace.nutrition_source === 'model' ? '在线模型' : '旧版本地估算'}`, 'metadata'));
    card.append(node(doc, 'p', list(data.cycle).map(x => x.label).join(' → ') + ' → 循环', 'plan-summary'));
    list(data.cycle).forEach(step => { const section = node(doc, 'section'); training(doc, section, step); card.append(section); });
    nutrition(doc, card, data.nutrition);
    supplements(doc, card, data, {
      knowledgeStatus: record.trace?.supplement_provider?.knowledge_status});
    card.append(node(doc, 'h3', `下次复盘参考日期：${text(data.review_after)}`));
    lines(doc, card, '复盘原则', data.review_rules);
    lines(doc, card, '恢复安排', data.recovery_guidance);
    if (record.status !== 'confirmed' && handlers.confirm) card.append(button(doc, '确认并启用长期计划', () => handlers.confirm(record.id)));
    optionalQuestions(doc, card, [data.training_questions, data.nutrition?.questions, data.supplements?.questions]);
    root.append(card);
  }
  function renderDaily(root, record, handlers = {}, doc = document) {
    root.replaceChildren();
    if (!record) { root.append(node(doc, 'p', '这个日期还没有当天计划。请先确认长期计划，再生成当天安排。', 'empty-state')); return; }
    const data = record.data || {}, decision = data.decision || {}, card = node(doc, 'article', null, 'card');
    card.append(node(doc, 'h2', `${record.date} · 当天计划`));
    card.append(node(doc, 'p', `修订 ${record.revision} · 关联长期计划 ${record.long_term_id}`, 'metadata'));
    if (data.conditions) card.append(node(doc, 'p', `当天条件：${data.conditions}`));
    card.append(node(doc, 'h2', '训练与恢复'));
    if (decision.summary) card.append(node(doc, 'p', decision.summary, 'plan-summary'));
    lines(doc, card, '训练规划假设', decision.assumptions);
    card.append(node(doc, 'p', actions[decision.action] || decision.action || '待评估', 'pill'));
    training(doc, card, data.training);
    card.append(node(doc, 'p', data.training_completed === true ? '训练已完成' : data.training_completed === false ? '训练未完成' : '训练完成情况未记录', 'metadata'));
    lines(doc, card, '本次调整依据', decision.reasons);
    lines(doc, card, '持续生效的训练限制', list(decision.restrictions).filter(x => x.active !== false).map(x => typeof x === 'string' ? x : `${areas[x.area] || x.area || '训练限制'}：${x.reason || '待评估'}${x.source_date ? `（${x.source_date}）` : ''}`), 'notice-inline');
    if (handlers.release) list(decision.restrictions).filter(x => x.active !== false && x.area).forEach(restriction => {
      const detail = node(doc, 'details');
      detail.append(node(doc, 'summary', `更新${areas[restriction.area] || restriction.area}恢复情况`));
      const form = node(doc, 'form');
      const label = node(doc, 'label', '确认恢复情况：请说明当前是否已无症状，或提供专业人员允许恢复的意见。仍有伤痛时保留限制。');
      const input = node(doc, 'textarea'); input.rows = 2; input.minLength = 5; input.maxLength = 1000; input.required = true;
      label.append(input); form.append(label);
      const submit = node(doc, 'button', '确认恢复并重新评估', 'button secondary'); submit.type = 'submit'; form.append(submit);
      form.addEventListener('submit', event => {event.preventDefault(); const statement = String(input.value || '').trim(); if (statement.length >= 5 && statement.length <= 1000) return handlers.release(record.id, restriction.area, record.revision, statement);});
      detail.append(form); card.append(detail);
    });
    if (decision.provider) card.append(node(doc, 'p', `训练决策来源：${typeof decision.provider === 'string' ? decision.provider : ({demo: '旧版本地规则记录', ok: '在线模型', live: '在线模型', preserved: '保留已完成记录', fallback: '旧版本地回退记录', skipped_safety: '安全暂停'}[decision.provider.status] || decision.provider.status || '未记录')}${decision.provider.reason ? ` · ${decision.provider.reason}` : ''}`, 'metadata'));
    if (record.trace?.nutrition_source) card.append(node(doc, 'p', `饮食来源：${record.trace.nutrition_source === 'model' ? '在线模型' : '旧版本地估算'}`, 'metadata'));
    nutrition(doc, card, data.nutrition, {completed: data.completed_meals, complete: handlers.complete ? meal => handlers.complete(record.id, meal, record.revision) : null});
    card.append(node(doc, 'h2', '饮水与恢复'));
    if (data.water) {
      if (data.water.base_ml != null) card.append(node(doc, 'p', `基础饮水参考 ${text(data.water.base_ml)} 毫升`, 'nutrition-targets'));
      card.append(node(doc, 'p', data.water.note));
    }
    lines(doc, card, '恢复安排', data.recovery_guidance);
    lines(doc, card, '长期计划复盘建议', data.review_suggestions, 'notice-inline');
    optionalQuestions(doc, card, [decision.questions, data.nutrition?.questions]);
    root.append(card);
  }

  if (typeof module !== 'undefined') module.exports = {parseCycleLabels, shouldRefreshToday, renderLongTerm, renderDaily, planningError, readPlanStream};
  if (typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const get = id => document.getElementById(id);
    if (!get('daily-form')) return;
    let state = {long_term_plans: [], daily_plans: []}, selectedLong = null, profileVersion, pending = Promise.resolve();
    const followups = new Map();
    const notifiedProfileVersions = new Set();
    const displayedQuestions = {'long-term': [], daily: []};
    const pendingQuestions = {'long-term': [], daily: []};
    const followupKey = (url, body) => `${url}:${body?.date || body?.start_date || ''}:${body?.mode || ''}`;
    const localToday = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
    get('daily-date').value = localToday();
    const message = (value, error = false, scope = 'daily') => {
      const el = get(scope === 'long-term' ? 'planning-message' : 'daily-message');
      el.textContent = value || ''; el.hidden = !value; el.className = error ? 'notice-inline' : 'field-hint';
    };
    function showMemory(scope, notice) {
      const root = get(`${scope}-memory`); root.replaceChildren(); root.hidden = !notice;
      if (!notice) return;
      root.append(node(document, 'span', notice.message + ' '));
      if (list(notice.profile_updated_fields).length && notice.profile_version
          && !notifiedProfileVersions.has(notice.profile_version)) {
        notifiedProfileVersions.add(notice.profile_version);
        document.dispatchEvent(new CustomEvent('fitness-profile-synced', {detail: {profile_version: notice.profile_version}}));
      }
      if (notice.feedback_id) {
        const label = notice.status === 'failed' ? '查看原文并重试'
          : notice.profile_sync_checked === true ? '查看原文与记忆' : '查看原文与档案同步状态';
        const link = node(document, 'a', label);
        link.href = `#feedback-${encodeURIComponent(notice.feedback_id)}`; root.append(link);
      }
    }
    function showQuestions(scope, groups = []) {
      const root = get(`${scope}-questions`); root.replaceChildren();
      const questions = [...new Set(pendingQuestions[scope])];
      displayedQuestions[scope] = questions.length ? questions : [...new Set(groups.flatMap(list))];
      root.hidden = !questions.length;
      if (questions.length) {
        root.append(node(document, 'h3', '生成前需要确认'));
        root.append(node(document, 'p', '以下信息影响安全规划，请尽量一次回答；不确定的内容可以说明“暂不清楚”。'));
        questions.forEach(question => root.append(node(document, 'p', question)));
      }
      get(`${scope}-conditions-label`).textContent = questions.length ? '回答以上问题，也可以补充其他条件' : scope === 'daily' ? '当天条件' : '补充条件';
      get(`${scope}-conditions`).placeholder = questions.length ? '可以按顺序回答；不确定的内容请说明“暂不清楚”。'
        : scope === 'daily' ? '例如今天很累，想休息；午餐在食堂，预算15元。' : '可以补充档案里没填的信息；也可以留空，规划时会按需询问。';
      get(`${scope}-submit`).textContent = questions.length ? '提交补充并继续生成' : scope === 'daily' ? '更新当天计划' : '生成长期计划草案';
    }
    const request = async (url, body) => {
      const scope = url.startsWith('/api/long-term-plans') ? 'long-term' : 'daily';
      const key = followupKey(url, body);
      const followup = followups.get(key);
      if (body && followup) {
        body = {...body, expected_snapshot_token: followup.snapshot_token};
        if (url === '/api/long-term-plans' && !body.start_date && followup.start_date)
          body.start_date = followup.start_date;
      }
      const generating = body && ['/api/long-term-plans', '/api/daily-plans'].includes(url);
      if (generating && body.mode === 'live' && body.conditions?.trim()) {
        body = {...body, answered_questions: [...displayedQuestions[scope]]};
      }
      const streaming = generating && body.mode === 'live';
      const preview = generating ? get(url === '/api/long-term-plans' ? 'long-term-preview' : 'daily-preview') : null;
      let status;
      if (preview && streaming) {
        preview.hidden = false;
        status = node(document, 'p', '正在生成计划；校验完成后显示最终内容。', 'field-hint');
        preview.replaceChildren(status);
      } else if (preview) preview.hidden = true;
      try {
        const response = await fetch(streaming ? `${url}/stream` : url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', ...(streaming ? {Accept: 'text/event-stream'} : {})}, ...(body === null ? {} : {body: JSON.stringify(body)})});
        const payload = response.ok && response.headers?.get('content-type')?.includes('text/event-stream')
          ? await readPlanStream(response, (event, data) => {
            if (event === 'memory') showMemory(scope, data);
            if ((event === 'status' || event === 'phase') && status) status.textContent = data.message;
          }) : await response.json();
        if (!response.ok) throw planningError(payload, response.status);
        followups.delete(key);
        if (generating) pendingQuestions[scope] = [];
        if (payload.trace?.conditions_memory) showMemory(scope, payload.trace.conditions_memory);
        if (preview) preview.hidden = true;
        return payload;
      } catch (error) {
        if (error.detail?.conditions_memory) showMemory(scope, error.detail.conditions_memory);
        if (url.startsWith('/api/long-term-plans') || url.startsWith('/api/daily-plans')) error.planningScope = scope;
        if (error.detail?.status === 'needs_input') {
          pendingQuestions[scope] = list(error.detail.questions);
          error.message = error.detail.message || '请回答以下问题后继续生成。';
          showQuestions(scope);
          if (preview) preview.hidden = true;
        }
        if (error.detail?.status === 'needs_input' && error.detail.snapshot_token)
          followups.set(key, {snapshot_token: error.detail.snapshot_token, start_date: error.detail.start_date});
        if (error.httpStatus === 409) followups.delete(key);
        if (status) status.textContent = '本次生成未完成，以下内容仍是草稿。' + error.message;
        throw error;
      }
    };
    function run(work, scope = 'daily') {
      pending = pending.catch(() => {}).then(async () => {
        const controls = [...document.querySelectorAll('#long-term-form input, #long-term-form textarea, #long-term-form button, #long-term-content button, #daily-form input, #daily-form textarea, #daily-form button, #daily-content button, #daily-history button, #long-term-history button')].map(el => [el, el.disabled]);
        controls.forEach(([el]) => { el.disabled = true; });
        try { await work(); } catch (error) { message(error.message, true, error.planningScope || scope); }
        finally { controls.forEach(([el, disabled]) => { el.disabled = disabled; }); }
      });
      return pending;
    }
    async function load() { state = await request(`/api/planning/state?date=${encodeURIComponent(get('daily-date').value)}`); profileVersion = state.profile_version ?? profileVersion; render(); }
    async function generate(conditions) {
      await request('/api/daily-plans', {date: get('daily-date').value, conditions, mode: 'live'});
      await load(); message('当天计划已更新，已完成的餐次与训练会保留。');
    }
    async function refresh(auto = false) {
      await load();
      if (auto && state.model_configured && shouldRefreshToday(state, get('daily-date').value, profileVersion)) {
        await generate(null);
      }
    }
    function render() {
      const records = list(state.long_term_plans), long = records.find(x => x.id === selectedLong) || records[0];
      selectedLong = long?.id;
      get('long-term-submit').disabled = state.model_configured !== true;
      get('daily-submit').disabled = state.model_configured !== true;
      showMemory('long-term', long?.trace?.conditions_memory);
      showQuestions('long-term', [long?.data?.training_questions, long?.data?.nutrition?.questions, long?.data?.supplements?.questions]);
      const longHistory = get('long-term-history'); longHistory.replaceChildren();
      records.forEach(record => longHistory.append(button(document, `${record.start_date} · 版本 ${record.version} · ${record.status === 'confirmed' ? '已确认' : '草稿'}`, () => { selectedLong = record.id; render(); })));
      renderLongTerm(get('long-term-content'), long, {confirm: id => run(async () => {
        await request(`/api/long-term-plans/${encodeURIComponent(id)}/confirm`, null);
        await refresh(!get('view-daily').hidden); message('长期计划已确认。', false, 'long-term');
      }, 'long-term')});
      const daily = list(state.daily_plans).find(x => x.date === get('daily-date').value);
      showMemory('daily', daily?.trace?.conditions_memory);
      showQuestions('daily', [daily?.data?.decision?.questions, daily?.data?.nutrition?.questions]);
      renderDaily(get('daily-content'), daily, {release: (id, area, expected_revision, confirmation_text) => run(async () => {
        const conditions = get('daily-conditions').value;
        await request(`/api/daily-plans/${encodeURIComponent(id)}/restrictions/release`, {area, expected_revision, confirmation_text});
        await load();
        try {
          await generate(conditions);
          message('恢复确认已保存，当天训练安排已重新评估。');
        } catch (error) {
          error.message = '恢复确认已保存，但训练安排重新评估未完成。' + error.message;
          throw error;
        }
      }), complete: (id, meal, expected_revision) => run(async () => {
        await request(`/api/daily-plans/${encodeURIComponent(id)}/meals/complete`, {meal, expected_revision});
        await load(); message(`${meal}已记录为完成，后续更新保留这餐。`);
      })});
      // Preserve an in-progress edit while state changes in another part of the page.
      if (!get('daily-conditions').dataset.dirty) get('daily-conditions').value = daily?.data?.conditions || '';
      const history = get('daily-history'); history.replaceChildren();
      list(state.daily_plans).forEach(record => history.append(button(document, `${record.date} · 修订 ${record.revision}`, () => run(async () => {
        get('daily-date').value = record.date; get('daily-conditions').dataset.dirty = ''; await load();
      }))));
    }
    get('long-term-form').addEventListener('submit', event => { event.preventDefault();
      const body = {mode: 'live'};
      if (get('long-term-conditions')?.value) body.conditions = get('long-term-conditions').value;
      run(async () => { message('', false, 'long-term'); const created = await request('/api/long-term-plans', body); selectedLong = created.id; await load(); message('长期计划草案已生成，请检查后确认。', false, 'long-term'); }, 'long-term');
    });
    get('daily-form').addEventListener('submit', event => { event.preventDefault(); const conditions = get('daily-conditions').value;
      run(async () => { message(''); await generate(conditions); get('daily-conditions').dataset.dirty = ''; });
    });
    get('daily-conditions').addEventListener('input', () => { get('daily-conditions').dataset.dirty = 'true'; });
    get('daily-date').addEventListener('change', () => { followups.clear(); pendingQuestions.daily = []; message(''); get('daily-conditions').dataset.dirty = ''; run(() => refresh(get('daily-date').value === state.today)); });
    get('daily-today').addEventListener('click', () => { followups.clear(); pendingQuestions.daily = []; message(''); get('daily-date').value = state.today || localToday(); get('daily-conditions').dataset.dirty = ''; run(() => refresh(true)); });
    document.addEventListener('fitness-view-change', event => {
      if (event.detail?.view === 'daily') run(() => refresh(true));
      if (event.detail?.view === 'plan' && event.detail.long_term_id) run(async () => {
        selectedLong = event.detail.long_term_id;
        await load();
        const found = list(state.long_term_plans).some(plan => plan.id === event.detail.long_term_id);
        if (!found) {
          get('long-term-content').replaceChildren();
          get('long-term-questions').hidden = true;
        }
        message(found
          ? '已打开本次生成的长期计划草稿，请检查后确认。' : '这份长期计划已不存在，请检查计划历史。',
          !found, 'long-term');
      }, 'long-term');
    });
    document.addEventListener('fitness-state-change', event => {
      profileVersion = event.detail?.profile_version;
      run(async () => {
        if (event.detail?.feedback_saved || event.detail?.planning_update) {
          await load();
          if (event.detail.planning_update?.status === 'failed') message('反馈已保存；计划调整未完成。' + (event.detail.planning_update.message || '') + ' ' + list(event.detail.planning_update.questions).join(' '), true);
        } else await refresh(!get('view-daily').hidden);
      });
    });
    run(() => refresh(!get('view-daily').hidden));
  });
})();
