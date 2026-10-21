const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
let ui = {};
try { ui = require('../../fitness/static/feedback-coach.js'); } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  set textContent(value) { this._text = value; this.children = []; }
  get textContent() { return (this._text || '') + this.children.map(x => x.textContent).join(''); }
  set innerHTML(_) { throw Error('unsafe HTML'); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
}
const doc = {createElement: tag => new Element(tag)};

test('reflection renders natural reply, followup and future decision without a field editor', () => {
  assert.equal(typeof ui.render, 'function');
  const root = new Element('div');
  let parent = null;
  ui.render(root, {id: 'feedback-1', date: '2026-10-21', raw_text: '练完很累 <script>',
    coaching: {status: 'ready', timing: 'review', memory_status: 'updated',
      data: {reply: '先恢复，不修改今天。', suggestions: ['今晚早点睡'], questions: ['哪里不舒服？'],
        memory_updates: [{key:'fatigue',category:'fact',text:'今天训练后疲劳',sources:[{feedback_id:'feedback-1',revision:1}]}],
        decision:{action:'adjust_next',reason:'下一次减轻负担'}},
      planning_update:{status:'updated',date:'2026-10-22'}}}, {followup: id => parent = id}, doc);
  for (const text of ['先恢复', '今晚早点睡', '哪里不舒服', '2026-10-22', '<script>', '今天训练后疲劳']) assert.ok(root.textContent.includes(text), text);
  const nodes = root.children.flatMap(function walk(x) { return [x,...x.children.flatMap(walk)]; });
  nodes.find(x => x.tagName === 'button' && x.textContent.includes('回答')).listeners.click();
  assert.equal(parent, 'feedback-1');
  assert.ok(!nodes.some(x => x.tagName === 'input'));
});

test('failure distinguishes saved original from incomplete understanding and offers retry', () => {
  const root = new Element('div');
  ui.render(root, {id:'f',raw_text:'原文',date:'2026-10-21',coaching:{status:'failed',error:'timeout'}}, {retry: () => {}}, doc);
  assert.ok(root.textContent.includes('原文已保存'));
  assert.ok(root.textContent.includes('重试'));
  assert.ok(!root.textContent.includes('已记住'));
});

test('compaction failure and draft awaiting confirmation are visible', () => {
  const root = new Element('div');
  ui.render(root, {id:'f',coaching:{status:'ready',memory_status:'failed',data:{reply:'回应',
    decision:{action:'propose_long_term',reason:'频率改变'},questions:[],suggestions:[],memory_updates:[]},
    planning_update:{status:'draft',date:'2026-10-22'}}}, {}, doc);
  assert.ok(root.textContent.includes('记忆未更新'));
  assert.ok(root.textContent.includes('确认'));
});

test('interrupted plan application exposes a recovery action', () => {
  const root = new Element('div'); let recovered = null;
  ui.render(root, {id:'f',coaching:{status:'ready',memory_status:'updated',
    data:{reply:'回应',decision:{reason:'恢复'},suggestions:[],questions:[]},
    planning_update:{status:'applying'}}}, {retryPlan:id => recovered=id}, doc);
  const nodes = root.children.flatMap(function walk(x) { return [x,...x.children.flatMap(walk)]; });
  const action = nodes.find(x => x.tagName === 'button' && x.textContent.includes('恢复'));
  assert.ok(action);
  action.listeners.click(); assert.equal(recovered,'f');
});

test('feedback state events load plans without automatically regenerating today', () => {
  const source = fs.readFileSync('fitness/static/daily-plans.js','utf8');
  assert.ok(source.includes('feedback_saved'));
  const app = fs.readFileSync('fitness/static/app.js','utf8');
  assert.ok(app.includes('/api/feedback/record'));
  assert.ok(app.includes('understand'));
  const html = fs.readFileSync('fitness/static/index.html','utf8');
  assert.ok(html.includes('日终复盘'));
  assert.ok(html.includes('feedback-timing'));
});
