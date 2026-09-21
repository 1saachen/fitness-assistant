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
test('editing a nested value preserves nullable fields and original object', () => {
  assert.equal(typeof ui.mergeFields, 'function');
  const profile = { personal: { weight_kg: null, body_fat_measured_on: null }, recovery: { sleep_schedule: 'variable' } };
  const result = ui.mergeFields(profile, [{ path: 'personal.weight_kg', value: '0', type: 'number' }]);
  assert.equal(result.personal.weight_kg, 0);
  assert.equal(result.personal.body_fat_measured_on, null);
  assert.equal(result.recovery.sleep_schedule, 'variable');
  assert.equal(profile.personal.weight_kg, null);
});
