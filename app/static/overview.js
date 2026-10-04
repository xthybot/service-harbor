/* Overview composes existing inventory; it never starts background polling. */
(() => {
  const $ = selector => document.querySelector(selector);
  const { navigate, selectCheckTarget, displayName, getOpenUrl, canOpen } = window.HostDashboard;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let services = [], ports = [], hosts = [], loaded = false, hostsLoaded = false;
  let attentionFilter = 'all', attentionExpanded = false, favoritesExpanded = false, frame = null;
  const stamp = value => value ? `Checked ${new Date(value).toLocaleString()}` : 'Not checked';
  const newest = rows => rows.map(row => row.checked_at).filter(Boolean).sort().at(-1);
  const name = service => displayName(service);
  const badge = status => `<span class="ov-badge ov-${status === 'Running' || status === 'Open' ? 'good' : status === 'Failed' ? 'bad' : status === 'Unavailable' || status === 'Unreachable' ? 'warn' : 'neutral'}">${esc(status)}</span>`;
  function go(page) { location.hash = '#' + page; navigate(); }
  function openHost(id) {
    $('#service-host-filter').value = id;
    $('#service-search-page').value = '';
    $('#status-filter-page').value = 'all';
    $('#category-filter-page').value = 'all';
    // Use the existing scope handler to reset scope and refresh once.
    go('services');
    $('[data-scope="all"]').click();
  }
  function openPort(port) {
    $('#port-host-filter').value = 'all';
    $('#port-search').value = '';
    go('ports');
    selectCheckTarget(port.manual ? 'manual-port' : 'configured-port', port.manual ? port.id : port.service_id);
    const row = [...document.querySelectorAll('.port-row')].find(item => item.dataset.portId === (port.manual ? port.id : port.service_id) && item.dataset.portKind === (port.manual ? 'manual-port' : 'configured-port'));
    row?.scrollIntoView({block:'center', behavior:'smooth'});
  }
  function issues() {
    return [
      ...services.filter(item => item.status === 'Failed').map(item => ({kind:'failed', service:item, label:'Failed', reason:item.error || 'systemd reports a failed unit.'})),
      ...services.filter(item => item.status === 'Unavailable').map(item => ({kind:'unavailable', service:item, label:'Unavailable', reason:item.error || 'Service state could not be read.'})),
      ...ports.filter(item => ['Unreachable','Unavailable'].includes(item.status)).map(item => ({kind:'ports', port:item, label:item.status, reason:item.error || 'TCP connection could not be established.'}))
    ];
  }
  function renderAttention() {
    const all = issues();
    $('#ov-attention-count').textContent = loaded ? all.length : '—';
    $('#ov-attention-filters').hidden = !loaded || !all.length;
    $('#ov-attention-filters').innerHTML = [['all','All'],['failed','Failed services'],['unavailable','Unavailable services'],['ports','TCP ports']].map(([kind,label]) => `<button type="button" data-ov-filter="${kind}" data-ov-key="filter-${kind}" aria-pressed="${attentionFilter === kind}">${label} <span>${kind === 'all' ? all.length : all.filter(item => item.kind === kind).length}</span></button>`).join('');
    const filtered = all.filter(item => attentionFilter === 'all' || item.kind === attentionFilter);
    $('#ov-attention-expand').hidden = filtered.length <= 5;
    $('#ov-attention-expand').textContent = attentionExpanded ? 'Show less ↑' : `View all ${filtered.length} →`;
    if (!loaded) { $('#ov-attention-list').innerHTML = '<p class="ov-empty">Waiting for the first inventory check…</p>'; return; }
    if (!all.length) { $('#ov-attention-list').innerHTML = '<p class="ov-clear"><span>✓</span> No failed services, unavailable queries or unreachable ports in the latest results.</p>'; return; }
    $('#ov-attention-list').innerHTML = (attentionExpanded ? filtered : filtered.slice(0,5)).map(item => {
      const record = item.service || item.port;
      const title = item.service ? name(record) : `${record.name} · ${record.port}`;
      const target = item.service ? `data-open-detail="${esc(record.id)}"` : `data-ov-port="${esc(record.id)}"`;
      return `<button type="button" class="ov-issue" ${target} data-ov-key="issue-${item.kind}-${esc(record.id)}"><span class="ov-issue-symbol ${item.kind === 'failed' ? 'is-failed' : ''}" aria-hidden="true">${item.kind === 'failed' ? '!' : '↯'}</span><span class="ov-issue-copy"><strong>${esc(title)}</strong><span>${esc(record.host_name || 'This host')} · ${item.service ? 'Service' : 'TCP port'}</span><small title="${esc(item.reason)}">${esc(item.reason)}</small></span><span class="ov-issue-meta">${badge(item.label)}<small>${esc(stamp(record.checked_at))}</small></span><span aria-hidden="true">›</span></button>`;
    }).join('') || '<p class="ov-empty">No items in this category.</p>';
  }
  function renderFavorites() {
    const favorites = services.filter(item => item.favorite);
    $('#ov-favorites-count').textContent = loaded ? favorites.length : '—';
    $('#ov-favorites-expand').hidden = favorites.length <= 6;
    $('#ov-favorites-expand').textContent = favoritesExpanded ? 'Show less ↑' : `View all ${favorites.length} →`;
    $('#ov-favorites').innerHTML = !loaded ? '<p class="ov-empty">Loading favorites…</p>' : !favorites.length ? '<div class="ov-empty ov-favorites-empty"><span>☆</span><strong>Your everyday services, one click away.</strong><p>Add stars in Services to keep your shortcuts here.</p><a href="#services" class="ov-text-button">Choose favorites →</a></div>' : (favoritesExpanded ? favorites : favorites.slice(0,6)).map(service => {
      const url = getOpenUrl(service);
      return `<article class="ov-favorite-row" data-ov-service="${esc(service.id)}" tabindex="0" aria-label="View ${esc(name(service))} details"><span class="ov-service-mark" aria-hidden="true">${esc([...name(service)][0] || 'S')}</span><div class="ov-favorite-row-copy"><button type="button" class="ov-favorite-row-name" data-open-detail="${esc(service.id)}" data-ov-key="favorite-${esc(service.id)}">${esc(name(service))}</button><span>${esc(service.host_name || 'This host')}${service.configured_port ? ` · Port ${esc(service.configured_port)}` : ''}</span><small>${esc(service.managed ? stamp(service.checked_at) : 'Website / unmanaged entry')}</small></div><div class="ov-favorite-row-meta">${badge(service.status)}<div class="ov-favorite-row-tools">${url && canOpen(service) ? `<a href="${esc(url)}" class="ov-text-button" target="_blank" rel="noopener noreferrer" aria-label="Open ${esc(name(service))}">↗ Open</a>` : ''}<button type="button" class="favorite-indicator is-favorite" data-toggle-favorite="${esc(service.id)}" data-ov-key="star-${esc(service.id)}" aria-label="Remove ${esc(name(service))} from favorites" aria-pressed="true">★</button></div></div></article>`;
    }).join('');
  }
  function renderHosts() {
    const items = [{id:'local', name:'This host', address:location.hostname}, ...hosts];
    $('#ov-hosts').innerHTML = items.map(host => {
      const rows = services.filter(service => (service.host_id || 'local') === host.id && service.service_type !== 'external');
      const managed = rows.filter(item => item.managed !== false);
      const unavailable = managed.filter(item => item.status === 'Unavailable').length;
      const result = !loaded ? 'Not checked' : unavailable ? `${unavailable} queries unavailable` : managed.length ? 'Service queries available' : 'No unit queries';
      return `<div class="ov-host"><button class="ov-host-link" type="button" data-ov-host="${esc(host.id)}" data-ov-key="host-${esc(host.id)}"><span class="ov-host-symbol" aria-hidden="true">▣</span><span><strong>${esc(host.name)}</strong><small>${esc(host.id === 'local' ? host.address : `${host.username}@${host.address}:${host.port}`)}</small></span><span class="ov-host-total">${loaded ? rows.length : '—'}<small>services</small></span></button><div class="ov-host-state"><span class="${unavailable ? 'ov-warn-text' : ''}">${esc(result)}</span><small>${esc(stamp(newest(managed)))}</small></div>${host.id !== 'local' ? `<div class="ov-host-ssh"><span>SSH last check: ${esc(host.connection || 'Unchecked')} · ${esc(stamp(host.checked_at))}</span>${!host.trusted ? '<a href="#hosts" class="ov-text-button">Verify fingerprint →</a>' : ''}</div>` : ''}</div>`;
    }).join('') + (!hostsLoaded ? '<p class="ov-panel-note">Remote host list has not loaded yet.</p>' : !hosts.length ? '<a class="ov-text-button ov-add-host" href="#hosts">＋ Connect a remote host</a>' : '');
  }
  function renderPorts() {
    if (!loaded) { $('#ov-ports').innerHTML = '<p class="ov-empty">Waiting for the first TCP check…</p>'; return; }
    const groups = new Map();
    ports.forEach(port => { if (!groups.has(port.host_id)) groups.set(port.host_id, {name:port.host_name, rows:[]}); groups.get(port.host_id).rows.push(port); });
    $('#ov-ports').innerHTML = [...groups].map(([id,group]) => {
      const open = group.rows.filter(item => item.status === 'Open').length;
      const unreachable = group.rows.filter(item => item.status === 'Unreachable').length;
      const other = group.rows.length - open - unreachable;
      return `<button type="button" class="ov-port-group" data-ov-port-host="${esc(id)}" data-ov-key="port-host-${esc(id)}"><span class="ov-port-group-top"><strong>${esc(group.name)}</strong><span>${group.rows.length} recorded →</span></span><span class="ov-port-counts"><span class="ov-good-text">${open} Open</span><span class="${unreachable ? 'ov-warn-text' : ''}">${unreachable} Unreachable</span>${other ? `<span>${other} Unavailable</span>` : ''}</span><small>${esc(stamp(newest(group.rows)))}</small></button>`;
    }).join('') || '<p class="ov-empty">No ports recorded yet. Assign a port in Services or use Add port.</p>';
  }
  function renderSearch() {
    const query = $('#service-search').value.trim().toLowerCase();
    const root = $('#ov-search-results');
    root.hidden = !query;
    if (!query) return;
    if (!loaded) { root.innerHTML = '<p class="ov-empty">Waiting for inventory. Results will appear when it loads.</p>'; return; }
    const matches = value => String(value).toLowerCase().includes(query);
    const results = [
      ...services.filter(item => matches([name(item),item.name,item.unit,item.host_name,item.configured_port].join(' '))).map(item => ({label:name(item),kind:'Service',meta:`${item.host_name || 'This host'} · ${item.status}`,attr:`data-open-detail="${esc(item.id)}"`,key:`service-${item.id}`})),
      ...[{id:'local', name:'This host', address:location.hostname},...hosts].filter(item => matches([item.name,item.address,item.username].join(' '))).map(item => ({label:item.name,kind:'Host',meta:item.address,attr:`data-ov-host="${esc(item.id)}"`,key:`host-${item.id}`})),
      ...ports.filter(item => matches([item.name,item.address,item.host_name,item.port,item.source].join(' '))).map(item => ({label:`${item.name} · ${item.port}`,kind:'TCP port',meta:`${item.address || item.host_name} · ${item.status}`,attr:`data-ov-port="${esc(item.id)}"`,key:`port-${item.id}`}))
    ];
    root.innerHTML = `<p class="ov-search-count">${results.length} results${results.length > 12 ? ' · Showing 12, refine your search for more' : ''}</p>` + results.slice(0,12).map(item => `<button type="button" class="ov-search-result" ${item.attr} data-ov-key="search-${esc(item.key)}"><span class="ov-result-kind">${item.kind}</span><span><strong>${esc(item.label)}</strong><small>${esc(item.meta)}</small></span><span aria-hidden="true">→</span></button>`).join('') + (!results.length ? '<p class="ov-empty">No matching services, hosts or ports.</p>' : '');
  }
  function render() {
    frame = null;
    const active = document.activeElement;
    const key = active?.dataset.ovKey;
    renderAttention(); renderFavorites(); renderHosts(); renderPorts(); renderSearch();
    if (key) [...$('#overview-view').querySelectorAll('[data-ov-key]')].find(item => item.dataset.ovKey === key)?.focus({preventScroll:true});
  }
  function schedule() { if (frame === null) frame = requestAnimationFrame(render); }
  window.addEventListener('dashboard:inventory', event => { ({services,ports,loaded} = event.detail); schedule(); });
  window.addEventListener('dashboard:hosts', event => { hosts = event.detail; hostsLoaded = true; schedule(); });
  window.addEventListener('dashboard:refresh-result', event => { $('#ov-refresh-error').hidden = event.detail.ok; $('#ov-refresh-error').textContent = event.detail.ok ? '' : `Refresh failed. Displaying the last available results. ${event.detail.message}`; });
  window.addEventListener('dashboard:logout', () => { services=[]; ports=[]; hosts=[]; loaded=false; hostsLoaded=false; $('#service-search').value=''; $('#ov-refresh-error').hidden=true; schedule(); });
  $('#service-search').addEventListener('input', renderSearch);
  $('#ov-attention-expand').addEventListener('click', () => { attentionExpanded=!attentionExpanded; renderAttention(); });
  $('#ov-favorites-expand').addEventListener('click', () => { favoritesExpanded=!favoritesExpanded; renderFavorites(); });
  $('#overview-view').addEventListener('keydown', event => {
    if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('[data-ov-service]')) {
      event.preventDefault(); window.HostDashboard.openServiceDetailFresh(event.target.dataset.ovService);
    }
  });
  $('#overview-view').addEventListener('click', event => {
    const filter = event.target.closest('[data-ov-filter]');
    if (filter) { attentionFilter=filter.dataset.ovFilter; attentionExpanded=false; schedule(); return; }
    const host = event.target.closest('[data-ov-host]');
    if (host) { openHost(host.dataset.ovHost); return; }
    const port = event.target.closest('[data-ov-port]');
    if (port) { const row=ports.find(item => item.id===port.dataset.ovPort); if(row)openPort(row); return; }
    const portHost = event.target.closest('[data-ov-port-host]');
    if (portHost) { $('#port-search').value=''; $('#port-host-filter').value=portHost.dataset.ovPortHost; go('ports'); return; }
    const card = event.target.closest('[data-ov-service]');
    if (card && !event.target.closest('button,a,input,[role="img"]')) { window.HostDashboard.openServiceDetailFresh(card.dataset.ovService); return; }
    const shortcut = event.target.closest('[data-ov-shortcut]');
    if (!shortcut) return;
    const targets = {host:['hosts','host-add-toggle'],port:['ports','manual-port-add'],import:['add-service','import-services'],export:['services','export-services']};
    const [page,id] = targets[shortcut.dataset.ovShortcut]; go(page); document.getElementById(id).click();
  });
})();
