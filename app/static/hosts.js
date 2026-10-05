/* Hosts have explicit key trust. The browser only receives public key material. */
(() => {
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const { api, showToast } = window.HostDashboard;
  let hosts = [], services = [], editId = null, trustTarget = null, loading = false, reloadRequested = false;
  let resolveConfirm = null, hostSaving = false;
  const busy = new Set();

  window.HostDashboard.confirm = (title, copy) => new Promise(resolve => {
    resolveConfirm?.(false);
    resolveConfirm = resolve;
    $('#manage-confirm-title').textContent = title;
    $('#manage-confirm-copy').textContent = copy;
    $('#manage-confirm-modal').hidden = false;
    $('#manage-confirm-cancel').focus();
  });
  function settleConfirm(accepted) {
    $('#manage-confirm-modal').hidden = true;
    resolveConfirm?.(accepted); resolveConfirm = null;
  }
  $('#manage-confirm-cancel').addEventListener('click', () => settleConfirm(false));
  $('#manage-confirm-accept').addEventListener('click', () => settleConfirm(true));

  async function copy(text) {
    if (!text) return;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {
        const input = document.createElement('textarea');
        input.value = text; input.style.position = 'fixed'; input.style.opacity = '0'; document.body.append(input);
        input.select(); const ok = document.execCommand('copy'); input.remove();
        if (!ok) throw new Error('Copy failed. Select the public key and copy it manually.');
      }
      showToast('Public key copied.');
    } catch (error) { showToast(error.message, 'error'); }
  }

  function displayKey(key) {
    $('#ssh-public-key').value = key.public_key || '';
    $('#ssh-key-fingerprint').textContent = key.fingerprint || 'No key generated';
    $('#ssh-key-copy').disabled = !key.public_key;
    $('#ssh-key-download').disabled = !key.public_key;
    $('#ssh-key-generate').hidden = !!key.public_key;
    window.HostDashboard.resizeTextareas();
  }

  function render() {
    $('#hosts-total').textContent = hosts.length;
    $('#hosts-connected').textContent = hosts.filter(host => host.connection === 'Connected').length;
    $('#hosts-list-count').textContent = hosts.length;
    $('#hosts-empty').hidden = hosts.length > 0;
    $('#hosts-grid').innerHTML = hosts.map(host => {
      const rows = services.filter(service => service.host_id === host.id);
      const locked = busy.has(host.id) ? 'disabled' : '';
      const connected = host.connection === 'Connected';
      const pending = host.pin_cleanup_pending;
      const badge = pending === 'delete' ? 'Removal pending' : pending === 'reset' ? 'Pin cleanup pending' : !host.trusted ? 'Verify key' : host.connection || 'Unchecked';
      const scanDisabled = locked || pending ? 'disabled' : '';
      const editDisabled = locked || pending === 'delete' ? 'disabled' : '';
      return `<article class="ssh-host-card"><div class="ssh-host-card-top"><span class="host-device-icon">▣</span><div><h3>${esc(host.name)}</h3><code>${esc(host.username)}@${esc(host.address)}:${host.port}</code></div><span class="status-badge ${connected ? 'status-running' : host.connection === 'Unavailable' ? 'status-unavailable' : 'status-stopped'}">${esc(badge)}</span></div><div class="host-capabilities"><span class="host-capability ${host.journal_access ? 'capability-good' : ''}">${host.journal_access ? '✓ System journal' : host.journal_access === false ? '△ System journal limited' : 'Journal not checked'}</span><span class="host-capability">${host.service_count || 0} services</span>${host.systemd_available ? '<span class="host-capability capability-good">✓ systemd</span>' : ''}</div>${host.last_error ? `<p class="host-diagnostic">${esc(host.last_error)}</p>` : ''}<div class="host-unit-list">${rows.slice(0,5).map(service => `<div><span title="${esc(service.unit)}">${esc(service.display_name || service.name)}</span><span class="status-badge ${service.status === 'Running' ? 'status-running' : service.status === 'Failed' ? 'status-failed' : service.status === 'Unavailable' ? 'status-unavailable' : 'status-stopped'}">${esc(service.status)}</span></div>`).join('')}${rows.length > 5 ? `<small>+${rows.length - 5} more in Services</small>` : ''}</div><div class="host-check-time">${host.checked_at ? `Last check ${esc(new Date(host.checked_at).toLocaleString())}` : 'Connection has not been checked'}${host.fingerprint ? `<code title="${esc(host.fingerprint)}">${esc(host.fingerprint)}</code>` : ''}</div><div class="ssh-host-card-actions"><button class="button button-secondary" data-host-action="scan" data-id="${host.id}" ${scanDisabled}>${host.trusted ? 'Verify key' : 'Verify fingerprint'}</button><button class="button button-primary" data-host-action="check" data-id="${host.id}" ${locked || !host.trusted || pending ? 'disabled' : ''}>${busy.has(host.id) ? 'Working…' : 'Check connection'}</button><button class="host-edit-button" data-host-action="edit" data-id="${host.id}" ${editDisabled} title="Edit host">✎</button><button class="host-edit-button host-remove-button" data-host-action="delete" data-id="${host.id}" ${locked} title="Remove host">⌫</button></div></article>`;
    }).join('');
    window.dispatchEvent(new CustomEvent('dashboard:hosts', { detail: hosts }));
  }

  async function load() {
    if ($('#app-shell').hidden) return;
    if (loading) { reloadRequested = true; return; }
    loading = true;
    try {
      const [data, key] = await Promise.all([api('/api/hosts'), api('/api/ssh-key')]);
      hosts = data.hosts || []; displayKey(key); render();
    } catch (error) { showToast(error.message, 'error'); }
    finally { loading = false; if (reloadRequested) { reloadRequested = false; load(); } }
  }
  window.HostDashboard.refreshHosts = load;

  function edit(host = null) {
    editId = host?.id || null;
    const form = $('#host-form'); form.reset();
    if (host) ['name','address','username','port'].forEach(name => { form.elements[name].value = host[name]; });
    $('#host-form-title').textContent = host ? 'Edit SSH host' : 'Add SSH host';
    $('#host-form-modal').showModal(); form.elements.name.focus();
  }
  $('#host-add-toggle').addEventListener('click', () => edit());
  function closeHostForm(force = false) { if (hostSaving && !force) return; $('#host-form-modal').close(); editId = null; }
  $('#host-form-close').addEventListener('click', () => closeHostForm());
  $('#host-form-cancel').addEventListener('click', () => closeHostForm());
  $('#host-form-modal').addEventListener('cancel', event => { if (hostSaving) event.preventDefault(); });
  $('#host-form-modal').addEventListener('close', () => { editId = null; });
  $('#host-help-toggle').addEventListener('click', () => $('#host-help-modal').showModal());
  ['#host-help-close', '#host-help-done'].forEach(selector => $(selector).addEventListener('click', () => $('#host-help-modal').close()));
  ['#host-form-modal', '#host-help-modal'].forEach(selector => {
    $(selector).addEventListener('click', event => {
      if (event.target !== event.currentTarget) return;
      const box = event.currentTarget.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) { if (selector === '#host-form-modal') closeHostForm(); else event.currentTarget.close(); }
    });
  });
  $('#hosts-refresh').addEventListener('click', load);
  $('#host-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (hostSaving) return;
    const form = event.target, button = form.querySelector('[type="submit"]');
    const body = Object.fromEntries(['name','address','username'].map(name => [name,form.elements[name].value.trim()]));
    body.port = Number(form.elements.port.value);
    const submittedId = editId;
    hostSaving = true;
    const originalLabel = button.textContent;
    button.textContent = 'Saving…';
    [...form.elements].forEach(field => { field.disabled = true; });
    try {
      await api(submittedId ? `/api/hosts/${submittedId}` : '/api/hosts', {method:submittedId ? 'PUT' : 'POST',body:JSON.stringify(body)});
      closeHostForm(true); showToast('Host saved. Verify its fingerprint before connecting.'); await load(); await window.HostDashboard.refreshAll();
    } catch (error) {
      showToast(error.message,'error');
      // A failed pin operation may have durably revoked trust before the error.
      await load();
      void window.HostDashboard.refreshAll();
    }
    finally { hostSaving = false; button.textContent = originalLabel; [...form.elements].forEach(field => { field.disabled = false; }); }
  });
  $('#ssh-key-generate').addEventListener('click', async () => {
    const button = $('#ssh-key-generate'); button.disabled = true;
    try { displayKey(await api('/api/ssh-key',{method:'POST'})); showToast('Dedicated SSH key generated.'); }
    catch(error){showToast(error.message,'error');} finally{button.disabled=false;}
  });
  $('#ssh-key-copy').addEventListener('click', () => copy($('#ssh-public-key').value));
  $('#ssh-key-download').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([$('#ssh-public-key').value+'\n'],{type:'text/plain'}));
    const anchor=document.createElement('a');anchor.href=url;anchor.download='host-dashboard.pub';document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });

  function closeTrust() { $('#host-trust-modal').hidden=true; trustTarget=null; }
  $('#host-trust-cancel').addEventListener('click',closeTrust);
  $('#host-trust-verified').addEventListener('change',event=>{$('#host-trust-accept').disabled=!event.target.checked;});
  $('#host-trust-accept').addEventListener('click',async()=>{
    if(!trustTarget||!$('#host-trust-verified').checked)return;
    const target=trustTarget; const button=$('#host-trust-accept');button.disabled=true;
    try{await api(`/api/hosts/${target.id}/trust`,{method:'POST',body:JSON.stringify({fingerprint:target.fingerprint})});closeTrust();showToast('Host fingerprint pinned. You can now check the connection.');await load();}
    catch(error){showToast(error.message,'error');button.disabled=false;await load();void window.HostDashboard.refreshAll();}
  });
  $('#hosts-grid').addEventListener('click',async event=>{
    const button=event.target.closest('[data-host-action]');if(!button||button.disabled)return;
    const host=hosts.find(item=>item.id===button.dataset.id);if(!host)return;
    const action=button.dataset.hostAction;
    if(action==='edit'){edit(host);return;}
    if(action==='delete'&&!await window.HostDashboard.confirm('Remove host?', 'Remove its dashboard configuration and trusted fingerprint. Registered services must be removed first.'))return;
    busy.add(host.id);render();
    try{
      if(action==='scan'){
        const result=await api(`/api/hosts/${host.id}/scan`,{method:'POST'});
        trustTarget={id:host.id,...result};$('#host-trust-address').textContent=`${host.name} · ${result.address}:${result.port} · ${result.algorithm}`;$('#host-trust-fingerprint').textContent=result.fingerprint;
        $('#host-trust-verified').checked=false;$('#host-trust-accept').disabled=true;$('#host-trust-modal').hidden=false;$('#host-trust-cancel').focus();
      }else if(action==='check'){
        const result=await api(`/api/hosts/${host.id}/check`,{method:'POST'});
        showToast(result.host.connection==='Connected'?'SSH connection verified.':'SSH connection failed. See host details.',result.host.connection==='Connected'?'success':'error');await load();await window.HostDashboard.refreshAll();
      }else if(action==='delete'){await api(`/api/hosts/${host.id}`,{method:'DELETE'});showToast('Host removed.');await load();await window.HostDashboard.refreshAll();}
    }catch(error){showToast(error.message,'error');await load();void window.HostDashboard.refreshAll();}
    finally{busy.delete(host.id);render();}
  });
  window.addEventListener('dashboard:ready',load);
  window.addEventListener('dashboard:inventory',event=>{services=event.detail.services;render();});
  window.addEventListener('hashchange',()=>{if(['#hosts','#add-service'].includes(location.hash))load();});
  window.addEventListener('dashboard:logout',()=>{hosts=[];services=[];reloadRequested=false;busy.clear();displayKey({});render();closeTrust();settleConfirm(false);closeHostForm(true);$('#host-help-modal').close();});

})();
