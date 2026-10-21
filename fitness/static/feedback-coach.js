(function (global) {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
  function mergeExerciseEdits(rows, edits) {
    const results = list(rows).map(row => ({...row}));
    list(edits).forEach(edit => {
      if (results[edit.index] && ['weight_kg','rpe'].includes(edit.field)) results[edit.index][edit.field] = edit.value;
    });
    return results.filter(result => result.weight_kg != null || result.rpe != null || list(result.sets).length
      || result.form_notes || result.goal_completed != null);
  }
  function render(root, item, handlers = {}, doc = document) {
    root.replaceChildren();
    const make = (tag, text, className) => {
      const el = doc.createElement(tag); el.textContent = text || '';
      if (className) el.className = className;
      return el;
    };
    const button = (text, fn) => {
      const el = make('button', text, 'button secondary'); el.type = 'button';
      el.addEventListener('click', fn); return el;
    };
    const panel = make('section', '', 'card feedback-response');
    panel.append(make('p', `${item.date || ''} · ${item.coaching.timing === 'remaining' ? '调整剩余安排' : '日终复盘'}`, 'metadata'),
      make('p', `原始记录：${item.raw_text || ''}`, 'plan-summary'));
    const coach = item.coaching, data = coach.data || {};
    const facts = coach.fact_status || {};
    const factNames = {weight_kg:'体重',sleep_hours:'睡眠',training_completed:'训练完成状态',
      diet_followed_plan:'饮食执行状态',exercise_results:'动作表现',intake_kcal:'摄入热量'};
    if (list(facts.ignored_fields).length) panel.append(make('p',
      `以下信息未能可靠识别，尚未用于统计：${facts.ignored_fields.map(x => factNames[x] || x).join('、')}。可以补充或更正。`, 'field-hint'));
    for (const [field, question, yes, no] of [
      ['training_completed','这条记录对应的整次训练是否全部完成？','训练已全部完成','训练尚未全部完成'],
      ['diet_followed_plan','这一天是否按饮食计划执行？','已按饮食计划执行','未按饮食计划执行']]) {
      if (facts[field]?.status === 'needs_confirmation' && handlers.confirmFacts) {
        panel.append(make('p', question));
        panel.append(button(yes, () => handlers.confirmFacts(item.id, item.revision, {[field]:true})),
          button(no, () => handlers.confirmFacts(item.id, item.revision, {[field]:false})));
      } else if (facts[field]?.status === 'confirmed') panel.append(make('p',
        `${factNames[field]}：${facts[field].value ? '已确认完成' : '已确认未完成'}。`, 'field-hint'));
    }
    if (list(item.data?.exercise_results).length) {
      const results = make('details'); results.append(make('summary','已记录的实际训练表现'));
      list(item.data.exercise_results).forEach(result => {
        results.append(make('p', `${result.exercise_name || result.exercise_id}${result.session_id ? ` · ${result.session_id}` : ''}`));
        list(result.sets).forEach((set, i) => results.append(make('p',
          `第${i+1}组：${set.reps}次 · ${set.weight_kg == null ? '重量未记录' : `${set.weight_kg} kg`}${set.rpe == null ? '' : ` · RPE ${set.rpe}`}${set.completed === false ? ' · 未完成' : ''}`)));
        if (!list(result.sets).length) results.append(make('p', `${result.weight_kg == null ? '重量未记录' : `${result.weight_kg} kg`}${result.rpe == null ? '' : ` · RPE ${result.rpe}`}`));
        if (result.form_notes) results.append(make('p',`动作质量：${result.form_notes}`));
        if (result.goal_completed != null) results.append(make('p',`本动作目标：${result.goal_completed ? '达到' : '未达到'}`));
      });
      panel.append(results);
    }
    if (coach.status !== 'ready') {
      const message = coach.status === 'processing' ? '原文已保存，模型正在结合历史理解。稍后可刷新查看。'
        : coach.status === 'stale' ? '原文已保存；这条反馈的数据已更正，之前的理解需要重新评估。'
        : coach.status === 'saved' ? '原文已保存，等待模型理解。'
        : '原文已保存，但模型尚未完成理解，记忆和计划没有因此更新。';
      panel.append(make('p', message));
      if (handlers.retry) panel.append(button('重试模型理解', () => handlers.retry(item.id, coach.status === 'stale')));
      root.append(panel); return;
    }
    panel.append(make('h2', '结合你的反馈'), make('p', data.reply, 'feedback-narrative'));
    if (list(data.suggestions).length) {
      const ul = make('ul'); list(data.suggestions).forEach(s => ul.append(make('li', s))); panel.append(ul);
    }
    const decision = data.decision || {}, update = coach.planning_update || {};
    const questions = [...new Set([...list(data.questions), ...list(update.questions)])];
    const reply = make(handlers.followup ? 'form' : 'section', '', 'feedback-reply');
    if (questions.length) {
      reply.append(make('h3', '想进一步了解'));
      questions.forEach(q => reply.append(make('p', q)));
    }
    if (handlers.followup) {
      const label = make('label', questions.length ? '回答以上问题' : '补充这条反馈');
      const input = make('textarea'); input.rows = 3; input.maxLength = 4000; input.required = true;
      input.value = handlers.replyDraft || '';
      input.addEventListener('input', () => handlers.changeDraft?.(input.value));
      label.append(input);
      const submit = make('button', '提交补充并获取回应', 'button'); submit.type = 'submit';
      const status = make('p', '', 'field-hint'); status.setAttribute('role', 'status');
      reply.append(label, status, submit);
      reply.addEventListener('submit', async event => {
        event.preventDefault();
        const answer = String(input.value || '').trim();
        if (!answer || submit.disabled) return;
        submit.disabled = true; status.textContent = '正在保存补充并获取回应…';
        try { await handlers.followup(item.id, answer); }
        catch (error) { status.textContent = `补充未提交成功，内容已保留。${error.message}`; }
        finally { submit.disabled = false; }
      });
    }
    if (questions.length || handlers.followup) panel.append(reply);
    const status = update.status;
    const labels = {none: '当天计划保留。', updated: `${update.date || ''} 的安排已更新。`,
      draft: `已生成 ${update.date || ''} 起的长期计划草稿，请到“长期计划”检查并确认。`,
      pending: '计划调整待执行，可点击下方按钮继续。', applying: '计划调整正在处理。若之前的处理已中断，可检查并恢复；运行中的任务不会重复执行。',
      failed: `计划调整未完成，原有计划保留。${update.message || ''}`};
    panel.append(make('h3', '后续安排'), make('p', decision.reason), make('p', labels[status] || '当天计划保留。'));
    if (status === 'failed' && handlers.retryPlan) panel.append(button('重试计划调整', () => handlers.retryPlan(item.id)));
    if (['pending','applying'].includes(status) && handlers.retryPlan) panel.append(button('检查并恢复计划调整', () => handlers.retryPlan(item.id)));
    if (status === 'draft') {
      const link = make('a', '查看长期计划草稿', 'text-button');
      link.href = update.plan_id ? `#plan-${encodeURIComponent(update.plan_id)}` : '#plan'; panel.append(link);
    }
    const memoryLabels = {failed: '本次个人记忆未更新，保留之前的版本；原始反馈和本次回应仍已保存。',
      unchanged: '模型判断本次没有需要新增或修改的个人记忆。',
      compacted: '个人记忆已整理并压缩，原始反馈和旧记忆版本继续保留。', updated: '个人记忆已整理，保留原文引用。'};
    panel.append(make('p', memoryLabels[coach.memory_status] || '本次无需新增记忆。', 'field-hint'));
    if (coach.memory_status === 'failed' && handlers.retry) panel.append(button('重新理解并整理记忆', () => handlers.retry(item.id, true)));
    if (list(data.memory_updates).length) {
      const detail = make('details'), summary = make('summary', coach.memory_status === 'failed' ? '查看未保存的记忆候选' : '查看本次记忆整理'); detail.append(summary);
      list(data.memory_updates).forEach(entry => detail.append(make('p', `${entry.text}（${entry.category === 'pattern' ? '模型归纳，待验证' : '用户报告/待确认信息'}）`)));
      panel.append(detail);
    }
    root.append(panel);
  }
  function renderMemory(root, memory, doc = document, handlers = {}) {
    root.replaceChildren();
    const make = (tag, text) => { const e = doc.createElement(tag); e.textContent = text; return e; };
    root.append(make('p', `记忆版本 ${memory.version || 0} · 约 ${memory.estimated_tokens || 0} / ${memory.budget_tokens || 6000} 上下文预算。原始反馈一直保留。`));
    if (list(memory.stale_keys).length) root.append(make('p', '部分记忆的来源已更正，待重新理解；普通条目暂停使用，未明确解除的限制继续保留。'));
    if (list(memory.expired_keys).length) root.append(make('p', `${memory.expired_keys.length}条临时信息已过期，不再用于当前规划，原始记录保留。`));
    if (!list(memory.entries).length) root.append(make('p', '还没有有效的个人记忆；提交反馈后由模型逐步整理。'));
    const names = {fact:'报告事实',preference:'偏好',restriction:'限制',question:'待确认',pattern:'模型归纳（待验证）'};
    list(memory.entries).forEach(entry => {
      const detail = make('details', ''); detail.append(make('summary', `${names[entry.category] || entry.category} · ${entry.text}`));
      if (entry.event_date) detail.append(make('p', `事件日期：${entry.event_date}${entry.expires_on ? ` · 有效至 ${entry.expires_on}` : ''}`));
      if (entry.retention === 'long_term') detail.append(make('p', '长期保留，后续计划会继续参考；可通过补充反馈更正。'));
      if (entry.verification === 'legacy_unverified') detail.append(make('p','旧记忆，原文依据待核实；可通过补充反馈更正。'));
      if (entry.verification === 'source_changed_recheck') detail.append(make('p','来源已更正，待重新理解；限制保留到明确解除。'));
      if (entry.verification === 'user_confirmed') detail.append(make('p','这条偏好已由你明确确认。'));
      if (list(entry.supersedes).length) detail.append(make('p',`已替代：${entry.supersedes.join('、')}`));
      list(entry.evidence).forEach(e => detail.append(make('p', `原文依据：“${e.quote}”`)));
      if (entry.category === 'preference' && handlers.confirmPreference) {
        for (const [label, action] of [['确认这条偏好','confirm'],['不再采用这条偏好','retire']]) {
          if (action === 'confirm' && entry.verification === 'user_confirmed') continue;
          const button = make('button',label); button.type='button'; button.className='button secondary';
          button.addEventListener('click', () => handlers.confirmPreference(entry.key,memory.version,action));
          detail.append(button);
        }
      }
      const sources = make('p', '来源：');
      list(entry.sources).forEach(source => {
        const link = make('a', `${source.feedback_id.slice(0,8)} · 修订 ${source.revision} `);
        link.href = `#feedback-${encodeURIComponent(source.feedback_id)}`;
        link.dataset.feedbackId = source.feedback_id; sources.append(link);
      });
      detail.append(sources); root.append(detail);
    });
  }
  const api = {render, renderMemory, mergeExerciseEdits};
  if (typeof module !== 'undefined') module.exports = api;
  else global.FeedbackCoachUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
