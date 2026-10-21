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
  setAttribute(name, value) { this[name] = value; }
}
const doc = {createElement: tag => new Element(tag)};

test('reflection keeps questions and a reply form together and submits the answer', async () => {
  assert.equal(typeof ui.render, 'function');
  const root = new Element('div');
  let parent = null;
  ui.render(root, {id: 'feedback-1', date: '2026-10-21', raw_text: '练完很累 <script>',
    coaching: {status: 'ready', timing: 'review', memory_status: 'updated',
      data: {reply: '先恢复，不修改今天。', suggestions: ['今晚早点睡'], questions: ['哪里不舒服？'],
        memory_updates: [{key:'fatigue',category:'fact',text:'今天训练后疲劳',sources:[{feedback_id:'feedback-1',revision:1}]}],
        decision:{action:'adjust_next',reason:'下一次减轻负担'}},
        planning_update:{status:'updated',date:'2026-10-22'}}}, {followup: (id, answer) => parent = {id, answer}}, doc);
  for (const text of ['先恢复', '今晚早点睡', '哪里不舒服', '2026-10-22', '<script>', '今天训练后疲劳']) assert.ok(root.textContent.includes(text), text);
  const nodes = root.children.flatMap(function walk(x) { return [x,...x.children.flatMap(walk)]; });
  const form = nodes.find(x => x.tagName === 'form');
  assert.ok(form.textContent.includes('哪里不舒服'));
  nodes.find(x => x.tagName === 'textarea').value = '肩部没有不适，只是疲劳';
  await form.listeners.submit({preventDefault() {}});
  assert.deepEqual(parent, {id: 'feedback-1', answer: '肩部没有不适，只是疲劳'});
  assert.ok(!nodes.some(x => x.tagName === 'input'));
});

test('reply failure preserves the answer and reports the error next to it', async () => {
  const root = new Element('div');
  ui.render(root, {id:'f',coaching:{status:'ready',data:{questions:['每组几次？']},
    planning_update:{status:'failed',questions:['有没有动作变形？']}}},
    {replyDraft:'8/8/7次', followup:async () => {throw Error('连接中断');}}, doc);
  const nodes = root.children.flatMap(function walk(x) {return [x,...x.children.flatMap(walk)];});
  const form = nodes.find(x=>x.tagName==='form'), input = nodes.find(x=>x.tagName==='textarea');
  assert.ok(form.textContent.includes('每组几次？'));
  assert.ok(form.textContent.includes('有没有动作变形？'));
  await form.listeners.submit({preventDefault() {}});
  assert.equal(input.value,'8/8/7次');
  assert.match(form.textContent,/连接中断/);
  assert.equal(nodes.find(x=>x.tagName==='button' && x.type==='submit').disabled,false);
});

test('draft link identifies the exact long-term plan to review', () => {
  const root = new Element('div');
  ui.render(root, {id:'f',coaching:{status:'ready',data:{},
    planning_update:{status:'draft',plan_id:'new-draft',date:'2026-10-22'}}}, {}, doc);
  const nodes = root.children.flatMap(function walk(x){return [x,...x.children.flatMap(walk)];});
  assert.equal(nodes.find(x=>x.tagName==='a').href,'#plan-new-draft');
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

test('unknown critical completion offers explicit confirmation and displays sets', () => {
  const root = new Element('div'); let confirmed = null;
  ui.render(root, {id:'f',revision:2,date:'2026-10-21',data:{exercise_results:[{
    exercise_id:'bench_press',exercise_name:'卧推',sets:[{reps:8,weight_kg:45},{reps:7,weight_kg:45,rpe:9}]}]},
    coaching:{status:'ready',memory_status:'updated',data:{reply:'收到',decision:{reason:'观察'}},
      fact_status:{training_completed:{status:'needs_confirmation'},ignored_fields:['weight_kg']}}},
    {confirmFacts:(id, revision, facts) => confirmed={id,revision,facts}}, doc);
  assert.ok(root.textContent.includes('45'));
  assert.ok(root.textContent.includes('第2组'));
  assert.ok(root.textContent.includes('整次训练'));
  assert.ok(root.textContent.includes('体重'));
  const nodes=root.children.flatMap(function walk(x){return [x,...x.children.flatMap(walk)];});
  nodes.find(x=>x.tagName==='button' && x.textContent==='训练已全部完成').listeners.click();
  assert.deepEqual(confirmed,{id:'f',revision:2,facts:{training_completed:true}});
});

test('memory view explains event dates, expiry, evidence and legacy verification', () => {
  const root=new Element('div');
  ui.renderMemory(root,{version:2,expired_keys:['old'],entries:[{key:'x',category:'fact',text:'今天很累',
    event_date:'2026-10-21',expires_on:'2026-11-03',verification:'legacy_unverified',sources:[],
    evidence:[{quote:'我今天有点累'}],supersedes:['old-fatigue']},
    {key:'budget',category:'fact',retention:'long_term',text:'伙食预算50元/天',sources:[],evidence:[]}]},doc);
  for(const phrase of ['2026-10-21','2026-11-03','我今天有点累','长期保留','待核实','已过期','old-fatigue'])
    assert.ok(root.textContent.includes(phrase),phrase);
});

test('legacy editing preserves imported sets and separate same-action sessions', () => {
  const rows=[{exercise_id:'bench_press',session_id:'am',sets:[{reps:8,weight_kg:45}],weight_kg:45},
    {exercise_id:'bench_press',session_id:'pm',sets:[{reps:7,weight_kg:45}],form_notes:'动作稳定'}];
  const updated=ui.mergeExerciseEdits(rows,[{index:0,field:'weight_kg',value:null},{index:1,field:'rpe',value:9}]);
  assert.equal(updated.length,2);
  assert.equal(updated[0].weight_kg,null);
  assert.equal(updated[1].session_id,'pm');
  assert.deepEqual(updated[1].sets,[{reps:7,weight_kg:45}]);
  assert.equal(updated[1].form_notes,'动作稳定');
  assert.equal(updated[1].rpe,9);
});
