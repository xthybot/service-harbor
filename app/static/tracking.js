/* Timed checks run only in an authenticated page. Persist deadlines, never logs. */
(() => {
  const {trackingCheck, displayName, showToast} = window.HostDashboard;
  const key = 'host-dashboard-tracking-v1';
  const bell = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4M12 2V1"/></svg>';
  let entries = [], services = [], ports = [], ready = false;
  const pending = new Map(), lastRun = new Map(), messages = new Map();
  const canonical = (kind, id) => `${kind === 'manual-port' ? 'manual-port' : 'service'}:${id}`;
  function read() {
    try {
      const values = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(values) ? values.filter(e => e && ['service','manual-port'].includes(e.kind) && typeof e.id === 'string' && Number.isFinite(e.endsAt) && e.endsAt > Date.now() && e.endsAt <= Date.now() + 3600000) : [];
    } catch { return []; }
  }
  entries = read();
  function save() {
    try { localStorage.setItem(key, JSON.stringify(entries)); }
    catch { showToast('Tracking works in this tab, but this browser could not save the deadline.', 'error'); }
  }
  function active(kind,id) { return entries.some(e => canonical(e.kind,e.id) === canonical(kind,id) && e.endsAt > Date.now()); }
  function stop(kind,id) {
    const target = canonical(kind,id);
    entries = entries.filter(e => canonical(e.kind,e.id) !== target);
    pending.get(target)?.abort(); lastRun.delete(target); messages.delete(target);
    save(); render();
  }
  function bind(anchor, kind, id, append = false) {
    if (!anchor) return;
    const parent = append ? anchor : anchor.parentElement;
    parent.querySelector(':scope > .tracking-control')?.remove();
    const wrapper = document.createElement('span'); wrapper.className = 'tracking-control';
    wrapper.dataset.kind = kind; wrapper.dataset.id = id;
    const button = document.createElement('button'); button.type = 'button'; button.className = 'icon-button tracking-bell'; button.innerHTML = bell;
    const menu = document.createElement('span'); menu.className = 'tracking-menu'; menu.hidden = true;
    for (const [minutes,label] of [[5,'5 minutes'],[10,'10 minutes'],[20,'20 minutes'],[60,'1 hour']]) {
      const option = document.createElement('button'); option.type = 'button'; option.textContent = label;
      option.onclick = () => {
        entries = entries.filter(e => canonical(e.kind,e.id) !== canonical(kind,id));
        entries.push({kind,id,endsAt:Date.now()+minutes*60000});
        lastRun.delete(canonical(kind,id)); save(); menu.hidden = true; button.setAttribute('aria-expanded','false'); render(); tick();
      };
      menu.append(option);
    }
    button.setAttribute('aria-expanded','false');
    button.onclick = () => {
      if (active(kind,id)) { stop(kind,id); menu.hidden=true; return; }
      const opening = menu.hidden;
      closeMenus(); menu.hidden = !opening; button.setAttribute('aria-expanded',String(opening));
    };
    wrapper.append(button,menu);
    if (append) parent.append(wrapper); else anchor.before(wrapper);
    paintButtons();
  }
  function closeMenus() {
    document.querySelectorAll('.tracking-menu').forEach(menu => { menu.hidden=true; menu.previousElementSibling.setAttribute('aria-expanded','false'); });
  }
  document.addEventListener('click', event => { if (!event.target.closest('.tracking-control')) closeMenus(); });
  document.addEventListener('keydown', event => { if(event.key==='Escape')closeMenus(); });
  function paintButtons() {
    document.querySelectorAll('.tracking-control').forEach(wrapper => {
      const enabled = active(wrapper.dataset.kind,wrapper.dataset.id);
      const button = wrapper.querySelector('.tracking-bell');
      button.classList.toggle('is-tracking',enabled);
      button.setAttribute('aria-pressed',String(enabled));
      button.title = enabled ? 'Stop timed tracking' : 'Start timed tracking';
      button.setAttribute('aria-label',button.title);
    });
  }
  function render() {
    paintButtons();
    window.HostDashboard.syncTrackingLog();
    const root = document.getElementById('tracking-list');
    const focused = root.querySelector('button:focus')?.dataset.key;
    root.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement('p'); empty.className='ov-empty'; empty.textContent='Use the blue bell in service or port details to start a timed check.'; root.append(empty); return;
    }
    for (const entry of entries) {
      const token=canonical(entry.kind,entry.id);
      const record=entry.kind==='service' ? services.find(s=>s.id===entry.id) : ports.find(p=>p.manual && p.id===entry.id);
      const row=document.createElement('div'); row.className='tracking-item';
      const text=document.createElement('div');
      const name=document.createElement('strong'); name.textContent=record ? entry.kind==='service' ? displayName(record) : record.name : 'Waiting for inventory';
      const meta=document.createElement('small'); const seconds=Math.max(0,Math.ceil((entry.endsAt-Date.now())/1000));
      meta.textContent=`${record?.status || 'Pending'} · ${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')} remaining`;
      const detail=document.createElement('small'); detail.textContent=messages.get(token) || (record?.checked_at ? `Checked ${new Date(record.checked_at).toLocaleTimeString()}` : 'Waiting for check');
      text.append(name,meta,detail);
      const button=document.createElement('button'); button.className='icon-button tracking-bell is-tracking'; button.type='button';button.innerHTML=bell; button.title='Stop timed tracking';button.setAttribute('aria-label',`Stop tracking ${name.textContent}`);button.dataset.key=token;button.onclick=()=>stop(entry.kind,entry.id);
      row.append(text,button);root.append(row);
    }
    if(focused)[...root.querySelectorAll('button')].find(b=>b.dataset.key===focused)?.focus({preventScroll:true});
  }
  async function run(entry) {
    const token=canonical(entry.kind,entry.id);
    if(pending.has(token))return;
    const controller=new AbortController();pending.set(token,controller);lastRun.set(token,Date.now());
    const timeout=setTimeout(()=>controller.abort(),20000);
    try {
      // One page owns each check across tabs when Web Locks is available.
      const check=async()=>{if(active(entry.kind,entry.id)&&ready)await trackingCheck(entry.kind,entry.id,controller.signal);};
      if(navigator.locks) await navigator.locks.request(`dashboard-track-${token}`,{ifAvailable:true},lock=>lock ? check() : undefined);
      else await check();
      messages.delete(token);
    } catch(error) {
      if(active(entry.kind,entry.id)) messages.set(token,controller.signal.aborted ? 'Check timed out' : error.message);
      if(error.status===404)stop(entry.kind,entry.id);
    } finally {clearTimeout(timeout);pending.delete(token);render();}
  }
  function tick() {
    const expired=entries.filter(e=>e.endsAt<=Date.now());
    for(const entry of expired)stop(entry.kind,entry.id);
    if(!ready)return;
    for(const entry of entries) {
      const record=entry.kind==='service' ? services.find(s=>s.id===entry.id) : ports.find(p=>p.manual&&p.id===entry.id);
      if(!record){stop(entry.kind,entry.id);continue;}
      if(Date.now()-(lastRun.get(canonical(entry.kind,entry.id))||0)>=5000)run(entry);
    }
    render();
  }
  window.addEventListener('dashboard:inventory',event=>{services=event.detail.services;ports=event.detail.ports;ready=event.detail.loaded && document.getElementById("login-screen").hidden;render();});
  window.addEventListener('dashboard:logout',()=>{ready=false;services=[];ports=[];messages.clear();closeMenus();for(const controller of pending.values())controller.abort();});
  window.addEventListener('pagehide',()=>{ready=false;for(const controller of pending.values())controller.abort();});
  window.addEventListener('pageshow',event=>{if(event.persisted){entries=read();ready=document.getElementById('login-screen').hidden;tick();}});
  window.addEventListener('storage',event=>{if(event.key!==key)return;entries=read();for(const [token,controller] of pending)if(!entries.some(e=>canonical(e.kind,e.id)===token))controller.abort();render();});
  setInterval(tick,1000);
  window.HostTracking={active,bind};
  render();
})();
