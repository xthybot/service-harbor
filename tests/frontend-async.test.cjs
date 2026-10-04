const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {AuthLifecycle, Lifetime} = require('../app/static/async-state.js');
const deferred = () => { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; };
const response = (payload, status=200) => ({status,ok:status<400,json:async()=>payload});
const flush = async () => { for(let i=0;i<12;i++) await Promise.resolve(); };

test('auth epoch rejects stale success and 401, including a late JSON body after new login', async()=>{
  let invalid=0;const network=[];const auth=new AuthLifecycle(()=>{const d=deferred();network.push(d);return d.promise;},()=>invalid++);
  auth.advance(true);
  const first=auth.request('/api/services').catch(e=>e);
  const second=auth.request('/api/services').catch(e=>e);
  const body=deferred();network[1].resolve({status:200,ok:true,json:()=>body.promise});await flush();
  auth.advance(false);auth.advance(true);
  network[0].resolve(response({},401));body.resolve({old:true});
  assert.equal((await first).stale,true);assert.equal((await second).stale,true);assert.equal(invalid,0);assert.equal(auth.authenticated,true);
});

test('login 401 retains server detail; SSE session checks deduplicate, back off and identify revocation',async()=>{
  let calls=0,invalid=0;let next=deferred();const auth=new AuthLifecycle(()=>{calls++;return next.promise;},()=>{invalid++;auth.advance(false);});
  const login=auth.request('/api/login').catch(e=>e);next.resolve(response({detail:'Incorrect password. Try again.'},401));
  assert.match((await login).message,/Incorrect password/);assert.equal(invalid,0);
  auth.advance(true);next=deferred();const a=auth.checkSession(100),b=auth.checkSession(100);assert.equal(calls,2);
  next.reject(new Error('offline'));assert.equal(await a,null);assert.equal(await b,null);assert.equal(await auth.checkSession(200),null);assert.equal(calls,2);
  next=deferred();const c=auth.checkSession(2000);next.resolve(response({authenticated:false}));assert.equal(await c,false);assert.equal(invalid,1);assert.equal(auth.authenticated,false);
});

function harness() {
  const nodes=new Map(),requests=[],events=[],sources=[];
  class Node {
    constructor(id=''){this.id=id;this.hidden=false;this.open=false;this.value=/filter|severity/.test(id)?'all':'';this.dataset={};this.style={};this.listeners={};this.children=[];this.textContent='';this.innerHTML='';this.disabled=false;this.isConnected=true;this.classList={set:new Set(),add(...xs){xs.forEach(x=>this.set.add(x));},remove(...xs){xs.forEach(x=>this.set.delete(x));},contains(x){return this.set.has(x);},toggle(x,on){if(on===undefined)on=!this.set.has(x);if(on)this.set.add(x);else this.set.delete(x);}};}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    removeEventListener(type,fn){this.listeners[type]=(this.listeners[type]||[]).filter(x=>x!==fn);}
    async emit(type,extra={}){for(const fn of [...(this.listeners[type]||[])])await fn({target:this,preventDefault(){},...extra});}
    setAttribute(){} removeAttribute(){} focus(){document.activeElement=this;} select(){} append(...items){this.children.push(...items);} replaceChildren(...items){this.children=items;} remove(){} closest(){return null;} querySelector(){return new Node();} querySelectorAll(){return [];} contains(){return false;} getClientRects(){return [];} matches(){return false;} showModal(){this.open=true;} close(){this.open=false;this.emit('close');}
  }
  const node=id=>{if(!nodes.has(id))nodes.set(id,new Node(id));return nodes.get(id);};
  const document={activeElement:null,body:new Node('body'),querySelector:selector=>node(selector.replace(/^#/,'')),getElementById:node,querySelectorAll:()=>[],createElement:()=>new Node(),addEventListener(){}};
  const window={HostAsync:{AuthLifecycle,Lifetime},addEventListener(){},dispatchEvent:e=>events.push(e)};
  class Source {constructor(url){this.url=url;this.listeners={};sources.push(this);}close(){this.closed=true;}addEventListener(type,fn){this.listeners[type]=fn;}}
  const context={window,document,fetch:(url,options)=>{const d=deferred();requests.push({url,options,...d});return d.promise;},EventSource:Source,Event:class{constructor(type){this.type=type;}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},URL,URLSearchParams,Intl,Date,Option:Node,AbortController,location:{hostname:'example.invalid',origin:'http://example.invalid',hash:'#services',port:'8765',protocol:'http:'},navigator:{},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){},requestAnimationFrame:()=>{},console};
  // Export closure internals only inside this VM; production source is unchanged.
  const code=fs.readFileSync(require.resolve('../app/static/app.js'),'utf8').replace('  init();','  window.__test = {state,auth,showLogin,openServiceDetail,closeDrawer,loadStatus,loadRecentLogs,startLogStream,toggleServiceFavorite,renderPorts,updateDrawerSummary,logout,bindEvents,refreshAll,trackingCheck};');
  vm.runInNewContext(code,context);const api=window.__test;api.auth.advance(true);api.bindEvents();
  const answer=(url,payload,status=200)=>{const r=requests.find(r=>!r.done&&r.url===url);assert.ok(r,`missing request ${url}`);r.done=true;r.resolve(response(payload,status));return r;};
  const service=id=>({id,name:id,display_name:id,description:'demo',category:'Tools',scope:'user',unit:id+'.service',managed:true,status:'Running',host_id:'local'});
  api.state.services=[service('A'),service('B')];return {api,node,nodes,requests,answer,sources,events,service,document,window,context};
}

test('actual drawer: A→B and same-service reopening reject late status/recent successes and errors',async()=>{
  const h=harness();h.api.openServiceDetail('A');h.api.openServiceDetail('B');
  h.answer('/api/services/B/status',{status:'B current'});h.answer('/api/services/B/logs?lines=150',{lines:['B current'],cursor:'b',identity:'B'});await flush();
  h.answer('/api/services/A/status',{detail:'old failure'},500);h.answer('/api/services/A/logs?lines=150',{lines:['A stale'],cursor:'a',identity:'A'});await flush();
  assert.equal(h.node('status-output').textContent,'B current');assert.deepEqual([...h.api.state.logLines],['B current']);
  h.api.openServiceDetail('A');const oldStatus=h.requests.at(-2),oldLogs=h.requests.at(-1);h.api.closeDrawer();h.api.openServiceDetail('A');
  oldStatus.resolve(response({status:'same-id stale'}));oldLogs.resolve(response({lines:['same-id stale']}));await flush();
  assert.equal(h.node('status-output').textContent,'Loading status…');assert.deepEqual([...h.api.state.logLines],[]);
});

test('actual logs: Pause wins over pending Recent; cursor is passed and equal text events remain distinct',async()=>{
  const h=harness();h.api.openServiceDetail('A');await h.node('log-pause').emit('click');
  h.answer('/api/services/A/logs?lines=150',{lines:['identical'],cursor:'c1',identity:'identityA'});await flush();
  assert.equal(h.sources.length,0);assert.equal(h.api.state.desiredFollow,false);
  await h.node('log-pause').emit('click');h.answer('/api/services/A/logs?lines=150',{lines:['identical'],cursor:'c1',identity:'identityA'});await flush();
  assert.equal(h.sources.length,1);assert.match(h.sources[0].url,/cursor=c1/);assert.match(h.sources[0].url,/identity=identityA/);assert.match(h.sources[0].url,/lines=0/);
  h.sources[0].onmessage({data:JSON.stringify({line:'identical'}),lastEventId:'c2'});
  assert.deepEqual([...h.api.state.logLines],['identical','identical']);assert.equal(h.api.state.logCursor,'c2');
  h.sources[0].listeners.gap({data:'{}'});assert.match(h.node('log-live-label').textContent,/gap/);
});

test('actual favorite completion updates latest object by ID and selected button follows current busy state',async()=>{
  const h=harness();const pending=h.api.toggleServiceFavorite('A');const replacement={...h.service('A'),description:'fresh Live value'};h.api.state.services[0]=replacement;
  h.api.state.favoriteBusy.add('B');h.api.openServiceDetail('B');assert.equal(h.node('drawer-favorite').disabled,true);
  h.answer('/api/services/A/favorite',{favorite:true});await pending;
  assert.equal(replacement.favorite,true);assert.equal(replacement.description,'fresh Live value');assert.equal(h.node('drawer-favorite').disabled,true);
  assert.ok(h.events.some(e=>e.type==='dashboard:inventory'&&e.detail.services[0].favorite));
});

test('actual identity edit closes old SSE; old messages cannot repopulate new drawer',async()=>{
  const h=harness();h.api.openServiceDetail('A');h.answer('/api/services/A/logs?lines=150',{lines:['old'],cursor:'c1',identity:'old'});await flush();const old=h.sources[0];
  h.api.state.services[0]={...h.service('A'),host_id:'other',unit:'new.service'};h.api.updateDrawerSummary();assert.equal(old.closed,true);
  old.onmessage({data:JSON.stringify({line:'late old host'}),lastEventId:'c2'});assert.deepEqual([...h.api.state.logLines],[]);
});

test('same remote host ID with changed transport identity clears paused drawer logs',async()=>{
  const h=harness();h.api.state.services[0]={...h.service('A'),host_id:'remote',execution_identity:'first'};
  h.api.openServiceDetail('A');await h.node('log-pause').emit('click');
  h.answer('/api/services/A/logs?lines=150',{lines:['old host log'],cursor:'c1',identity:'first'});await flush();
  assert.deepEqual([...h.api.state.logLines],['old host log']);
  h.api.state.services[0]={...h.api.state.services[0],execution_identity:'second'};
  h.api.updateDrawerSummary();
  assert.deepEqual([...h.api.state.logLines],[]);
  assert.equal(h.api.state.desiredFollow,false);
});

test('logout in flight blocks login and a stale completion cannot replace newer UI',async()=>{
  const h=harness();h.window.HostInputLimits={validatePassword:value=>value,passwordPolicy:async()=>({})};
  const old=h.api.logout();
  await h.node('login-form').emit('submit');
  assert.equal(h.requests.filter(r=>r.url==='/api/login').length,0);
  h.api.auth.advance(true);
  h.answer('/api/logout',{});await old;
  assert.notEqual(h.node('login-error').textContent,'Signed out.');
});

test('actual logout failure hides data, offers retry, cancels requests and closes confirmations',async()=>{
  const h=harness();let cancelled=0;h.api.state.confirmCleanup=()=>cancelled++;h.api.openServiceDetail('A');
  const p=h.api.logout();h.answer('/api/logout',{detail:'Denied'},403);await p;
  assert.equal(h.node('app-shell').hidden,true);assert.equal(h.node('logout-retry').hidden,false);assert.match(h.node('login-error').textContent,/not confirmed/);assert.equal(cancelled,1);assert.equal(h.api.state.services.length,0);
  const r=h.requests.find(r=>r.url.endsWith('/status'));assert.equal(r.options.signal.aborted,true);
  const retry=h.api.logout();h.answer('/api/logout',{});await retry;assert.equal(h.node('logout-retry').hidden,true);assert.equal(h.node('login-error').textContent,'Signed out.');
});

test('actual empty port filter renders an empty-result message',()=>{const h=harness();h.api.state.ports=[];h.api.renderPorts();assert.match(h.node('ports-list').innerHTML,/No port records match/);});

test('actual import dialog sends skip without conflicts and confirmed token with conflicts',async()=>{
  async function scenario(conflicts){
    const h=harness();
    h.window.HostInputLimits={readBounded:async()=>JSON.stringify({format:'host-service-dashboard-services',version:1,services:[]}),stringifyBounded:JSON.stringify,MAX_IMPORT_BYTES:1048576};
    h.node('config-export-target').options=[];
    vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/config-transfer.js'),'utf8'),h.context);
    h.node('import-services-file').files=[{name:'example.json',size:80,stream:()=>({})}];
    const file=h.node('import-services-file').emit('change');
    await flush();
    h.answer('/api/services/import/preview',{added:0,updated:conflicts.length,hosts_added:0,conflicts,preview_token:'test-token'});
    await file;
    assert.equal(h.node('config-import-modal').open,true);
    const button=h.node('config-import-confirm').emit('click');
    await flush();
    const url=`/api/services/import?overwrite=${conflicts.length>0}`;
    const request=h.requests.find(r=>r.url===url);
    assert.ok(request);
    assert.equal(request.options.headers['X-Import-Preview'],'test-token');
    if(conflicts.length>5) assert.match(h.node('config-import-conflicts').textContent,/last conflict/);
    h.answer(url,{added:0,updated:conflicts.length,skipped:0,hosts_added:0});
    // Refresh requests intentionally remain pending; the test checks the sent import request.
    await flush();
    void button;
  }
  await scenario([]);
  await scenario(Array.from({length:6},(_,i)=>({id:`svc-${i}`,name:i===5?'last conflict':`conflict ${i}`})));
});

test('actual modal manager closes only top layer, traps Ctrl+K and restores focus',()=>{
  const callbacks={},nodes=new Map(),roots=[];
  const doc={activeElement:null,body:{},querySelectorAll:()=>roots,getElementById:id=>nodes.get(id),addEventListener:(name,fn)=>{callbacks[name]=fn;}};
  class Element {
    constructor(id,tagName='DIV'){this.id=id;this.tagName=tagName;this.hidden=true;this.open=false;this.isConnected=true;this.children=[];
      this.classList={contains:value=>value==='open'&&this.open};nodes.set(id,this);}
    contains(item){return this.children.includes(item);} querySelectorAll(){return this.children;}
    closest(){return null;}focus(){doc.activeElement=this;}click(){}
    dispatchEvent(){return true;}close(){this.open=false;}
    querySelector(){return null;}
  }
  const trigger=new Element('trigger');trigger.focus();
  const modal=new Element('rename-modal');const input=new Element('modal-input','INPUT');modal.children=[input];
  const cancel=new Element('rename-cancel','BUTTON');cancel.click=()=>{modal.hidden=true;};
  const dialog=new Element('config-import-modal','DIALOG');const action=new Element('dialog-action','BUTTON');dialog.children=[action];
  roots.push(modal,dialog);
  const window={};let observer;
  const context={document:doc,window,Event:class{constructor(type,opts){this.type=type;this.cancelable=opts?.cancelable;}},MutationObserver:class{constructor(fn){observer=fn;}observe(){}}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/modal-state.js'),'utf8'),context);
  modal.hidden=false;observer();assert.equal(window.HostModals.top(),modal);assert.equal(doc.activeElement,input);
  dialog.open=true;observer();assert.equal(window.HostModals.top(),dialog);assert.equal(doc.activeElement,action);
  let blocked=0;const evt=(key,more={})=>({key,preventDefault(){blocked++;},stopImmediatePropagation(){blocked++;},...more});
  callbacks.keydown(evt('k',{ctrlKey:true}));assert.equal(blocked,2);assert.equal(doc.activeElement,action);
  callbacks.keydown(evt('Escape'));assert.equal(dialog.open,false);assert.equal(modal.hidden,false);assert.equal(window.HostModals.top(),modal);assert.equal(doc.activeElement,input);
  callbacks.keydown(evt('Escape'));assert.equal(modal.hidden,true);assert.equal(window.HostModals.top(),null);assert.equal(doc.activeElement,trigger);
});

test('actual Hosts load queues a second fetch when refresh arrives during a pending load',async()=>{
  const h=harness(),listeners={};
  h.window.addEventListener=(type,fn)=>{(listeners[type]??=[]).push(fn);};
  vm.runInNewContext(fs.readFileSync(require.resolve('../app/static/hosts.js'),'utf8'),h.context);
  const first=listeners['dashboard:ready'][0]();await flush();
  assert.equal(h.requests.filter(r=>r.url==='/api/hosts').length,1);
  await listeners['dashboard:ready'][0]();
  h.answer('/api/hosts',{hosts:[]});h.answer('/api/ssh-key',{public_key:'',fingerprint:''});await first;await flush();
  assert.equal(h.requests.filter(r=>r.url==='/api/hosts').length,2);
  h.answer('/api/hosts',{hosts:[]});h.answer('/api/ssh-key',{public_key:'',fingerprint:''});await flush();
});
