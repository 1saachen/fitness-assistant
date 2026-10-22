const assert = require('node:assert/strict');
const test = require('node:test');
let ui = {};
try { ui = require('../../fitness/static/app.js'); } catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
test('blank fields remain unknown and zero remains a real value', () => {
  assert.equal(typeof ui.fieldValue, 'function');
  assert.equal(ui.fieldValue('', 'number'), null);
  assert.equal(ui.fieldValue('0', 'number'), 0);
  assert.equal(ui.fieldValue('', 'boolean'), null);
  assert.equal(ui.fieldValue('false', 'boolean'), false);
});
test('profile starts unknown and has no required-field validation', () => {
  const source = require('node:fs').readFileSync(require('node:path').join(__dirname, '../../fitness/static/app.js'), 'utf8');
  const profileForm = source.slice(source.indexOf('function renderProfile'), source.indexOf('function readProfile'));
  assert.doesNotMatch(profileForm, /input\.required\s*=\s*true/);
  assert.match(source, /age_years: null/);
  assert.match(source, /primary: null/);
  assert.match(source, /deadline_negotiable: null/);
});
test('training frequency field accepts a user-written weekly or training-rest rhythm', () => {
  const source = require('node:fs').readFileSync(require('node:path').join(__dirname, '../../fitness/static/app.js'), 'utf8');
  assert.match(source, /training\.training_frequency", "训练频率", "text"/);
  assert.match(source, /一周4练、练3休1/);
});
test('editing a nested value preserves nullable fields and original object', () => {
  assert.equal(typeof ui.mergeFields, 'function');
  const profile = { personal: { weight_kg: null, body_fat_measured_on: null }, recovery: { sleep_schedule: 'variable' } };
  const result = ui.mergeFields(profile, [{ path: 'personal.weight_kg', value: '0', type: 'number' }]);
  assert.equal(result.personal.weight_kg, 0);
  assert.equal(result.personal.body_fat_measured_on, null);
  assert.equal(result.recovery.sleep_schedule, 'variable');
  assert.equal(profile.personal.weight_kg, null);
});
