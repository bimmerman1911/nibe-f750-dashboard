import {test} from 'node:test';
import assert from 'node:assert/strict';
import {chartActivity} from '../dist/nibe-f750-smart-card.js';
const t=Date.parse('2026-11-11T15:45:00Z');
test('sixteen minutes across three quarters remains 45 s, 900 s and 15 s',()=>{
  const rows=[{start:(t+855000)/1000,end:(t+1815000)/1000,action:'dhw',inline_kw:0}];
  assert.deepEqual([0,1,2].map(i=>chartActivity(rows,t+i*900000,t+(i+1)*900000).reduce((v,r)=>v+r.end-r.start,0)),[45000,900000,15000]);
});
test('normalised display accepts milliseconds and clips zoom boundaries',()=>{
  const a=chartActivity([{start:t,end:t+900000,action:'heat',inline_kw:1}],t+300000,t+600000);
  assert.deepEqual(a,[{start:t+300000,end:t+600000,action:'heat',inline_kw:1}]);
  assert.equal(chartActivity(undefined,t,t+900000),null);
});
test('invalid and overlapping activity cannot double-fill a price bar',()=>{
  const rows=[{start:t,end:t+60000,action:'dhw'}, {start:t+30000,end:t+90000,action:'heat'}, {start:NaN,end:t+60000,action:'dhw'}, {start:t,end:t+60000,action:'bad'}];
  const a=chartActivity(rows,t,t+900000);
  assert.equal(a.length,1);assert.equal(a[0].action,'dhw');
});
