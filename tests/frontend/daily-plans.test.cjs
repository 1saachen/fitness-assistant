const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let ui = {};
try { ui = require('../../fitness/static/daily-plans.js'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }

class Element {
  constructor(tag = 'div') { this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ''; }
  set textContent(value) { this._text = String(value ?? ''); this.children = []; }
  get textContent() { return (this._text || '') + this.children.map(x => x.textContent || '').join(''); }
  set innerHTML(_) { throw new Error('unsafe HTML rendering'); }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
}
const doc = { createElement: tag => new Element(tag) };

test('long-term supplements show priorities, current products, evidence and safe source links', () => {
  const root = new Element();
  const item = {name: '维生素D <script>', current_product: '我的D片', priority: 'conditional',
    reason: '结合日晒条件评估', conditions: ['先核实健康信息'], food_alternatives: ['先调整饮食'],
    cautions: ['创作者观点，证据有限'], source_ids: ['card-1', 'card-2']};
  const source = {id: 'card-1', title: '维生素D与日晒', source: {creator_name: '作者',
    video_title: '来源视频', video_url: 'https://example.com/video'}, metadata: {
      evidence_level: 'limited', source_type: 'creator_opinion', claim: '来源主张 <script>',
      explanation: '来源有适用限制', safety_level: '不可作个体剂量'}};
  const record = {id: 'long', data: {supplements: {summary: '按需评估', budget_note: '预算未知',
    items: [item], questions: ['请核实成分']}, supplement_sources: [source,
      {...source, id: 'card-2', source: {...source.source, video_url: 'javascript:alert(1)'}}]}};
  ui.renderLongTerm(root, record, {}, doc);
  for (const value of ['补剂建议', '条件满足再考虑', '当前产品：我的D片', '维生素D <script>',
    '先核实健康信息', '先调整饮食', '证据有限', '有限证据', '创作者观点', '请核实成分',
    '来源主张 <script>', '不可作个体剂量']) assert.ok(root.textContent.includes(value), value);
  const nodes = root.children.flatMap(function walk(x) { return [x, ...x.children.flatMap(walk)]; });
  const links = nodes.filter(x => x.tagName === 'a');
  assert.equal(links.length, 1);
  assert.equal(links[0].href, 'https://example.com/video');
  assert.equal(links[0].rel, 'noopener noreferrer');
  ui.renderLongTerm(root, {id: 'legacy', data: {}}, {}, doc);
  assert.ok(!root.textContent.includes('补剂建议'));
});

test('long-term supplements explain an unavailable knowledge library even with no products', () => {
  const root = new Element();
  ui.renderLongTerm(root, {data: {supplements: {summary: '暂不新增', items: []}},
    trace: {supplement_provider: {knowledge_status: 'unavailable'}}}, {}, doc);
  assert.match(root.textContent, /补剂知识库暂不可用/);
});

test('profile synchronization notifies the profile form once when the plan is saved', async () => {
  const nodes = new Map(), listeners = {}, events = [];
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('view-daily').hidden = true;
  get('long-term-conditions').value = '通常18点训练';
  const notice = {feedback_id: 'answer', status: 'updated', profile_sync_checked: true, profile_version: 4,
    profile_updated_fields: ['通常训练时间'], message: '个人档案已同步：通常训练时间。'};
  const state = {today: '2026-10-22', profile_version: 3, model_configured: true, long_term_plans: [], daily_plans: []};
  const document = {createElement: tag => new Element(tag), getElementById: get, querySelectorAll: () => [],
    dispatchEvent: event => events.push(event), addEventListener: (name, fn) => { listeners[name] = fn; }};
  class CustomEvent { constructor(type, options) { this.type = type; this.detail = options.detail; } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../fitness/static/daily-plans.js'), 'utf8'),
    {document, CustomEvent, Intl, Date, TextDecoder, fetch: async url => {
      if (url === '/api/long-term-plans/stream') {
        const plan = {id: 'new', trace: {conditions_memory: notice}};
        state.long_term_plans = [plan]; state.profile_version = 4;
        return new Response(['event: memory', `data: ${JSON.stringify(notice)}`, '',
          'event: result', `data: ${JSON.stringify(plan)}`, '', ''].join('\n'),
          {headers: {'content-type': 'text/event-stream'}});
      }
      return {ok: true, json: async () => state};
    }});
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
  listeners.DOMContentLoaded(); await settle();
  get('long-term-form').listeners.submit({preventDefault() {}}); await settle();
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'fitness-profile-synced');
  assert.equal(events[0].detail.profile_version, 4);
});

test('legacy plan memory links directly to profile review', async () => {
  const state = {today: '2026-10-22', profile_version: 3, model_configured: true,
    long_term_plans: [{id: 'legacy', status: 'confirmed', start_date: '2026-10-21', profile_version: 3,
      data: {title: '旧计划', cycle: [], nutrition: {}},
      trace: {conditions_memory: {feedback_id: 'old-answer', status: 'updated', message: '补充原文已保存'}}}],
    daily_plans: []};
  const {get} = await planningPage(state);
  assert.match(get('long-term-memory').textContent, /查看原文与档案同步状态/);
  const link = get('long-term-memory').children.find(x => x.tagName === 'a');
  assert.equal(link.href, '#feedback-old-answer');
});

test('stream reader displays split UTF-8 text before the final plan arrives', async () => {
  const encoder = new TextEncoder(), events = [];
  const first = encoder.encode('event: text\r\ndata: {"text":"今天练腿 <script>"}\r\n\r\n');
  const split = first.indexOf(encoder.encode('今')[0]) + 1;
  let reads = 0;
  const response = new Response(new ReadableStream({pull(controller) {
    reads += 1;
    if (reads === 1) controller.enqueue(first.slice(0, split));
    else if (reads === 2) controller.enqueue(first.slice(split));
    else if (reads === 3) controller.enqueue(encoder.encode(': keepalive\n\n'));
    else {
      assert.deepEqual(events, [['text', {text: '今天练腿 <script>'}]]);
      controller.enqueue(encoder.encode('event: result\ndata: {"id":"saved"}\n\n'));
      controller.close();
    }
  }}));
  assert.deepEqual(await ui.readPlanStream(response, (name, data) => events.push([name, data])), {id: 'saved'});
});

test('stream reader preserves needs-input details and rejects dropped connections', async () => {
  const detail = {status: 'needs_input', questions: ['请说明限制'], snapshot_token: 'abc', message: '需要补充信息'};
  await assert.rejects(ui.readPlanStream(new Response(`event: error\ndata: ${JSON.stringify({status: 422, detail})}\n\n`), () => {}),
    error => error.detail.snapshot_token === 'abc' && error.message.includes('请说明限制'));
  await assert.rejects(ui.readPlanStream(new Response('event: text\ndata: {"text":"草稿"}\n\n'), () => {}), /连接中断/);
});
const nutrition = {daily_targets: {calories_kcal: 2100, protein_g: 130, fat_g: 60, carbs_g: 260}, meal_options: [{meal: '早餐', suggestions: ['鸡蛋2个 <script>'], estimated_kcal: 500, protein_g: 30, estimated_cost_cny: 6, alternatives: ['豆腐150克']}], questions: ['确认过敏信息'], budget_note: '每天约30元'};
const daily = {id: 'day-1', date: '2026-10-20', revision: 2, long_term_id: 'long-1', data: {training: {label: '恢复', kind: 'rest', exercises: []}, decision: {action: 'defer', reasons: ['今天疲劳，顺延'], restrictions: [{area: 'shoulder', reason: '肩痛', active: true}], questions: ['肩部情况如何？'], provider: 'local'}, water: {base_ml: 2400, note: '分次饮水'}, completed_meals: ['早餐'], training_completed: null, nutrition, review_suggestions: ['需要复盘'], recovery_guidance: ['规律睡眠']}};

test('daily plan identifies model designed food and displays free exercise notes safely', () => {
  const root = new Element();
  const record = {...daily, trace: {nutrition_source: 'model'}, data: {...daily.data,
    training: {label: '下肢', kind: 'training', exercises: [{name: '保加利亚分腿蹲', sets: 2,
      reps_min: 8, reps_max: 10, rest_seconds: 90, notes: '每侧完成 <script>'}]}}};
  ui.renderDaily(root, record, {}, doc);
  assert.ok(root.textContent.includes('饮食来源：在线模型'));
  assert.ok(root.textContent.includes('保加利亚分腿蹲'));
  assert.ok(root.textContent.includes('每侧完成 <script>'));
});

test('training cycle accepts Chinese punctuation and rejects empty or oversized cycles', () => {
  assert.equal(typeof ui.parseCycleLabels, 'function');
  assert.deepEqual(ui.parseCycleLabels('推，拉, 腿、休息'), ['推', '拉', '腿', '休息']);
  assert.throws(() => ui.parseCycleLabels(' , '), /循环/);
  assert.throws(() => ui.parseCycleLabels(Array(15).fill('推').join(',')), /14/);
});

test('daily plan renders completion, restrictions, meal estimates and literal untrusted text', () => {
  assert.equal(typeof ui.renderDaily, 'function');
  const root = new Element();
  ui.renderDaily(root, daily, {complete: () => {}}, doc);
  for (const value of ['顺延', '肩痛', '肩部情况如何', '2400', '2100', '已完成', '鸡蛋2个 <script>', '豆腐150克', '6', '需要复盘', '完成情况未记录']) assert.ok(root.textContent.includes(value), value);
  const nodes = root.children.flatMap(function walk(x) { return [x, ...x.children.flatMap(walk)]; });
  const completed = nodes.find(x => x.tagName === 'button' && x.textContent.includes('已完成'));
  assert.equal(completed.disabled, true);
});

test('daily nutrition review shows evidence and explicitly requires user confirmation', () => {
  const root = new Element();
  const record = {...daily, data: {...daily.data, review_suggestions: [
    '前后两周体重均值约75.00kg和75.02kg，变化约+0.02kg；6条饮食执行记录的执行率约100%。',
    '减脂期间体重均值变化较小。可考虑将每日目标下调约100千卡，这是复盘建议，不会自动改写已确认目标。',
  ]}};
  ui.renderDaily(root, record, {}, doc);
  assert.ok(root.textContent.includes('前后两周体重均值'));
  assert.ok(root.textContent.includes('下调约100千卡'));
  assert.ok(root.textContent.includes('不会自动改写已确认目标'));
});

test('missing profile measurements are shown as unknown without false nutrition or water totals', () => {
  const root = new Element();
  ui.renderDaily(root, {...daily, data: {...daily.data, water: {base_ml: null,
    note: '档案未提供体重，暂不生成个体化饮水量。'}, nutrition: {approach: '资料不足，仅提供通用餐次建议。',
      daily_targets: null, meal_options: [{meal: '午餐', suggestions: ['按已知条件安排'], alternatives: []}]}}}, {}, doc);
  assert.ok(root.textContent.includes('资料不足'));
  assert.ok(root.textContent.includes('档案未提供体重'));
  assert.ok(!root.textContent.includes('基础饮水参考 未记录'));
  assert.ok(!root.textContent.includes('估算 未记录 千卡'));
});

test('long-term plan shows non-week cycle and confirms a draft through callback', async () => {
  assert.equal(typeof ui.renderLongTerm, 'function');
  const root = new Element();
  let confirmed = null;
  ui.renderLongTerm(root, {id: 'long-1', version: 1, status: 'draft', start_date: '2026-10-20', data: {title: '长期减脂', goals: {primary: 'fat_loss', target_weight_kg: 70}, cycle: [{label: '推', kind: 'training', estimated_minutes: 30, exercises: [{name: '卧推', sets: 3, reps_min: 8, reps_max: 12, rest_seconds: 90}]}, {label: '休息', kind: 'rest'}], nutrition, review_after: '2026-11-03', review_rules: ['按趋势复盘']}}, {confirm: id => { confirmed = id; }}, doc);
  for (const value of ['长期减脂', '减脂', '70', '推', '休息', '卧推', '2026-11-03', '2100']) assert.ok(root.textContent.includes(value), value);
  const nodes = root.children.flatMap(function walk(x) { return [x, ...x.children.flatMap(walk)]; });
  await nodes.find(x => x.tagName === 'button').listeners.click();
  assert.equal(confirmed, 'long-1');
});

test('long-term and daily exercise display prescribed load and target RPE', () => {
  const root = new Element();
  ui.renderLongTerm(root, {id: 'long-load', version: 1, status: 'draft', start_date: '2026-10-20', data: {
    title: '力量计划', goals: {primary: 'general_health'},
    cycle: [{label: '推', kind: 'training', estimated_minutes: 30, exercises: [
      {exercise_id: 'bench', name: '卧推', sets: 3, reps_min: 8, reps_max: 10,
       rest_seconds: 90, weight_kg: 42.5, target_rpe: 7.5},
    ]}], nutrition, review_after: '2026-11-03', review_rules: [],
  }}, {}, doc);
  assert.ok(root.textContent.includes('42.5 kg'));
  assert.ok(root.textContent.includes('RPE 7.5'));
});

test('restriction release requires an explicit recovery statement and retains the plan revision', async () => {
  const root = new Element();
  let released;
  ui.renderDaily(root, daily, {release: (...args) => {released = args;}}, doc);
  const nodes = root.children.flatMap(function walk(x) {return [x, ...x.children.flatMap(walk)];});
  const form = nodes.find(x => x.tagName === 'form');
  assert.ok(form, 'active restriction provides recovery form');
  const input = nodes.find(x => x.tagName === 'textarea');
  assert.equal(input.required, true);
  assert.match(root.textContent, /专业/);
  input.value = '肩部目前已无症状，医生允许逐步恢复';
  await form.listeners.submit({preventDefault() {}});
  assert.deepEqual(released, ['day-1', 'shoulder', 2, '肩部目前已无症状，医生允许逐步恢复']);
});

test('automatic generation only targets today after a confirmed applicable long-term plan', () => {
  assert.equal(typeof ui.shouldRefreshToday, 'function');
  const state = {today: '2026-10-20', long_term_plans: [{status: 'confirmed', start_date: '2026-10-19', profile_version: 2}]};
  assert.equal(ui.shouldRefreshToday(state, '2026-10-20', 2), true);
  assert.equal(ui.shouldRefreshToday(state, '2026-10-21', 2), false);
  assert.equal(ui.shouldRefreshToday(state, '2026-10-20', 3), false);
  assert.equal(ui.shouldRefreshToday({...state, long_term_plans: [{status: 'draft'}]}, '2026-10-20', 2), false);
  assert.equal(ui.shouldRefreshToday({...state, daily_plans: [{date:'2026-10-20'}]}, '2026-10-20', 2), false);
});

test('page exposes long-term and daily navigation while preserving weekly history ids', () => {
  const html = fs.readFileSync(path.join(__dirname, '../../fitness/static/index.html'), 'utf8');
  assert.match(html, /data-view="daily"/);
  assert.match(html, /id="long-term-form"/);
  assert.doesNotMatch(html, /id="long-term-date"|id="long-term-cycle"/);
  assert.match(html, /id="long-term-conditions"/);
  assert.match(html, /id="daily-form"/);
  assert.match(html, /历史周计划兼容/);
  for (const id of ['plan-form', 'plan-content', 'plan-history', 'plan-date']) assert.ok(html.includes(`id="${id}"`));
  assert.match(html, /daily-plans\.js/);
});

test('long-term form sends profile-led request without a date or fixed cycle and allows answers', async () => {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('view-daily').hidden = true;
  get('mode').value = 'live';
  get('long-term-conditions').value = '每周训练3次，每次45分钟；有杠铃和器械；目前没有运动限制';
  const listeners = {}, calls = [];
  const state = {today: '2026-10-20', profile_version: 3, long_term_plans: [], daily_plans: []};
  const document = {createElement: tag => new Element(tag), getElementById: get, querySelectorAll: () => [],
    addEventListener: (name, fn) => { listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../fitness/static/daily-plans.js'), 'utf8'),
    {document, Intl, Date, console, TextDecoder, fetch: async (url, options = {}) => {
      calls.push({url, options});
      if (url === '/api/long-term-plans/stream') return new Response('event: text\ndata: {"text":"训练草稿"}\n\nevent: result\ndata: {"id":"long-new"}\n\n', {headers: {'content-type': 'text/event-stream'}});
      return {ok: true, json: async () => url === '/api/planning/state?date=' ? state :
        url === '/api/long-term-plans' ? {id: 'long-new'} : state};
    }});
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
  listeners.DOMContentLoaded(); await settle();
  await nodes.get('long-term-form').listeners.submit({preventDefault() {}}); await settle();
  const request = calls.find(x => x.url === '/api/long-term-plans/stream');
  assert.ok(request);
  assert.equal(request.options.headers.Accept, 'text/event-stream');
  assert.equal(get('long-term-preview').hidden, true);
  const body = JSON.parse(request.options.body);
  assert.equal(body.mode, 'live');
  assert.equal(body.conditions, '每周训练3次，每次45分钟；有杠铃和器械；目前没有运动限制');
  assert.deepEqual(body.answered_questions, []);
});

test('live planning keeps model draft text hidden until the validated result arrives', async () => {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('view-daily').hidden = true;
  get('mode').value = 'live';
  get('long-term-conditions').value = '';
  const listeners = {}, state = {today: '2026-10-20', profile_version: 3, long_term_plans: [], daily_plans: []};
  let controller, pulls = 0;
  const stream = new ReadableStream({
    start(value) { controller = value; },
    pull(value) {
      if (pulls++ === 0) value.enqueue(new TextEncoder().encode('event: text\ndata: {"text":"不要显示的未校验草稿"}\n\n'));
    },
  });
  const document = {createElement: tag => new Element(tag), getElementById: get, querySelectorAll: () => [],
    addEventListener: (name, fn) => { listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../fitness/static/daily-plans.js'), 'utf8'),
    {document, Intl, Date, console, TextDecoder, fetch: async url => url === '/api/long-term-plans/stream'
      ? new Response(stream, {headers: {'content-type': 'text/event-stream'}})
      : {ok: true, json: async () => state}});
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
  listeners.DOMContentLoaded(); await settle();
  const submission = get('long-term-form').listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(get('long-term-preview').hidden, false);
  assert.match(get('long-term-preview').textContent, /正在生成计划/);
  assert.ok(!get('long-term-preview').textContent.includes('不要显示的未校验草稿'));
  controller.enqueue(new TextEncoder().encode('event: result\ndata: {"id":"long-new"}\n\n'));
  controller.close();
  await submission; await settle();
});

test('long-term follow-up reuses the asked date and snapshot token after an answer', async () => {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('view-daily').hidden = true;
  get('mode').value = 'live';
  const listeners = {}, posts = [];
  const state = {today: '2026-10-20', profile_version: 3, long_term_plans: [], daily_plans: []};
  const document = {createElement: tag => new Element(tag), getElementById: get, querySelectorAll: () => [],
    addEventListener: (name, fn) => { listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../fitness/static/daily-plans.js'), 'utf8'),
    {document, Intl, Date, console, TextDecoder, fetch: async (url, options = {}) => {
      if (url === '/api/long-term-plans/stream') {
        posts.push(JSON.parse(options.body));
        if (posts.length > 1) state.long_term_plans = [{id: 'long-new', status: 'draft',
          data: {training_questions: ['下次可补充动作偏好？']}}];
        return posts.length === 1
          ? new Response(`event: error\ndata: ${JSON.stringify({status: 422, detail: {status: 'needs_input', message: '需要补充信息',
            questions: ['每周能训练几次？'], snapshot_token: 'a'.repeat(64), start_date: '2026-10-20'}})}\n\n`, {headers: {'content-type': 'text/event-stream'}})
          : new Response('event: result\ndata: {"id":"long-new"}\n\n', {headers: {'content-type': 'text/event-stream'}});
      }
      return {ok: true, json: async () => state};
    }});
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
  listeners.DOMContentLoaded(); await settle();
  const form = get('long-term-form');
  await form.listeners.submit({preventDefault() {}}); await settle();
  assert.match(get('planning-message').textContent, /需要补充信息/);
  assert.ok(!get('planning-message').textContent.includes('每周能训练几次？'), 'questions appear once next to the answer');
  assert.equal(get('daily-message').textContent, '', 'a long-term question must not appear on the daily page');
  assert.equal(get('long-term-preview').hidden, true);
  assert.match(get('long-term-questions').textContent, /每周能训练几次？/);
  assert.match(get('long-term-submit').textContent, /补充.*继续/);
  get('long-term-conditions').value = '每周3次，每次45分钟';
  await form.listeners.submit({preventDefault() {}}); await settle();
  assert.deepEqual(posts[0], {mode: 'live'});
  assert.deepEqual(posts[1].answered_questions, ['每周能训练几次？']);
  const {answered_questions, ...submitted} = posts[1];
  assert.deepEqual(submitted, {mode: 'live', conditions: '每周3次，每次45分钟',
    expected_snapshot_token: 'a'.repeat(64), start_date: '2026-10-20'});
  assert.equal(get('long-term-questions').hidden, true);
  assert.equal(get('long-term-submit').textContent, '生成长期计划草案');
  assert.match(get('long-term-content').textContent, /可选补充/);
  assert.match(get('long-term-content').textContent, /下次可补充动作偏好？/);
  assert.match(get('long-term-content').textContent, /确认并启用长期计划/);
});

async function planningPage(state, respond = async () => daily) {
  state = {model_configured: true, ...state};
  const nodes = new Map(), listeners = {}, calls = [];
  const get = id => {if (!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id);};
  get('view-daily').hidden = true;
  const document = {createElement:tag=>new Element(tag),getElementById:get,querySelectorAll:()=>[],
    addEventListener:(name,fn)=>{listeners[name]=fn;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../fitness/static/daily-plans.js'),'utf8'),
    {document,Intl,Date,console,fetch:async(url,options={})=>{
      calls.push({url,options});
      return {ok:true,json:async()=>url.startsWith('/api/planning/state')?state:await respond(url,options)};
    }});
  const settle = async()=>{for(let i=0;i<8;i++) await new Promise(resolve=>setImmediate(resolve));};
  listeners.DOMContentLoaded(); await settle();
  get('daily-date').value = state.today;
  listeners['fitness-state-change']({detail:{feedback_saved:true}}); await settle();
  return {get,listeners,calls,settle};
}

test('saved questions are optional at the end of each plan and do not keep the form unfinished', async () => {
  const state = {today:'2026-10-20',long_term_plans:[{id:'l',version:1,status:'confirmed',
    data:{training_questions:['每周几次？'],nutrition:{questions:['有没有过敏？']},
      supplements:{summary:'先评估',questions:['当前产品有哪些成分？', '有没有过敏？']}}}],daily_plans:[daily]};
  const {get} = await planningPage(state);
  assert.equal(get('long-term-questions').hidden, true);
  assert.equal(get('daily-questions').hidden, true);
  assert.equal(get('long-term-submit').textContent, '生成长期计划草案');
  assert.equal(get('daily-submit').textContent, '更新当天计划');
  assert.equal(get('long-term-conditions-label').textContent, '补充条件');
  for (const scope of ['long-term', 'daily']) {
    const card = get(`${scope}-content`).children[0];
    const optional = card.children.at(-1);
    assert.match(optional.textContent, /可选补充/);
    assert.match(optional.textContent, /不影响使用当前计划/);
    assert.doesNotMatch(get(`${scope}-content`).textContent, /需要补充的/);
  }
  const longText = get('long-term-content').textContent;
  for (const question of ['每周几次？', '有没有过敏？', '当前产品有哪些成分？'])
    assert.equal(longText.split(question).length - 1, 1);
  assert.match(get('daily-content').textContent, /肩部情况如何？/);
  assert.match(get('daily-content').textContent, /确认过敏信息/);
});

test('optional answers retain the displayed question context without entering a blocking follow-up', async () => {
  const state = {today:'2026-10-20',long_term_plans:[{id:'l',status:'confirmed',
    data:{training_questions:['通常几点训练？']}}],daily_plans:[daily]};
  const {get, calls, settle} = await planningPage(state);
  get('long-term-conditions').value = '18点';
  await get('long-term-form').listeners.submit({preventDefault(){}}); await settle();
  const body = JSON.parse(calls.find(x => x.url === '/api/long-term-plans/stream').options.body);
  assert.deepEqual(body.answered_questions, ['通常几点训练？']);
  assert.equal(body.expected_snapshot_token, undefined);
  assert.equal(get('long-term-submit').textContent, '生成长期计划草案');
});

test('recovery confirmation saves the release then regenerates that day', async () => {
  const state = {today:'2026-10-20',model_configured:true,long_term_plans:[],daily_plans:[daily]};
  const {get,calls,settle} = await planningPage(state);
  get('daily-conditions').value='今天可训练40分钟';
  const nodes = get('daily-content').children.flatMap(function walk(x){return [x,...x.children.flatMap(walk)];});
  nodes.find(x=>x.tagName==='textarea').value='肩部目前已无症状，医生允许逐步恢复';
  await nodes.find(x=>x.tagName==='form').listeners.submit({preventDefault(){}}); await settle();
  const writes=calls.filter(x=>x.options.method==='POST');
  assert.deepEqual(writes.map(x=>x.url),['/api/daily-plans/day-1/restrictions/release','/api/daily-plans/stream']);
  assert.equal(JSON.parse(writes[1].options.body).date,'2026-10-20');
  assert.equal(JSON.parse(writes[1].options.body).conditions,'今天可训练40分钟');
  assert.equal(get('planning-message').textContent,'');
});

test('recovery keeps the saved release when regeneration fails and explains the partial result', async () => {
  const state = {today:'2026-10-20',model_configured:true,long_term_plans:[],daily_plans:[daily]};
  const {get,settle} = await planningPage(state, async url => {
    if (url === '/api/daily-plans/stream') throw Error('模型暂时不可用');
    return daily;
  });
  const nodes = get('daily-content').children.flatMap(function walk(x){return [x,...x.children.flatMap(walk)];});
  nodes.find(x=>x.tagName==='textarea').value='肩部已恢复，医生允许逐步恢复';
  await nodes.find(x=>x.tagName==='form').listeners.submit({preventDefault(){}}); await settle();
  assert.match(get('daily-message').textContent,/恢复确认已保存.*重新评估未完成.*模型暂时不可用/);
  assert.equal(get('planning-message').textContent,'');
});

test('a draft navigation selects its exact version instead of the previous selection', async () => {
  const old = {id:'old',version:1,status:'confirmed',data:{title:'旧计划'}};
  const draft = {id:'new',version:2,status:'draft',data:{title:'本次生成的新草稿'}};
  const {get,listeners,settle} = await planningPage({today:'2026-10-20',long_term_plans:[old,draft],daily_plans:[]});
  assert.match(get('long-term-content').textContent,/旧计划/);
  listeners['fitness-view-change']({detail:{view:'plan',long_term_id:'new'}}); await settle();
  assert.match(get('long-term-content').textContent,/本次生成的新草稿/);
  assert.ok(!get('long-term-content').textContent.includes('旧计划'));
});

test('an unavailable linked draft does not leave the previous plan visible for confirmation', async () => {
  const old = {id:'old',version:1,status:'draft',data:{title:'无关的旧草稿'}};
  const {get,listeners,settle} = await planningPage({today:'2026-10-20',long_term_plans:[old],daily_plans:[]});
  listeners['fitness-view-change']({detail:{view:'plan',long_term_id:'missing'}}); await settle();
  assert.match(get('planning-message').textContent,/不存在/);
  assert.ok(!get('long-term-content').textContent.includes('确认并启用'));
  assert.ok(!get('long-term-content').textContent.includes('无关的旧草稿'));
});

test('opening today preserves an existing plan, creates a missing plan, and future dates never auto-write', async () => {
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
  get('view-daily').hidden = true;
  const listeners = {}, calls = [];
  const state = {today: '2026-10-20', model_configured: true, profile_version: 2, long_term_plans: [{id: 'long-1', version: 1, profile_version: 2, status: 'confirmed', start_date: '2026-10-19', data: {}}], daily_plans: [{...daily, trace: {mode: 'live'}}]};
  const document = {createElement: tag => new Element(tag), getElementById: get, querySelectorAll: () => [], addEventListener: (name, fn) => { listeners[name] = fn; }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../fitness/static/daily-plans.js'), 'utf8'), {document, Intl, Date, console, fetch: async (url, options = {}) => {
    calls.push({url, options});
    return {ok: true, json: async () => url.startsWith('/api/planning/state') ? state : daily};
  }});
  const settle = async () => { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)); };
  listeners.DOMContentLoaded(); await settle();
  assert.equal(calls.filter(x => x.options.method === 'POST').length, 0);
  get('daily-date').value = '2026-10-20';
  listeners['fitness-view-change']({detail: {view: 'daily'}}); await settle();
  assert.equal(calls.filter(x => x.options.method === 'POST').length, 0);
  state.daily_plans = [];
  listeners['fitness-view-change']({detail: {view: 'daily'}}); await settle();
  const writes = calls.filter(x => x.options.method === 'POST');
  assert.equal(writes.length, 1);
  assert.equal(writes[0].url, '/api/daily-plans/stream');
  assert.deepEqual(JSON.parse(writes[0].options.body), {date: '2026-10-20', conditions: null, mode: 'live'});
  listeners['fitness-state-change']({detail: {profile_version: 2, planning_update: {status: 'failed', message: '模型超时'}}}); await settle();
  assert.equal(calls.filter(x => x.options.method === 'POST').length, 1, 'saved feedback must not trigger an automatic model retry');
  assert.match(get('daily-message').textContent, /反馈已保存.*计划调整未完成.*模型超时/);
  get('daily-date').value = '2026-10-21';
  listeners['fitness-view-change']({detail: {view: 'daily'}}); await settle();
  assert.equal(calls.filter(x => x.options.method === 'POST').length, 1);
});

test('model training and historical local nutrition sources are displayed separately', () => {
  const root = new Element();
  const record = {...daily, trace: {nutrition_source: 'deterministic_local'}, data: {...daily.data,
    decision: {...daily.data.decision, summary: '模型选择今天恢复', assumptions: ['时间按估算'], provider: {status: 'ok'}}}};
  ui.renderDaily(root, record, {}, doc);
  for (const value of ['模型选择今天恢复', '时间按估算', '在线模型', '饮食来源：旧版本地估算']) assert.ok(root.textContent.includes(value), value);
});

test('planning failure keeps questions and marks old plans as not updated', () => {
  assert.equal(typeof ui.planningError, 'function');
  const detail = {status: 'needs_input', message: '需要补充信息', questions: ['今天能练多久？ <script>'], snapshot_token: 'a'.repeat(64)};
  const error = ui.planningError({detail}, 422);
  assert.equal(error.detail.snapshot_token, detail.snapshot_token);
  assert.ok(error.message.includes('今天能练多久？ <script>'));
  const failed = ui.planningError({detail: {status: 'failed', message: '本次模型规划未完成'}}, 502);
  assert.ok(failed.message.includes('尚未按本次条件更新'));
  const existing = ui.planningError({detail: {status: 'failed', message: '工具调用格式不兼容。原有计划尚未按本次条件更新。'}}, 502);
  assert.equal((existing.message.match(/原有计划尚未按本次条件更新/g) || []).length, 1);
});

test('planning failure reports that the original answer was saved', () => {
  const error = ui.planningError({detail: {status: 'failed', message: '生成失败',
    conditions_memory: {status: 'failed', feedback_id: 'feedback-1', message: '补充原文已保存'}}}, 502);
  assert.match(error.message, /补充原文已保存/);
});
