const test = require('node:test');
const assert = require('node:assert/strict');
const limits = require('../app/static/input-limits.js');
const policy = require('../app/static/password-policy.json');
test('Unicode password limits and controls', () => {
  for (const value of ['a', 'a'.repeat(256), '😀'.repeat(256)]) assert.equal(limits.validatePassword(value,policy), value);
  for (const value of ['', 'a'.repeat(257), 'a\nb', '\ud800']) assert.throws(()=>limits.validatePassword(value,policy));
});
test('stream stops and cancels at limit before reading more', async () => {
  let reads=0,cancelled=false;
  const stream={getReader:()=>({read:async()=>{reads++;return {done:false,value:new Uint8Array(reads===1 ? 1024*1024 : 1)};},cancel:async()=>{cancelled=true;},releaseLock(){}})};
  await assert.rejects(limits.readBounded(stream));
  assert.equal(reads,2);assert.equal(cancelled,true);
});
test('exact byte limit accepted, serialization enlargement rejected', async () => {
  const stream = new Blob([' '.repeat(1024*1024-2)+'{}']).stream();
  assert.equal((await limits.readBounded(stream)).length,1024*1024);
  assert.throws(()=>limits.stringifyBounded({value:'😀'.repeat(300000)}));
});
