/* Chrome against --managed fixture: fake systemd, real HTTP/TCP, no host commands. */
const fs=require('node:fs'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fixture=JSON.parse(fs.readFileSync(process.env.FIXTURE_LOG||'/tmp/service-harbor-managed-fixture.log','utf8').split('\n')[0]);
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1500,height:1000}});context.setDefaultTimeout(15000);
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const card=id=>page.locator(`.service-card[data-service-id="${id}"]`);
 const metrics=async()=> (await context.request.get(fixture.http+'/_metrics')).json();
 const close=async()=>{await page.locator('button[data-close-drawer]').click();await page.locator('#detail-drawer').waitFor({state:'hidden'});};
 const mark=text=>console.log('PASS '+text);
 try{
  const initialProbeCount=(await metrics())['/_tcp_probe']||0;
  await page.goto(fixture.dashboard+'/#services');await page.locator('#login-password').fill('isolated-browser-only');await page.locator('#login-form button[type=submit]').click();
  await card('svc-managed-running').waitFor();
  assert.deepEqual(await page.locator('#services-view .summary-grid .summary-card').evaluateAll(cards=>cards.map(card=>card.dataset.summaryFilter)),['all','Running','Connectivity','Stopped','Failed']);
  mark('Services summary order puts Connectivity issues third');
  assert.equal((await metrics())['/_tcp_probe']||0,initialProbeCount);
  assert.equal(await page.locator('#count-running').textContent(),'1');assert.equal(await page.locator('#count-connectivity').textContent(),'4');
  for(const [id,cls] of [['svc-managed-running','status-warning'],['svc-managed-failed','status-failed'],['svc-managed-stopped','status-stopped'],['svc-website','status-warning']]){
   assert.ok((await card(id).locator('.service-status-light').getAttribute('class')).includes(cls));
   assert.match(await card(id).textContent(),/HTTP Unreachable/);
  }
  await page.locator('[data-summary-filter=Connectivity]').click();assert.equal(await page.locator('#status-filter-page').inputValue(),'Connectivity');assert.equal(await page.locator('.service-card').count(),4);
  mark('Running+HTTP failure is yellow, Failed red, Stopped gray+warning; standalone website yellow; summary filter counts all four');
  await card('svc-managed-running').click();
  await page.waitForFunction(()=>document.querySelector('#drawer-meta').textContent.includes('HTTP Unreachable'));
  assert.match(await page.locator('#drawer-meta').textContent(),/Running/);
  assert.match(await page.locator('#drawer-meta').textContent(),/Checked/);
  await page.locator('#drawer-rename').click();await page.locator('#rename-modal').waitFor({state:'visible'});
  assert.equal(await page.locator('#service-unit').inputValue(),'fixture-running.service');assert.equal(await page.locator('#service-check-method').isVisible(),true);
  await page.locator('#service-check-method').selectOption('tcp');await page.locator('#service-port').fill(String(fixture.tcp_port));
  const save=page.waitForResponse(r=>r.url().endsWith('/svc-managed-running/edit')&&r.request().method()==='PUT');
  await page.locator('#rename-form button[type=submit]').click();assert.equal((await save).status(),200);await page.locator('#rename-modal').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#drawer-meta').textContent.includes('TCP Reachable'));
  assert.match(await page.locator('#drawer-meta').textContent(),/Running/);
  assert.equal((await metrics())['/_tcp_probe']||0,initialProbeCount);
  const checked=await (await context.request.get(fixture.dashboard+'/api/services/svc-managed-running/live')).json();
  assert.equal(checked.service.website_result.target,`127.0.0.1:${fixture.tcp_port}`);
  mark('managed editor derives TCP from Open URL host and Service Port; systemd remains Running');
  await page.locator('#drawer-rename').click();await page.locator('#rename-modal').waitFor({state:'visible'});await page.locator('#service-check-method').selectOption('http');
  const again=page.waitForResponse(r=>r.url().endsWith('/svc-managed-running/edit')&&r.request().method()==='PUT');await page.locator('#rename-form button[type=submit]').click();assert.equal((await again).status(),200);await page.locator('#rename-modal').waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.querySelector('#drawer-meta').textContent.includes('HTTP Unreachable'));await close();
  await page.locator('a[data-nav=overview]').click();await page.locator('[data-ov-open-service="svc-managed-running"]').first().waitFor();
  assert.equal(await page.locator('[data-ov-port="port-associated"]').count(),0);
  await page.locator('[data-ov-open-service="svc-managed-running"]').first().click();
  await page.waitForURL('**/#services');await page.locator('#detail-drawer.open').waitFor();assert.equal(await page.locator('#drawer-title').textContent(),'Managed running');assert.equal(await page.locator('#status-filter-page').inputValue(),'all');
  mark('Overview HTTP failure opens Services+matching drawer, clears filters, deduplicates associated Port failures');
  await close();await page.locator('a[data-nav=overview]').click();
  if(await page.locator('#ov-attention-expand').isVisible()) await page.locator('#ov-attention-expand').click();
  await page.locator('[data-ov-port="port-standalone"]').click();await page.waitForURL('**/#ports');
  await page.locator('.port-row.is-selected[data-port-id="port-standalone"]').waitFor();assert.ok((await metrics())['/_tcp_probe']>initialProbeCount);
  mark('standalone Port failure opens Open ports and selects its row; explicit Open ports checks still run');
  await page.locator('a[data-nav="add-service"]').click();await page.locator('#add-display-name').fill('New managed website');await page.locator('#add-unit').fill('fixture-new.service');
  assert.equal(await page.locator('#add-check-method').isVisible(),true);await page.locator('#add-open-url').fill(fixture.https+'/status/200');await page.locator('#add-check-method').selectOption('http');
  const create=page.waitForResponse(r=>r.url()===fixture.dashboard+'/api/services'&&r.request().method()==='POST');await page.locator('#add-register').click();const response=await create;assert.equal(response.status(),200);const id=(await response.json()).service.id;
  await page.waitForFunction(()=>document.querySelector('#add-form-feedback').textContent.includes('✓'));await page.locator('a[data-nav=services]').click();await card(id).waitFor();assert.match(await card(id).textContent(),/HTTP Reachable/);
  assert.ok((await card(id).locator('.service-status-light').getAttribute('class')).includes('status-running'));
  mark('new managed unit accepts HTTPS check and displays both Running and HTTP Reachable');
  await page.screenshot({path:'/tmp/service-harbor-connectivity-services.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  const width=await page.evaluate(()=>[document.documentElement.scrollWidth,innerWidth]);assert.ok(width[0]<=width[1],JSON.stringify(width));
  await page.screenshot({path:'/tmp/service-harbor-connectivity-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);mark('mobile layout fits viewport; no uncaught browser errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
