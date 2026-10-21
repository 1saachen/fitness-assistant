(function (global) {
  'use strict';
  const list = value => Array.isArray(value) ? value : [];
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
    if (list(data.questions).length) {
      panel.append(make('h3', '想进一步了解'));
      list(data.questions).forEach(q => panel.append(make('p', q)));
    }
    if (handlers.followup) panel.append(button(list(data.questions).length ? '回答这些问题' : '补充这条反馈', () => handlers.followup(item.id)));
    const decision = data.decision || {}, update = coach.planning_update || {};
    const status = update.status;
    const labels = {none: '当天计划保留。', updated: `${update.date || ''} 的安排已更新。`,
      draft: `已生成 ${update.date || ''} 起的长期计划草稿，请到“长期计划”检查并确认。`,
      pending: '计划调整待执行，可点击下方按钮继续。', applying: '计划调整正在处理。若之前的处理已中断，可检查并恢复；运行中的任务不会重复执行。',
      failed: `计划调整未完成，原有计划保留。${update.message || ''}`};
    panel.append(make('h3', '后续安排'), make('p', decision.reason), make('p', labels[status] || '当天计划保留。'));
    list(update.questions).forEach(q => panel.append(make('p', q)));
    if (status === 'failed' && handlers.retryPlan) panel.append(button('重试计划调整', () => handlers.retryPlan(item.id)));
    if (['pending','applying'].includes(status) && handlers.retryPlan) panel.append(button('检查并恢复计划调整', () => handlers.retryPlan(item.id)));
    if (status === 'draft') {
      const link = make('a', '查看长期计划草稿', 'text-button'); link.href = '#plan'; panel.append(link);
    }
    const memoryLabels = {failed: '本次个人记忆未更新，保留之前的版本；原始反馈和本次回应仍已保存。',
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
  function renderMemory(root, memory, doc = document) {
    root.replaceChildren();
    const make = (tag, text) => { const e = doc.createElement(tag); e.textContent = text; return e; };
    root.append(make('p', `记忆版本 ${memory.version || 0} · 约 ${memory.estimated_tokens || 0} / ${memory.budget_tokens || 6000} 上下文预算。原始反馈一直保留。`));
    if (list(memory.stale_keys).length) root.append(make('p', '部分记忆的来源已更正，已从当前上下文排除，待重新理解。'));
    if (!list(memory.entries).length) root.append(make('p', '还没有有效的个人记忆；提交反馈后由模型逐步整理。'));
    const names = {fact:'报告事实',preference:'偏好',restriction:'限制',question:'待确认',pattern:'模型归纳（待验证）'};
    list(memory.entries).forEach(entry => {
      const detail = make('details', ''); detail.append(make('summary', `${names[entry.category] || entry.category} · ${entry.text}`));
      const sources = make('p', '来源：');
      list(entry.sources).forEach(source => {
        const link = make('a', `${source.feedback_id.slice(0,8)} · 修订 ${source.revision} `);
        link.href = `#feedback-${encodeURIComponent(source.feedback_id)}`;
        link.dataset.feedbackId = source.feedback_id; sources.append(link);
      });
      detail.append(sources); root.append(detail);
    });
  }
  const api = {render, renderMemory};
  if (typeof module !== 'undefined') module.exports = api;
  else global.FeedbackCoachUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
