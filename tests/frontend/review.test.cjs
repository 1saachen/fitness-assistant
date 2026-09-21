const assert = require('node:assert/strict');
const test = require('node:test');
const ui = require('../../fitness/static/app.js');

const cards = [
  { id: 'a', collection: 'supplements', title: '肌酸', review_status: 'pending' },
  { id: 'b', collection: 'training', title: '力量训练', review_status: 'approved' },
  { id: 'c', collection: 'sleep_recovery', title: '睡眠恢复', review_status: 'rejected' },
];

test('knowledge review filters by collection, status, and query', () => {
  assert.deepEqual(ui.filterReviewCards(cards, { collection: 'training', status: 'all', query: '' }).map(x => x.id), ['b']);
  assert.deepEqual(ui.filterReviewCards(cards, { collection: 'all', status: 'approved', query: '' }).map(x => x.id), ['b']);
  assert.deepEqual(ui.filterReviewCards(cards, { collection: 'all', status: 'all', query: '睡眠' }).map(x => x.id), ['c']);
});

test('review status labels remain user-facing and stable', () => {
  assert.equal(ui.reviewLabel('pending'), '待审核');
  assert.equal(ui.reviewLabel('approved'), '已批准');
  assert.equal(ui.reviewLabel('rejected'), '已拒绝');
});
