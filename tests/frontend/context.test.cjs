const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../../fitness/static/app.js');

class FakeNode {
  constructor(tagName = null, text = '') {
    this.tagName = tagName ? tagName.toUpperCase() : null;
    this.childNodes = [];
    this.className = '';
    this.dataset = {};
    this.attributes = {};
    this._text = text;
    this.innerHTMLWrites = 0;
  }

  append(...nodes) {
    nodes.forEach((node) => this.childNodes.push(node));
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  get children() {
    return this.childNodes.filter((node) => node.tagName);
  }

  get textContent() {
    return this._text + this.childNodes.map((node) => node.textContent).join('');
  }

  set textContent(value) {
    this._text = value == null ? '' : String(value);
    this.childNodes = [];
  }

  set innerHTML(_value) {
    this.innerHTMLWrites += 1;
    throw new Error('renderers must not write innerHTML');
  }
}

function fakeDocument() {
  const created = [];
  return {
    created,
    createElement(tagName) {
      const element = new FakeNode(tagName);
      created.push(element);
      return element;
    },
    createTextNode(value) {
      const textNode = new FakeNode(null, String(value));
      created.push(textNode);
      return textNode;
    },
  };
}

function descendants(root, predicate) {
  const matches = [];
  const visit = (node) => {
    if (predicate(node)) matches.push(node);
    node.childNodes.forEach(visit);
  };
  visit(root);
  return matches;
}

function withFakeDocument(run) {
  const previous = global.document;
  const document = fakeDocument();
  global.document = document;
  try {
    return run(document);
  } finally {
    if (previous === undefined) delete global.document;
    else global.document = previous;
  }
}

test('optional why explanation renders facts and history safely with no default knowledge cards', () => {
  withFakeDocument(() => {
    const detail = ui.renderBriefExplanation({explanations:[{
      issue:'short_sleep', facts:['sleep_hours=5 <script>'], rule:'先安排恢复',
      history:['14天3次记录平均6小时'], knowledge_ids:['card-1'],
    }]}, {similar_history:{matches:[{date:'2026-10-01', previous_suggestions:['降低训练量'],
       next_observation:{date:'2026-10-02',data:{sleep_hours:7}}, outcome_notice:'未证明因果'}]}});
    assert.equal(detail.tagName, 'DETAILS');
    assert.ok(detail.textContent.includes('为什么这样建议'));
    assert.ok(detail.textContent.includes('sleep_hours=5 <script>'));
    assert.ok(detail.textContent.includes('未证明因果'));
    assert.equal(descendants(detail, n => n.tagName === 'SCRIPT').length, 0);
  });
});

test('refresh preserves live selection only while configured', () => {
  assert.equal(ui.preservedMode('live', {mode:'demo',available_modes:['demo','live']}), 'live');
  assert.equal(ui.preservedMode('live', {mode:'demo',available_modes:['demo']}), 'demo');
});

test('groups one citation under every valid matched feedback issue in input order', () => {
  assert.equal(typeof ui.groupKnowledgeByIssue, 'function');
  const groups = ui.groupKnowledgeByIssue([
    { id: 'a', matched_issues: ['short_sleep', 'training_fatigue', '', null] },
    { id: 'b', matched_issues: ['short_sleep'] },
    { id: 'c', matched_issues: 'diet' },
  ]);

  assert.deepEqual(groups.short_sleep.map((row) => row.id), ['a', 'b']);
  assert.deepEqual(groups.training_fatigue.map((row) => row.id), ['a']);
  assert.equal(groups.diet, undefined);
  assert.equal(groups[''], undefined);
});

test('groups citations without valid issues under the stable fallback group', () => {
  const groups = ui.groupKnowledgeByIssue([
    { id: 'a', matched_issues: ['short_sleep'] },
    { id: 'b', matched_issues: [] },
    { id: 'c' },
  ], 'other');

  assert.deepEqual(groups.short_sleep.map((row) => row.id), ['a']);
  assert.deepEqual(groups.other.map((row) => row.id), ['b', 'c']);
});

test('preserves prototype-shaped issue IDs without throwing or losing citations', () => {
  const groups = ui.groupKnowledgeByIssue([
    { id: 'a', matched_issues: ['__proto__'] },
    { id: 'b', matched_issues: ['constructor'] },
    { id: 'c', matched_issues: [] },
  ], 'other');

  assert.deepEqual(groups.__proto__.map((row) => row.id), ['a']);
  assert.deepEqual(groups.constructor.map((row) => row.id), ['b']);
  assert.deepEqual(groups.other.map((row) => row.id), ['c']);
});

test('uses stable labels while prototype-shaped unknown issues fall back to their IDs', () => {
  assert.equal(typeof ui.feedbackIssueLabel, 'function');
  assert.equal(ui.feedbackIssueLabel('short_sleep'), '睡眠不足');
  assert.equal(ui.feedbackIssueLabel('other'), '其他依据');
  assert.equal(ui.feedbackIssueLabel('__proto__'), '__proto__');
  assert.equal(ui.feedbackIssueLabel('constructor'), 'constructor');
});

test('assigns plan citations to strategies and retains every unmatched source', () => {
  assert.equal(typeof ui.assignPlanKnowledge, 'function');
  const citations = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const assigned = ui.assignPlanKnowledge([
    { id: 'strategy-1', knowledge_item_ids: ['a', 'missing-id'] },
  ], citations);

  assert.deepEqual(assigned.strategies[0].citations.map((row) => row.id), ['a']);
  assert.equal(assigned.strategies[0].supportCount, 1);
  assert.deepEqual(assigned.unmatched.map((row) => row.id), ['b', 'c']);
});

test('retains all plan citations when there are no strategies', () => {
  const assigned = ui.assignPlanKnowledge([], [{ id: 'a' }, { id: 'b' }]);

  assert.deepEqual(assigned.strategies, []);
  assert.deepEqual(assigned.unmatched.map((row) => row.id), ['a', 'b']);
});

test('accepts HTTPS video URLs without rewriting and rejects unsafe protocols', () => {
  assert.equal(typeof ui.safeVideoUrl, 'function');
  const source = 'https://www.bilibili.com/video/BV1?from=knowledge#part-1';

  assert.equal(ui.safeVideoUrl(source), source);
  assert.equal(ui.safeVideoUrl('http://www.bilibili.com/video/BV1'), null);
  assert.equal(ui.safeVideoUrl('javascript:alert(1)'), null);
  assert.equal(ui.safeVideoUrl('data:text/html,unsafe'), null);
  assert.equal(ui.safeVideoUrl('not a url'), null);
});

test('normalizes missing or invalid legacy context lists to empty arrays', () => {
  assert.equal(typeof ui.normalizeContextList, 'function');
  const context = [{ id: 'knowledge-1' }];

  assert.deepEqual(ui.normalizeContextList(), []);
  assert.deepEqual(ui.normalizeContextList(null), []);
  assert.deepEqual(ui.normalizeContextList({ id: 'knowledge-1' }), []);
  assert.equal(ui.normalizeContextList(context), context);
});

test('keeps every safe citation video in order and filters unsafe URLs', () => {
  assert.equal(typeof ui.safeCitationVideos, 'function');
  const videos = [
    { title: '第一集', url: 'https://example.com/video/1' },
    { title: '不安全链接', url: 'http://example.com/video/2' },
    { title: '第二集', url: 'https://example.com/video/3?x=%2F' },
    { title: '脚本链接', url: 'javascript:alert(1)' },
  ];

  assert.deepEqual(
    ui.safeCitationVideos(videos).map((video) => [video.title, video.safeUrl]),
    [
      ['第一集', 'https://example.com/video/1'],
      ['第二集', 'https://example.com/video/3?x=%2F'],
    ],
  );
});

test('renders plan strategies in order with actual counts and unmatched citations', () => {
  assert.equal(typeof ui.renderPlanFoundations, 'function');
  withFakeDocument(() => {
    const shared = { id: 'shared', title: '共享知识' };
    const panel = ui.renderPlanFoundations([
      { id: 'first', title: '第一策略', knowledge_item_ids: ['shared', 'a', 'missing'] },
      { id: 'second', title: '第二策略', knowledge_item_ids: ['shared'] },
    ], [shared, { id: 'a', title: '知识 A' }, { id: 'other', title: '未匹配知识' }]);
    const rows = panel.children.filter((node) => node.className === 'strategy-row');

    assert.deepEqual(rows.map((row) => row.children[0].textContent), [
      '第一策略 · 2 张支持知识卡',
      '第二策略 · 1 张支持知识卡',
      '其他方案依据 · 1 张知识卡',
    ]);
    assert.equal(descendants(rows[0], (node) => node.tagName === 'SUMMARY' && node.textContent === '共享知识').length, 1);
    assert.equal(descendants(rows[1], (node) => node.tagName === 'SUMMARY' && node.textContent === '共享知识').length, 1);
    assert.equal(descendants(rows[2], (node) => node.tagName === 'SUMMARY' && node.textContent === '未匹配知识').length, 1);
  });
});

test('renders only safe citation videos as protected links without innerHTML', () => {
  assert.equal(typeof ui.renderKnowledgeCitation, 'function');
  withFakeDocument((document) => {
    const detail = ui.renderKnowledgeCitation({
      id: 'citation',
      title: '<img src=x onerror=alert(1)>',
      excerpt: '<script>alert(1)</script>',
      creator_name: '<b>作者</b>',
      videos: [
        { title: '安全一', url: 'https://example.com/1' },
        { title: '不安全', url: 'javascript:alert(1)' },
        { title: '安全二', url: 'https://example.com/2' },
      ],
    });
    const links = descendants(detail, (node) => node.tagName === 'A');

    assert.deepEqual(links.map((link) => link.href), ['https://example.com/1', 'https://example.com/2']);
    assert.deepEqual(links.map((link) => [link.target, link.rel]), [
      ['_blank', 'noopener noreferrer'],
      ['_blank', 'noopener noreferrer'],
    ]);
    assert.equal(detail.children[0].textContent, '<img src=x onerror=alert(1)>');
    assert.equal(descendants(detail, (node) => node.textContent.includes('<script>')).length > 0, true);
    assert.equal(document.created.reduce((sum, node) => sum + node.innerHTMLWrites, 0), 0);
  });
});

test('renders advice citations under every issue and keeps issue-less citations', () => {
  assert.equal(typeof ui.renderAdjustmentSources, 'function');
  withFakeDocument(() => {
    const panel = ui.renderAdjustmentSources([
      { id: 'shared', title: '共享建议知识', matched_issues: ['short_sleep', 'training_fatigue'] },
      { id: 'other', title: '无 issue 知识', matched_issues: [] },
    ]);
    const groups = panel.children.filter((node) => node.className === 'strategy-row');

    assert.deepEqual(groups.map((group) => group.children[0].textContent), ['睡眠不足', '训练疲劳', '其他依据']);
    assert.equal(descendants(panel, (node) => node.tagName === 'SUMMARY' && node.textContent === '共享建议知识').length, 2);
    assert.equal(descendants(panel, (node) => node.tagName === 'SUMMARY' && node.textContent === '无 issue 知识').length, 1);
  });
});

test('renders legacy static source IDs with safe links', () => {
  assert.equal(typeof ui.sourceLinks, 'function');
  withFakeDocument(() => {
    const detail = ui.sourceLinks(['safe', 'unsafe'], [
      { id: 'safe', title: '旧安全来源', url: 'https://example.com/source' },
      { id: 'unsafe', title: '旧不安全来源', url: 'http://example.com/source' },
    ]);
    const links = descendants(detail, (node) => node.tagName === 'A');

    assert.equal(links.length, 1);
    assert.equal(links[0].textContent, '旧安全来源');
    assert.equal(links[0].href, 'https://example.com/source');
    assert.equal(links[0].target, '_blank');
    assert.equal(links[0].rel, 'noopener noreferrer');
  });
});

test('assembles plan context without duplicating legacy links for new context', () => {
  assert.equal(typeof ui.renderPlanContextSections, 'function');
  withFakeDocument(() => {
    const sources = [{ id: 'knowledge', title: '旧目录同 ID', url: 'https://example.com/legacy' }];
    const sections = ui.renderPlanContextSections({
      strategy_context: [{ id: 'strategy', title: '策略', knowledge_item_ids: ['knowledge'] }],
      knowledge_context: [{ id: 'knowledge', title: '新知识快照' }],
      source_ids: ['knowledge'],
    }, sources);

    assert.equal(sections.length, 1);
    assert.equal(sections[0].className, 'context-panel');
    assert.equal(descendants(sections[0], (node) => node.tagName === 'SUMMARY' && node.textContent.includes('参考资料')).length, 0);
  });
});

test('assembles plan legacy and empty branches through one mount decision', () => {
  withFakeDocument(() => {
    const sources = [{ id: 'legacy', title: '旧来源', url: 'https://example.com/legacy' }];
    const legacy = ui.renderPlanContextSections({ source_ids: ['legacy'] }, sources);
    const empty = ui.renderPlanContextSections({}, sources);

    assert.equal(legacy.length, 2);
    assert.equal(legacy[0].textContent.includes('本次未采用知识库内容'), true);
    assert.equal(descendants(legacy[1], (node) => node.tagName === 'A').length, 1);
    assert.equal(empty.length, 1);
    assert.equal(empty[0].textContent.includes('本次未采用知识库内容'), true);
  });
});

test('assembles advice new, legacy, and empty branches through one mount decision', () => {
  assert.equal(typeof ui.renderAdviceContextSections, 'function');
  withFakeDocument(() => {
    const sources = [{ id: 'legacy', title: '旧建议来源', url: 'https://example.com/advice' }];
    const modern = ui.renderAdviceContextSections({
      knowledge_context: [{ id: 'new', title: '新建议知识', matched_issues: ['short_sleep'] }],
      source_ids: ['legacy'],
    }, sources);
    const legacy = ui.renderAdviceContextSections({ source_ids: ['legacy'] }, sources);
    const empty = ui.renderAdviceContextSections({}, sources);

    assert.equal(modern.length, 1);
    assert.equal(descendants(modern[0], (node) => node.tagName === 'SUMMARY' && node.textContent === '新建议知识').length, 1);
    assert.equal(descendants(modern[0], (node) => node.tagName === 'A' && node.textContent === '旧建议来源').length, 0);
    assert.equal(legacy.length, 2);
    assert.equal(descendants(legacy[1], (node) => node.tagName === 'A').length, 1);
    assert.equal(empty.length, 1);
    assert.equal(empty[0].textContent.includes('本次未采用知识库内容'), true);
  });
});

test('formats trend metrics with sample counts and explicit insufficient data', () => {
  assert.equal(typeof ui.trendMetricPresentation, 'function');

  assert.deepEqual(ui.trendMetricPresentation('sleep_hours', {
    valid_count: 3,
    average: 6.5,
    minimum: 5.5,
    maximum: 7.5,
    insufficient_data: false,
  }), {
    label: '平均睡眠',
    value: '6.5 小时',
    detail: '3 条有效记录 · 5.5–7.5 小时',
    insufficient: false,
  });
  assert.deepEqual(ui.trendMetricPresentation('weight_kg', {
    valid_count: 1,
    average: 79,
    minimum: 79,
    maximum: 79,
    change: null,
    insufficient_data: true,
  }), {
    label: '平均体重',
    value: '79 kg',
    detail: '1 条有效记录 · 变化数据不足',
    insufficient: true,
  });
});

test('formats explicit zero rates as data instead of missing values', () => {
  assert.deepEqual(ui.trendMetricPresentation('training_completion', {
    valid_count: 2,
    completed_count: 0,
    rate: 0,
    insufficient_data: false,
  }), {
    label: '训练完成率',
    value: '0%',
    detail: '0 / 2 条明确记录',
    insufficient: false,
  });
  assert.deepEqual(ui.trendMetricPresentation('diet_execution', {
    valid_count: 0,
    followed_count: 0,
    rate: null,
    insufficient_data: true,
  }), {
    label: '饮食执行率',
    value: '暂无数据',
    detail: '0 条明确记录',
    insufficient: true,
  });
});
